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
