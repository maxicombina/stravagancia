"""Private HTML workflows, using synthetic inventory only."""
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from .models import Bike, Category, Installation, Item, UsageBaseline
from .services.ownership import create_inventory
from .services.installations import create_installation

UTC = dt_timezone.utc


class GarageViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user('garage-ui', password='test-only-password')
        cls.other = get_user_model().objects.create_user('other-ui', password='test-only-password')
        cls.admin = get_user_model().objects.create_superuser('admin-ui', 'admin@example.test', 'test-only-password')
        cls.category = create_inventory(cls.user, Category, name='Sillines')
        cls.foreign_category = create_inventory(cls.other, Category, name='Privado ajeno')
        cls.a = create_inventory(cls.user, Bike, name='Bici A')
        cls.b = create_inventory(cls.user, Bike, name='Bici B')
        cls.foreign_bike = create_inventory(cls.other, Bike, name='Bici secreta')
        cls.item = create_inventory(cls.user, Item, name='Sillín', category=cls.category)
        cls.incoming = create_inventory(cls.user, Item, name='Segundo sillín', category=cls.category)
        cls.foreign_item = create_inventory(cls.other, Item, name='Objeto secreto', category=cls.foreign_category)

    def setUp(self):
        self.client.force_login(self.user)

    def url(self, name, *args):
        return reverse('garage:' + name, args=args)

    def item_data(self, **changes):
        data = {'name': 'Usado', 'category': str(self.category.pk), 'time_zone': 'UTC'}
        data.update(changes)
        return data

    def mount(self, item, bike, started='2026-01-01T10:00:00', **changes):
        data = {'time_zone': 'UTC', 'started_at': started, 'bike': str(bike.pk), 'slot': 'main_saddle'}
        data.update(changes)
        return self.client.post(self.url('installation-create', item.pk), data)

    def test_anonymous_login_and_default_destination(self):
        self.client.logout()
        self.assertRedirects(self.client.get(self.url('index')), '/accounts/login/?next=/garage/', fetch_redirect_response=False)
        self.assertContains(self.client.get('/accounts/login/'), 'Entrar en Garage')
        response = self.client.post('/accounts/login/', {'username': self.user.username, 'password': 'test-only-password', 'next': '/garage/'})
        self.assertRedirects(response, self.url('index'))

    def test_lists_scoped_even_for_superuser(self):
        for user in (self.user, self.admin):
            self.client.force_login(user)
            for name, private in [('bike-list', 'Bici secreta'), ('item-list', 'Objeto secreto'), ('category-list', 'Privado ajeno')]:
                self.assertNotContains(self.client.get(self.url(name)), private)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url('bike-detail', self.a.pk)).status_code, 404)

    def test_foreign_routes_get_and_post_are_404(self):
        for kind, obj in [('bike', self.foreign_bike), ('item', self.foreign_item), ('category', self.foreign_category)]:
            for suffix in ('detail', 'edit'):
                for method in ('get', 'post'):
                    with self.subTest(kind=kind, suffix=suffix, method=method):
                        expected = 405 if suffix == 'detail' and method == 'post' else 404
                        self.assertEqual(getattr(self.client, method)(self.url(kind + '-' + suffix, obj.pk)).status_code, expected)
        self.assertEqual(self.client.post(self.url('bike-detail', self.a.pk)).status_code, 405)
        for suffix in ('retire', 'reactivate'):
            self.assertEqual(self.client.post(self.url('item-' + suffix, self.foreign_item.pk)).status_code, 404)
        for route in ('installation-create', 'baseline-create'):
            self.assertEqual(self.client.post(self.url(route, self.foreign_item.pk)).status_code, 404)

    def test_create_edit_and_owner_uuid_forgery_ignored(self):
        response = self.client.post(self.url('item-create'), self.item_data(owner=str(self.other.pk), id=str(self.foreign_item.pk)))
        self.assertEqual(response.status_code, 302)
        obj = Item.objects.get(name='Usado')
        self.assertEqual(obj.owner_id, self.user.pk)
        self.assertNotEqual(obj.pk, self.foreign_item.pk)
        response = self.client.post(self.url('item-edit', obj.pk), self.item_data(name='Actualizado', retired_at='2026-01-01'))
        self.assertEqual(response.status_code, 302)
        obj.refresh_from_db()
        self.assertIsNone(obj.retired_at)
        self.assertEqual(obj.name, 'Actualizado')

    def test_foreign_choices_and_invalid_purchase_show_errors(self):
        response = self.client.post(self.url('item-create'), self.item_data(category=str(self.foreign_category.pk)))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors.get('category'))
        response = self.client.post(self.url('bike-create'), {'name': 'Money', 'time_zone': 'UTC', 'purchase_amount': '4.50'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors.get('purchase_currency'))
        self.assertFalse(Bike.objects.filter(name='Money').exists())

    def test_category_create_archive_edit_and_case_conflict(self):
        response = self.client.post(self.url('category-create'), {'name': '  Casco  ', 'notes': 'nota'})
        self.assertEqual(response.status_code, 302)
        category = Category.objects.get(name='Casco')
        self.assertEqual(self.client.post(self.url('category-edit', category.pk), {'name': 'Casco', 'is_archived': 'on'}).status_code, 302)
        self.assertContains(self.client.get(self.url('category-list') + '?state=retired'), 'Casco')
        response = self.client.post(self.url('category-create'), {'name': 'CASCO'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('name', response.context['form'].errors)

    def test_used_readings_independent_known_zero_and_exact_units(self):
        response = self.client.post(self.url('item-used-create'), self.item_data(
            acquired_on='2025-01-01', acquisition_anchor_at='2026-01-01T10:00:00',
            previous_distance='1.234567', previous_distance_cut='2026-02-01T10:00:00', previous_distance_scope='lifetime',
            previous_time='0', previous_time_cut='2026-03-01T10:00:00', previous_time_scope='acquisition',
            reading_source='manual', reading_estimated='on'))
        self.assertEqual(response.status_code, 302)
        item = Item.objects.get(name='Usado')
        readings = {r.metric: r for r in UsageBaseline.objects.filter(item=item)}
        self.assertEqual(readings['distance_m'].value, Decimal('1234.567'))
        self.assertEqual(readings['moving_time_s'].value, 0)
        self.assertEqual(readings['moving_time_s'].scope, 'acquisition')
        self.assertNotIn('ride_count', readings)
        self.assertEqual(item.acquisition_anchor_at, datetime(2026, 1, 1, 10, tzinfo=UTC))

    def test_used_creation_rolls_back_item_and_first_reading(self):
        from .services.baselines import record_baseline
        calls = []
        def failure(actor, **values):
            calls.append(values)
            if len(calls) == 2:
                raise ValidationError('Synthetic second reading failure')
            return record_baseline(actor, **values)
        with patch('garage.web_forms.record_baseline', side_effect=failure):
            response = self.client.post(self.url('item-used-create'), self.item_data(
                previous_distance='3', previous_distance_cut='2026-01-01T10:00:00', previous_distance_scope='lifetime',
                previous_time='1', previous_time_cut='2026-01-01T10:00:00', previous_time_scope='lifetime', reading_source='manual'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Synthetic second reading failure')
        self.assertFalse(Item.objects.filter(name='Usado').exists())
        self.assertFalse(UsageBaseline.objects.exists())

    def test_unknown_is_not_zero_and_bad_readings_rejected(self):
        for changes in [dict(previous_rides='1.5'), dict(previous_distance='-1'),
                        dict(previous_distance='1', previous_distance_scope='acquisition'),
                        dict(previous_distance='1')]:
            response = self.client.post(self.url('item-used-create'), self.item_data(**changes))
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context['form'].errors)
        self.assertEqual(self.client.post(self.url('item-used-create'), self.item_data()).status_code, 302)
        self.assertFalse(UsageBaseline.objects.exists())

    def test_dst_invalid_times_and_valid_anchor_conversion(self):
        for instant in ['2026-03-29T02:30:00', '2026-10-25T02:30:00']:
            response = self.client.post(self.url('item-create'), self.item_data(time_zone='Europe/Madrid', acquisition_anchor_at=instant))
            self.assertEqual(response.status_code, 200)
            self.assertIn('acquisition_anchor_at', response.context['form'].errors)
        response = self.client.post(self.url('item-create'), self.item_data(time_zone='Europe/Madrid', acquisition_anchor_at='2026-03-29T03:30:00'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Item.objects.get(name='Usado').acquisition_anchor_at, datetime(2026, 3, 29, 1, 30, tzinfo=UTC))

    def test_mount_close_remount_a_b_a_keeps_history(self):
        self.assertEqual(self.mount(self.item, self.a).status_code, 302)
        period = Installation.objects.get(item=self.item)
        self.assertEqual(self.client.post(self.url('installation-close', period.pk), {'at': '2026-01-02T10:00:00', 'time_zone': 'UTC'}).status_code, 302)
        self.assertEqual(self.mount(self.item, self.b, '2026-01-02T10:00:00', ended_at='2026-01-03T10:00:00').status_code, 302)
        self.assertEqual(self.mount(self.item, self.a, '2026-01-03T10:00:00').status_code, 302)
        self.assertEqual(list(Installation.objects.filter(item=self.item).order_by('started_at').values_list('bike_id', flat=True)), [self.a.pk, self.b.pk, self.a.pk])
        self.assertContains(self.client.get(self.url('item-detail', self.item.pk)), 'Historial completo')

    def test_foreign_destination_and_overlap_are_form_errors(self):
        self.assertEqual(self.mount(self.item, self.foreign_bike).status_code, 200)
        self.assertEqual(self.mount(self.item, self.a).status_code, 302)
        response = self.mount(self.incoming, self.a)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        self.assertEqual(Installation.objects.count(), 1)

    def test_replace_transfer_and_item_destination(self):
        self.mount(self.item, self.a)
        period = Installation.objects.get(item=self.item)
        response = self.client.post(self.url('installation-replace', period.pk), {'at': '2026-01-02T10:00:00', 'time_zone': 'UTC', 'incoming_item': str(self.incoming.pk)})
        self.assertEqual(response.status_code, 302)
        incoming = Installation.objects.get(item=self.incoming)
        response = self.client.post(self.url('installation-transfer', incoming.pk), {'at': '2026-01-03T10:00:00', 'time_zone': 'UTC', 'parent_item': str(self.item.pk), 'slot': 'cleat'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Installation.objects.filter(item=self.incoming, parent_item=self.item).count(), 1)
        self.assertContains(self.client.get(self.url('item-detail', self.item.pk)), 'Material montado sobre este objeto')

    def test_retirement_closes_history_edit_preserves_state_reactivate_post_only(self):
        self.mount(self.item, self.a)
        response = self.client.post(self.url('item-retire', self.item.pk), {'at': '2026-01-02T10:00:00', 'time_zone': 'UTC'})
        self.assertEqual(response.status_code, 302)
        self.item.refresh_from_db()
        retired = self.item.retired_at
        self.assertEqual(Installation.objects.get(item=self.item).ended_at, retired)
        self.assertEqual(self.client.post(self.url('item-edit', self.item.pk), self.item_data(name='Retirado')).status_code, 302)
        self.item.refresh_from_db()
        self.assertEqual(self.item.retired_at, retired)
        self.assertEqual(self.client.get(self.url('item-reactivate', self.item.pk)).status_code, 405)
        self.assertEqual(self.client.post(self.url('item-reactivate', self.item.pk)).status_code, 302)
        self.assertEqual(Installation.objects.get(item=self.item).ended_at, retired)

    def test_baseline_route_fixed_item_edit_and_foreign_reading(self):
        data = {'item': str(self.foreign_item.pk), 'metric': 'distance_m', 'scope': 'lifetime', 'cut_at': '2026-01-01T10:00:00', 'time_zone': 'UTC', 'value': '12.345', 'source': 'manual'}
        self.assertEqual(self.client.post(self.url('baseline-create', self.item.pk), data).status_code, 302)
        reading = UsageBaseline.objects.get()
        self.assertEqual(reading.item_id, self.item.pk)
        data['value'] = '13.125'
        self.assertEqual(self.client.post(self.url('baseline-edit', reading.pk), data).status_code, 302)
        reading.refresh_from_db()
        self.assertEqual(reading.value, Decimal('13.125'))
        self.assertEqual(UsageBaseline.objects.count(), 1)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url('baseline-edit', reading.pk)).status_code, 404)
        self.assertEqual(self.client.post(self.url('baseline-edit', reading.pk), data).status_code, 404)

    def test_foreign_installation_all_routes_denied_and_get_no_mutation(self):
        period = create_installation(self.other, item=self.foreign_item, bike=self.foreign_bike, started_at=datetime(2026, 1, 1, tzinfo=UTC))
        for action in ['edit', 'close', 'replace', 'transfer']:
            for method in ('get', 'post'):
                self.assertEqual(getattr(self.client, method)(self.url('installation-' + action, period.pk)).status_code, 404)
        self.mount(self.item, self.a)
        own = Installation.objects.get(item=self.item)
        for action in ['edit', 'close', 'replace', 'transfer']:
            self.assertEqual(self.client.get(self.url('installation-' + action, own.pk)).status_code, 200)
        own.refresh_from_db()
        self.assertIsNone(own.ended_at)

    def test_escape_notes_search_pagination_and_state(self):
        malicious = '<script>alert("x")</script>'
        obj = create_inventory(self.user, Bike, name=malicious, notes=malicious)
        response = self.client.get(self.url('bike-detail', obj.pk))
        self.assertNotContains(response, malicious)
        self.assertContains(response, '&lt;script&gt;')
        for n in range(25):
            create_inventory(self.user, Bike, name=f'Pagination {n:02}')
        response = self.client.get(self.url('bike-list') + '?q=Pagination&page=2')
        self.assertEqual(len(response.context['page']), 5)
        self.assertContains(response, 'Página 2 de 2')
        self.assertNotContains(response, 'Bici secreta')

    def test_csrf_missing_rejected_and_token_accepted(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        url = self.url('category-create')
        self.assertEqual(client.post(url, {'name': 'CSRF'}).status_code, 403)
        client.get(url)
        token = client.cookies['csrftoken'].value
        self.assertEqual(client.post(url, {'name': 'CSRF', 'csrfmiddlewaretoken': token}).status_code, 302)
        self.assertEqual(client.put(self.url('item-edit', self.item.pk), HTTP_X_CSRFTOKEN=token).status_code, 405)

    def test_logout_returns_to_login_and_clears_session(self):
        response = self.client.post('/accounts/logout/', {'next': '/accounts/login/?next=/garage/'})
        self.assertRedirects(response, '/accounts/login/?next=/garage/')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_microseconds_preserved_on_anchor_installation_and_baseline_edit(self):
        # Forms show instants in the viewer's zone (garage-032); UTC here keeps the wall times below.
        self.client.cookies['garage_tz'] = 'UTC'
        instant = datetime(2026, 1, 1, 10, 0, 0, 123456, tzinfo=UTC)
        self.client.post(self.url('item-edit', self.item.pk), self.item_data(name='Sillín', acquisition_anchor_at='2026-01-01T11:00:00.123456', time_zone='Europe/Madrid'))
        self.item.refresh_from_db()
        self.assertEqual(self.item.acquisition_anchor_at, instant)
        response = self.client.get(self.url('item-edit', self.item.pk))
        self.assertContains(response, '2026-01-01T10:00:00.123456')
        self.assertNotContains(response, 'type="datetime-local"')
        self.assertEqual(self.mount(self.item, self.a, '2026-01-01T10:00:00.123456').status_code, 302)
        period = Installation.objects.get(item=self.item)
        response = self.client.get(self.url('installation-edit', period.pk))
        self.assertContains(response, '2026-01-01T10:00:00.123456')
        self.assertEqual(self.client.post(self.url('installation-edit', period.pk), {'time_zone': 'UTC', 'started_at': '2026-01-01T10:00:00.123456', 'bike': str(self.a.pk)}).status_code, 302)
        period.refresh_from_db()
        self.assertEqual(period.started_at, instant)
        data = {'metric': 'ride_count', 'scope': 'lifetime', 'cut_at': '2026-01-01T11:00:00.123456', 'time_zone': 'Europe/Madrid', 'value': '0', 'source': 'manual'}
        self.assertEqual(self.client.post(self.url('baseline-create', self.item.pk), data).status_code, 302)
        reading = UsageBaseline.objects.get()
        self.assertEqual(reading.cut_at, instant)
        self.assertContains(self.client.get(self.url('baseline-edit', reading.pk)), '2026-01-01T10:00:00.123456')
        data.update(time_zone='UTC', cut_at='2026-01-01T10:00:00.123456')
        self.assertEqual(self.client.post(self.url('baseline-edit', reading.pk), data).status_code, 302)
        reading.refresh_from_db()
        self.assertEqual(reading.cut_at, instant)


ENGLISH = (  # what the phone forms said before garage-047 F07, as fragments
    'This item is already installed', 'This position is occupied', 'form a cycle', 'Choose exactly one',
    'cannot contain itself', 'The end must be later', 'must finish by', 'overlaps recorded inactivity', 'nonempty name',
    'already have a category', 'Enter both', 'Choose one of your own', "Declare the reading", 'cannot precede',
    'Confirm the acquisition', 'Correct the existing reading', 'Constraint', 'Only service readings', 'Choose an intervention',
    'number of rides', 'exactly representable', 'finite nonnegative', 'Ensure that', 'Enter a number', 'Enter a valid date',
    'Null characters', 'position key', 'strictly inside', 'already closed', 'acquisition anchor', 'acquisition readings',
    'This field is required', 'Select a valid choice', 'not a valid UUID')
ENGLISH_LABELS = ('Name', 'Notes', 'Item', 'Service event')
CONTROLS = ('input', 'select', 'textarea')


def page_of(response):
    from .test_html import parse
    return parse(response.content.decode())


def wrapper_of(page, name):
    """The `div.field` that holds the control `name`."""
    from .test_html import find_all
    wrappers = [w for w in find_all(page, 'div', cls='field') if any(find_all(w, tag, name=name) for tag in CONTROLS)]
    assert len(wrappers) == 1, f'{len(wrappers)} div.field hold {name!r}'
    return wrappers[0]


def errors_under(page, name):
    from .test_html import find_all, visible_text
    return [visible_text(li) for ul in find_all(wrapper_of(page, name), 'ul', cls='errorlist') for li in find_all(ul, 'li')]


def every_error(page):
    from .test_html import find_all, visible_text
    return [visible_text(li) for ul in find_all(page, 'ul', cls='errorlist') for li in find_all(ul, 'li')]


def page_text(page):
    from .test_html import visible_text
    return visible_text(page)


class SpanishFormTests(TestCase):
    """garage-047 F07 and F09: the phone forms speak Spanish, say each error once, and their titles name one thing."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user('spanish-forms', password='test-only-password')
        cls.category = create_inventory(cls.user, Category, name='Sillines')
        cls.a = create_inventory(cls.user, Bike, name='Bici A')
        cls.b = create_inventory(cls.user, Bike, name='Bici B')
        cls.item = create_inventory(cls.user, Item, name='Sillín', category=cls.category)
        cls.second = create_inventory(cls.user, Item, name='Segundo sillín', category=cls.category)

    def setUp(self):
        self.client.force_login(self.user)
        self.client.cookies['garage_tz'] = 'UTC'

    def url(self, name, *args):
        return reverse('garage:' + name, args=args)

    def rejected(self, url, data):
        """A POST that the page refuses: shown again (200 or 400), with its errors."""
        response = self.client.post(url, data)
        self.assertIn(response.status_code, (200, 400), response)
        return page_of(response)

    def assert_spanish(self, page):
        text = page_text(page)
        self.assertEqual([english for english in ENGLISH if english in text], [])

    # Cases: each returns the page of a rejected POST, and the caller checks that nothing was saved.

    def overlapping_mount(self):
        create_installation(self.user, item=self.item, bike=self.a, started_at=datetime(2026, 1, 1, 10, tzinfo=UTC))
        return self.rejected(self.url('installation-create', self.item.pk),
                             {'time_zone': 'UTC', 'started_at': '2026-01-02T10:00', 'bike': str(self.b.pk)})

    def cyclic_mount(self):
        create_installation(self.user, item=self.second, parent_item=self.item, started_at=datetime(2026, 1, 1, 10, tzinfo=UTC))
        return self.rejected(self.url('installation-create', self.item.pk),
                             {'time_zone': 'UTC', 'started_at': '2026-01-02T10:00', 'parent_item': str(self.second.pk)})

    def occupied_position(self):
        create_installation(self.user, item=self.item, bike=self.a, slot='main_saddle', started_at=datetime(2026, 1, 1, 10, tzinfo=UTC))
        return self.rejected(self.url('installation-create', self.second.pk),
                             {'time_zone': 'UTC', 'started_at': '2026-01-02T10:00', 'bike': str(self.a.pk), 'slot': 'main_saddle'})

    def position_that_is_not_a_key(self):
        return self.rejected(self.url('installation-create', self.item.pk),
                             {'time_zone': 'UTC', 'started_at': '2026-01-02T10:00', 'bike': str(self.a.pk), 'slot': 'Rueda X'})

    def outgoing_period(self, **ends):
        return create_installation(self.user, item=self.item, bike=self.a, started_at=datetime(2026, 1, 10, 10, tzinfo=UTC), **ends)

    def replacement_before_the_start(self):
        period = self.outgoing_period()
        return self.rejected(self.url('installation-replace', period.pk),
                             {'time_zone': 'UTC', 'at': '2026-01-05T10:00', 'incoming_item': str(self.second.pk)})

    def transfer_before_the_start(self):
        period = self.outgoing_period()
        return self.rejected(self.url('installation-transfer', period.pk), {'time_zone': 'UTC', 'at': '2026-01-05T10:00', 'bike': str(self.b.pk)})

    def closing_a_closed_period(self):
        period = self.outgoing_period(ended_at=datetime(2026, 1, 20, 10, tzinfo=UTC))  # another tab closed it
        return self.rejected(self.url('installation-close', period.pk), {'time_zone': 'UTC', 'at': '2026-01-25T10:00'})

    def reading(self, **changes):
        data = {'metric': 'distance_m', 'scope': 'lifetime', 'cut_at': '2026-02-01T10:00', 'time_zone': 'UTC', 'value': '10', 'source': 'manual'}
        data.update(changes)
        return self.rejected(self.url('baseline-create', self.item.pk), data)

    def event(self):
        from .models import ServiceType, ServiceEvent
        from .services.maintenance import save_maintenance
        kind = save_maintenance(self.user, ServiceType, name='Cambio')
        return save_maintenance(self.user, ServiceEvent, item=self.item, service_type=kind, performed_at=datetime(2026, 2, 1, 10, tzinfo=UTC))

    def anchored_item_with_a_reading(self):
        from .services.baselines import record_baseline
        from .services.ownership import update_inventory
        update_inventory(self.user, Item, self.item.pk, acquisition_anchor_at=datetime(2026, 1, 1, 10, tzinfo=UTC))
        record_baseline(self.user, item=self.item, metric='distance_m', scope='acquisition', cut_at=datetime(2026, 2, 1, 10, tzinfo=UTC),
                        value=Decimal('1000'), source='manual')

    def repeated_reading(self):
        from .services.baselines import record_baseline
        record_baseline(self.user, item=self.item, metric='distance_m', scope='lifetime', cut_at=datetime(2026, 2, 1, 10, tzinfo=UTC),
                        value=Decimal('5'), source='manual')
        return self.reading()

    def item_edit(self, **changes):
        data = {'name': 'Sillín', 'category': str(self.category.pk), 'time_zone': 'UTC'}
        data.update(changes)
        return self.rejected(self.url('item-edit', self.item.pk), data)

    def anchor_after_a_reading(self):
        self.anchored_item_with_a_reading()
        return self.item_edit(acquisition_anchor_at='2026-03-01T10:00')

    def anchor_removed_under_readings(self):
        self.anchored_item_with_a_reading()
        return self.item_edit(acquisition_anchor_at='')

    # F07: labels

    def test_reading_labels_are_spanish(self):
        from .test_html import find_all, visible_text
        page = page_of(self.client.get(self.url('baseline-create', self.item.pk)))
        for name, label in (('item', 'Objeto'), ('service_event', 'Intervención')):
            with self.subTest(field=name):
                self.assertEqual([visible_text(found) for found in find_all(wrapper_of(page, name), 'label')], [label])

    # F07: errors in Spanish

    def test_an_overlapping_mount_says_so_in_spanish(self):
        page = self.overlapping_mount()
        self.assertIn('Este objeto ya está montado en ese período.', every_error(page))
        self.assertEqual(Installation.objects.count(), 1)

    def test_a_cycle_says_so_in_spanish(self):
        page = self.cyclic_mount()
        self.assertEqual(errors_under(page, 'parent_item'), ['Esos montajes forman un ciclo en un período común.'])
        self.assertEqual(Installation.objects.count(), 1)

    def test_an_occupied_position_says_so_in_spanish(self):
        page = self.occupied_position()
        self.assertEqual(errors_under(page, 'slot'), ['Esa posición ya está ocupada en ese período.'])
        self.assertEqual(Installation.objects.count(), 1)

    def test_an_empty_category_name_says_so_in_spanish(self):
        for name in ('', '   '):
            with self.subTest(name=name):
                page = self.rejected(self.url('category-create'), {'name': name})
                self.assertEqual(errors_under(page, 'name'), ['Este campo es obligatorio.'])
        self.assertEqual(Category.objects.filter(owner=self.user).count(), 1)

    def test_a_repeated_category_says_so_in_spanish(self):
        for name in ('Sillines', ' SILLINES '):
            with self.subTest(name=name):
                page = self.rejected(self.url('category-create'), {'name': name})
                self.assertEqual(every_error(page), ['Ya tienes una categoría con ese nombre.'])
        self.assertEqual(Category.objects.filter(owner=self.user).count(), 1)

    def test_a_price_without_currency_says_so_in_spanish(self):
        page = self.rejected(self.url('bike-create'), {'name': 'Con precio', 'time_zone': 'UTC', 'purchase_amount': '4.50'})
        self.assertEqual(errors_under(page, 'purchase_currency'), ['Indica precio y moneda, o ninguno de los dos.'])
        self.assertFalse(Bike.objects.filter(name='Con precio').exists())

    def test_too_many_decimals_say_so_in_spanish(self):
        page = self.rejected(self.url('item-create'), {'name': 'Caro', 'category': str(self.category.pk), 'time_zone': 'UTC',
                                                       'purchase_amount': '1.234', 'purchase_currency': 'EUR'})
        self.assertEqual(errors_under(page, 'purchase_amount'), ['Como máximo 2 decimales.'])
        self.assertEqual(every_error(page), ['Como máximo 2 decimales.'], 'a price was typed: nothing to say about the currency')
        self.assertEqual(errors_under(self.reading(value='1.2345'), 'value'), ['El valor exacto admite como máximo 3 decimales.'])
        self.assertEqual(errors_under(self.reading(value='123456789012345678'), 'value'),
                         ['Escribe un valor positivo o cero, dentro del máximo admitido.'])
        self.assertFalse(Item.objects.filter(name='Caro').exists())
        self.assertFalse(UsageBaseline.objects.exists())

    def test_a_wrong_currency_is_said_even_when_the_price_is_wrong_too(self):
        """Two mistakes, two messages: a price the form rejects silences only «precio y moneda», never a bad code."""
        code = 'Usa un código de moneda ISO 4217, por ejemplo EUR.'
        cases = [  # a decimal comma and a lowercase code, natural on a Spanish keyboard; and the same on an edit
            ('create', self.url('bike-create'), {'name': 'Con precio', 'time_zone': 'UTC', 'purchase_amount': '12,50',
                                                 'purchase_currency': 'eur'}, 'Introduce un número.'),
            ('edit', self.url('item-edit', self.item.pk), {'name': 'Sillín', 'category': str(self.category.pk), 'time_zone': 'UTC',
                                                           'purchase_amount': '1.234', 'purchase_currency': 'XYZ'}, 'Como máximo 2 decimales.'),
        ]
        for case, url, data, price in cases:
            with self.subTest(case=case):
                page = self.rejected(url, data)
                self.assertEqual(errors_under(page, 'purchase_amount'), [price])
                self.assertEqual(errors_under(page, 'purchase_currency'), [code])
                self.assertEqual(every_error(page), [price, code])
        # A currency the form itself rejects, with a good price: only its own message, never «precio y moneda».
        page = self.rejected(self.url('bike-create'), {'name': 'Con precio', 'time_zone': 'UTC', 'purchase_amount': '4.50',
                                                       'purchase_currency': 'EURO'})
        self.assertEqual(every_error(page), ['Como máximo 3 caracteres.'])
        self.assertFalse(Bike.objects.filter(name='Con precio').exists())
        self.item.refresh_from_db()
        self.assertEqual((self.item.purchase_amount, self.item.purchase_currency), (None, None))

    def test_the_admin_form_also_reports_a_wrong_currency_next_to_a_wrong_price(self):
        """OwnedInventoryForm backs the admin too, in English there."""
        from .forms import BikeForm
        form = BikeForm({'name': 'Con precio', 'purchase_amount': '12,50', 'purchase_currency': 'eur'}, user=self.user)
        self.assertFalse(form.is_valid())
        self.assertEqual({field: [str(message) for message in messages] for field, messages in form.errors.items()},
                         {'purchase_amount': ['Enter a number.'], 'purchase_currency': ['Enter an uppercase ISO 4217 currency code.']})

    def select_pages(self):
        """The phone pages with a select of own resources: (route, args, the rest of a valid POST, the select), and a
        mount that the period pages change."""
        period = create_installation(self.user, item=self.item, bike=self.a, started_at=datetime(2026, 1, 1, 10, tzinfo=UTC))
        mount = {'time_zone': 'UTC', 'started_at': '2026-02-01T10:00'}
        change = {'time_zone': 'UTC', 'at': '2026-02-01T10:00'}
        return period, [
            ('item-create', (), {'name': 'Nulo', 'time_zone': 'UTC'}, 'category'),
            ('item-edit', (self.second.pk,), {'name': 'Segundo sillín', 'time_zone': 'UTC'}, 'category'),
            ('installation-create', (self.second.pk,), mount, 'bike'),
            ('installation-create', (self.second.pk,), dict(mount, bike=str(self.a.pk)), 'parent_item'),
            ('installation-edit', (period.pk,), dict(mount, started_at='2026-01-01T10:00'), 'bike'),
            ('installation-transfer', (period.pk,), change, 'parent_item'),
            ('installation-replace', (period.pk,), change, 'incoming_item'),
            ('baseline-create', (self.item.pk,), {'metric': 'distance_m', 'scope': 'service', 'cut_at': '2026-02-01T10:00',
                                                  'time_zone': 'UTC', 'value': '10', 'source': 'manual'}, 'service_event'),
            ('item-part-create', (self.second.pk,), change, 'item'),
        ]

    def assert_forged_select_refused(self, forged, expected):
        period, cases = self.select_pages()
        for name, args, data, field in cases:
            with self.subTest(page=name, field=field):
                page = self.rejected(self.url(name, *args), dict(data, **{field: forged}))
                self.assertEqual(errors_under(page, field), [expected])
                self.assert_spanish(page)
        self.assertEqual(list(Installation.objects.values_list('pk', 'ended_at')), [(period.pk, None)])
        self.assertFalse(Item.objects.filter(name='Nulo').exists())
        self.assertFalse(UsageBaseline.objects.exists())

    def test_a_null_character_in_a_select_says_so_in_spanish(self):
        """Only a forged POST sends one: ModelChoiceField refuses it before its validators, so FIELD_MESSAGES never sees it."""
        self.assert_forged_select_refused('\x00', 'No se admiten caracteres nulos.')

    def test_a_select_value_that_is_not_even_a_key_says_choose_a_valid_option(self):
        """Only a forged POST sends one. The model's key field refuses it, in English and with the value in the text, before
        ModelChoiceField looks the choice up (garage-047 B2b-R1-02)."""
        self.assert_forged_select_refused('abc', 'Elige una opción válida.')

    def test_a_bad_zone_says_only_that(self):
        """Without a valid zone the local times stay naive: «con su zona horaria» under a date typed right would be false."""
        anchor = '2026-01-01T10:00'
        for zone, message in (('Marte/Olimpo', 'Elige una zona horaria IANA válida.'), ('', 'Este campo es obligatorio.')):
            cases = [
                ('bike', lambda: self.rejected(self.url('bike-create'), {'name': 'Zona', 'time_zone': zone, 'acquisition_anchor_at': anchor})),
                ('item edit', lambda: self.item_edit(time_zone=zone, acquisition_anchor_at=anchor)),
                ('reading', lambda: self.reading(time_zone=zone)),
                ('nothing else typed', lambda: self.rejected(self.url('bike-create'), {'name': 'Zona', 'time_zone': zone})),
            ]
            for case, run in cases:
                with self.subTest(case=case, zone=zone):
                    page = run()
                    self.assertEqual(errors_under(page, 'time_zone'), [message])
                    self.assertEqual(every_error(page), [message])
        # A date that is wrong too is still said, next to the zone.
        page = self.rejected(self.url('bike-create'), {'name': 'Zona', 'time_zone': 'Marte/Olimpo', 'acquisition_anchor_at': 'mañana'})
        self.assertEqual(errors_under(page, 'acquisition_anchor_at'), ['Introduce una fecha y hora local.'])
        self.assertEqual(errors_under(page, 'time_zone'), ['Elige una zona horaria IANA válida.'])
        self.assertFalse(Bike.objects.filter(name='Zona').exists())
        self.item.refresh_from_db()
        self.assertIsNone(self.item.acquisition_anchor_at)
        self.assertFalse(UsageBaseline.objects.exists())

    def test_reading_errors_are_spanish(self):
        event = self.event()
        cases = [
            ('empty source', dict(source=''), 'source', 'Este campo es obligatorio.'),
            ('service without intervention', dict(scope='service'), 'service_event',
             'La intervención va con el ámbito «Desde una intervención concreta», y sólo con él.'),
            ('intervention with another scope', dict(service_event=str(event.pk)), 'service_event',
             'La intervención va con el ámbito «Desde una intervención concreta», y sólo con él.'),
            ('before its intervention', dict(scope='service', service_event=str(event.pk), cut_at='2026-01-15T10:00'), 'cut_at',
             'La lectura no puede ser anterior a la intervención.'),
            ('fractional rides', dict(metric='ride_count', value='1.5'), 'value', 'Las salidas son un número entero.'),
            ('acquisition without its start', dict(scope='acquisition'), 'scope',
             'Confirma antes el inicio de la adquisición para este ámbito.'),
        ]
        for case, changes, field, message in cases:
            with self.subTest(case=case):
                self.assertEqual(errors_under(self.reading(**changes), field), [message])
        from .services.ownership import update_inventory
        update_inventory(self.user, Item, self.item.pk, acquisition_anchor_at=datetime(2026, 3, 1, 10, tzinfo=UTC))
        self.assertEqual(errors_under(self.reading(scope='acquisition'), 'cut_at'), ['La lectura no puede ser anterior a la adquisición.'])
        self.assertFalse(UsageBaseline.objects.exists())

    def test_a_repeated_reading_says_so_in_spanish(self):
        """A new reading at the instant of another of the same metric and scope: the form refuses it by the constraint."""
        from .services.baselines import record_baseline
        event = self.event()
        for scope, extra in (('lifetime', {}), ('service', {'service_event': event})):
            with self.subTest(scope=scope):
                record_baseline(self.user, item=self.item, metric='distance_m', scope=scope, cut_at=datetime(2026, 2, 1, 10, tzinfo=UTC),
                                value=Decimal('5'), source='manual', **extra)
                page = self.reading(scope=scope, **{key: str(value.pk) for key, value in extra.items()})
                self.assertEqual(every_error(page), ['Ya hay una lectura de esa métrica y ámbito en ese instante: corrígela.'])
        self.assertEqual(sorted(UsageBaseline.objects.values_list('value', flat=True)), [Decimal('5'), Decimal('5')])

    def test_previous_readings_say_so_in_spanish(self):
        page = self.rejected(self.url('item-used-create'), {'name': 'Usado', 'category': str(self.category.pk), 'time_zone': 'UTC',
                                                            'previous_distance': 'mucho', 'previous_distance_cut': '2026-01-01T10:00',
                                                            'previous_distance_scope': 'lifetime', 'reading_source': 'manual'})
        self.assertEqual(errors_under(page, 'previous_distance'), ['Introduce un número.'])
        self.assertFalse(Item.objects.filter(name='Usado').exists())

    def test_a_start_of_use_typed_wrong_says_only_that(self):
        """Crear material usado: a start was typed, so «Confirma el inicio…» under a reading «Desde mi adquisición» would be
        false (garage-047 F07, D4: never a false error). Left empty, the reading still asks for it."""
        used = {'name': 'Usado', 'category': str(self.category.pk), 'time_zone': 'UTC', 'reading_source': 'manual',
                'previous_distance': '10', 'previous_distance_cut': '2026-02-01T10:00', 'previous_distance_scope': 'acquisition'}
        both = dict(used, previous_time='2', previous_time_cut='2026-11-01T10:00', previous_time_scope='acquisition')
        cases = [
            ('not a date', used, {'acquisition_anchor_at': 'mañana'}, 'Introduce una fecha y hora local.'),
            ('summer-time gap', used, {'acquisition_anchor_at': '2026-03-29T02:30', 'time_zone': 'Europe/Madrid'},
             'Esa hora local no existe (cambio de hora): elige otra.'),
            ('repeated hour, two readings', both, {'acquisition_anchor_at': '2026-10-25T02:30', 'time_zone': 'Europe/Madrid'},
             'Esa hora local se repite (cambio de hora): elige otra.'),
        ]
        for case, data, changes, message in cases:
            with self.subTest(case=case):
                page = self.rejected(self.url('item-used-create'), dict(data, **changes))
                self.assertEqual(errors_under(page, 'acquisition_anchor_at'), [message])
                self.assertEqual(every_error(page), [message])
        confirm = 'Confirma el inicio de adquisición para este ámbito.'
        for case, data in (('one reading', used), ('two readings', both)):
            with self.subTest(case=f'start left empty, {case}'):
                page = self.rejected(self.url('item-used-create'), dict(data, acquisition_anchor_at=''))
                self.assertEqual(errors_under(page, 'previous_distance_scope'), [confirm])
                self.assertEqual(every_error(page), [confirm] * (2 if data is both else 1))
        self.assertFalse(Item.objects.filter(name='Usado').exists())

    def test_mount_errors_are_spanish(self):
        inside = 'El cambio tiene que caer dentro del montaje actual: después de su inicio y, si tiene final, antes de él.'
        for case in (self.replacement_before_the_start, self.transfer_before_the_start):
            with self.subTest(case=case.__name__):
                Installation.objects.all().delete()
                page = case()
                self.assertEqual(errors_under(page, 'at'), [inside])  # next to «Instante del cambio», not above the form
                self.assertEqual(page_text(wrapper_of(page, 'at')).split(' ')[:3], ['Instante', 'del', 'cambio'])
                self.assertEqual(every_error(page), [inside])
                self.assertEqual(Installation.objects.count(), 1)
                self.assertIsNone(Installation.objects.get().ended_at)
        Installation.objects.all().delete()
        page = self.position_that_is_not_a_key()
        self.assertEqual(errors_under(page, 'slot'), ['Usa minúsculas, números y guion bajo, por ejemplo rear_wheel.'])
        self.assertFalse(Installation.objects.exists())
        page = self.closing_a_closed_period()
        self.assertEqual(errors_under(page, 'at'), ['Ese montaje ya está cerrado: corrígelo con «Editar período».'])
        self.assertEqual(Installation.objects.get().ended_at, datetime(2026, 1, 20, 10, tzinfo=UTC))

    def test_dates_and_null_characters_say_so_in_spanish(self):
        from django.test import override_settings
        page = self.rejected(self.url('item-create'), {'name': 'Fechado', 'category': str(self.category.pk), 'time_zone': 'UTC',
                                                       'acquired_on': 'mañana'})
        self.assertEqual(errors_under(page, 'acquired_on'), ['Introduce una fecha válida.'])
        with override_settings(GARAGE_STRAVA_USER=self.user.username):
            page = self.rejected(self.url('strava-import'), {'after': 'ayer'})
        self.assertEqual(errors_under(page, 'after'), ['Introduce una fecha válida.'])
        page = self.rejected(self.url('category-create'), {'name': 'Nula', 'notes': 'con\x00nulo'})
        self.assertEqual(errors_under(page, 'notes'), ['No se admiten caracteres nulos.'])
        self.assertFalse(Item.objects.filter(name='Fechado').exists())
        self.assertFalse(Category.objects.filter(name='Nula').exists())

    def test_acquisition_anchor_errors_are_spanish(self):
        self.assertEqual(errors_under(self.anchor_after_a_reading(), 'acquisition_anchor_at'),
                         ['El inicio del uso desde adquisición no puede ser posterior a una lectura «Desde mi adquisición» ya registrada.'])
        self.assertEqual(errors_under(self.anchor_removed_under_readings(), 'acquisition_anchor_at'),
                         ['Hay lecturas «Desde mi adquisición»: corrígelas antes de quitar este inicio.'])
        self.item.refresh_from_db()
        self.assertEqual(self.item.acquisition_anchor_at, datetime(2026, 1, 1, 10, tzinfo=UTC))

    def test_each_error_is_shown_once(self):
        """One the service raises while saving (the form and the view each added it) and one the model invents for a name
        the form had already rejected."""
        for case in (self.anchor_after_a_reading, self.anchor_removed_under_readings):
            with self.subTest(case=case.__name__):
                errors = every_error(case())
                self.assertEqual(len(errors), 1, errors)
        errors = every_error(self.rejected(self.url('category-create'), {'name': 'sillines'}))
        self.assertEqual(errors, ['Ya tienes una categoría con ese nombre.'])
        self.assertNotIn('Escribe un nombre.', errors)

    def test_translating_keeps_the_error_codes(self):
        """Only the words change: whoever reads the form's errors by code still finds them."""
        create_installation(self.user, item=self.item, bike=self.a, started_at=datetime(2026, 1, 1, 10, tzinfo=UTC))
        cases = [
            (self.url('installation-create', self.item.pk), {'time_zone': 'UTC', 'started_at': '2026-01-02T10:00', 'bike': str(self.b.pk)},
             '__all__', 'installation_overlap'),
            (self.url('category-create'), {'name': 'sillines'}, 'name', 'category_name_conflict'),
            (self.url('category-create'), {'name': 'N', 'notes': '\x00'}, 'notes', 'null_characters_not_allowed'),
            (self.url('item-create'), {'name': 'D', 'category': str(self.category.pk), 'time_zone': 'UTC', 'purchase_amount': '1.234',
                                       'purchase_currency': 'EUR'}, 'purchase_amount', 'max_decimal_places'),
        ]
        for url, data, field, code in cases:
            with self.subTest(code=code):
                form = self.client.post(url, data).context['form']
                self.assertIn(code, [error.code for error in form.errors.as_data()[field]])

    def test_no_web_form_page_shows_a_known_english_message(self):
        from .test_html import find_all, visible_text
        from django.test import override_settings
        event = self.event()
        cases = [
            ('overlap', self.overlapping_mount), ('cycle', self.cyclic_mount), ('position', self.occupied_position),
            ('position key', self.position_that_is_not_a_key), ('replace', self.replacement_before_the_start),
            ('transfer', self.transfer_before_the_start), ('close', self.closing_a_closed_period),
            ('empty category', lambda: self.rejected(self.url('category-create'), {'name': ''})),
            ('repeated category', lambda: self.rejected(self.url('category-create'), {'name': 'SILLINES'})),
            ('null character', lambda: self.rejected(self.url('category-create'), {'name': 'N', 'notes': '\x00'})),
            ('price', lambda: self.rejected(self.url('bike-create'), {'name': 'P', 'time_zone': 'UTC', 'purchase_amount': '4.5'})),
            ('decimals', lambda: self.rejected(self.url('item-create'), {'name': 'D', 'category': str(self.category.pk), 'time_zone': 'UTC',
                                                                          'purchase_amount': '1.234', 'purchase_currency': 'EUR'})),
            ('date', lambda: self.rejected(self.url('item-create'), {'name': 'F', 'category': str(self.category.pk), 'time_zone': 'UTC',
                                                                      'acquired_on': '31/02/2026'})),
            ('empty item', lambda: self.rejected(self.url('item-create'), {'time_zone': 'UTC'})),
            ('previous', lambda: self.rejected(self.url('item-used-create'), {'name': 'U', 'category': str(self.category.pk),
                                                                               'time_zone': 'UTC', 'previous_time': 'x'})),
            ('reading source', lambda: self.reading(source='')),
            ('reading scope', lambda: self.reading(scope='service')),
            ('reading event', lambda: self.reading(service_event=str(event.pk))),
            ('reading order', lambda: self.reading(scope='service', service_event=str(event.pk), cut_at='2026-01-15T10:00')),
            ('reading rides', lambda: self.reading(metric='ride_count', value='1.5')),
            ('reading decimals', lambda: self.reading(value='1.2345')),
            ('reading range', lambda: self.reading(value='123456789012345678')),
            ('reading number', lambda: self.reading(value='diez')),
            ('reading acquisition', lambda: self.reading(scope='acquisition')),
            ('reading repeated', lambda: self.repeated_reading()),
            ('anchor after', self.anchor_after_a_reading), ('anchor removed', self.anchor_removed_under_readings),
        ]
        for case, run in cases:
            with self.subTest(case=case):
                Installation.objects.all().delete()
                UsageBaseline.objects.all().delete()
                page = run()
                self.assertTrue(every_error(page), 'a rejected POST shows why')
                self.assert_spanish(page)
                labels = [visible_text(label) for label in find_all(page, 'label')]
                self.assertEqual([label for label in labels if label in ENGLISH_LABELS], [])
        with override_settings(GARAGE_STRAVA_USER=self.user.username):
            self.assert_spanish(self.rejected(self.url('strava-import'), {'after': 'ayer'}))

    # F09: titles, empty options and order

    def test_create_and_edit_titles_are_singular(self):
        from .test_html import find_all, visible_text
        pages = [('bike-create', (), 'Crear bici'), ('item-create', (), 'Crear material'), ('item-used-create', (), 'Crear material'),
                 ('category-create', (), 'Crear categoría'), ('bike-edit', (self.a.pk,), 'Editar bici'),
                 ('item-edit', (self.item.pk,), 'Editar material'), ('category-edit', (self.category.pk,), 'Editar categoría')]
        for name, args, title in pages:
            with self.subTest(page=name):
                page = page_of(self.client.get(self.url(name, *args)))
                self.assertEqual([visible_text(h1) for h1 in find_all(page, 'h1')], [title])
                self.assertEqual([visible_text(found) for found in find_all(page, 'title')], [f'{title} · Garage'])

    def test_the_way_back_still_names_the_list(self):
        """Only the title is singular: «Crear bici» goes back to «Bicis»."""
        from .test_html import find_all
        for name, back in (('bike-create', 'Bicis'), ('item-create', 'Material'), ('category-create', 'Categorías')):
            with self.subTest(page=name):
                page = page_of(self.client.get(self.url(name)))
                self.assertEqual([link.attrs['aria-label'] for link in find_all(page, 'a', cls='back')], [f'Volver a {back}'])

    def test_category_comes_right_after_the_name(self):
        from .test_html import find_all
        for name in ('item-create', 'item-used-create'):
            with self.subTest(page=name):
                form = find_all(page_of(self.client.get(self.url(name))), 'form', method='post')[0]
                fields = [next(control.attrs['name'] for tag in CONTROLS for control in find_all(wrapper, tag))
                          for wrapper in find_all(form, 'div', cls='field')]
                self.assertEqual(fields[:3], ['name', 'category', 'brand'])
