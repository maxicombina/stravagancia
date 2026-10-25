"""Private profiles and ride exceptions: explicit temporal choices and actor scope."""
from datetime import datetime, timezone
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from .models import Bike, Category, Item, UsageOverride, UsageProfile
from .services.ownership import create_inventory, retire_inventory, reactivate_inventory
from .services.rides import create_manual_ride, import_fit_session, withdraw_source
from .services.usage_profiles import create_profile_history, resolve_ride_usage, set_usage_override


def instant(day):
    return datetime(2026, 1, day, 10, tzinfo=timezone.utc)


class UsageViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user('usage-web')
        cls.other = get_user_model().objects.create_user('usage-private')
        cls.admin = get_user_model().objects.create_superuser('usage-admin', 'usage@example.test', 'test-only')
        category = create_inventory(cls.owner, Category, name='Wearable')
        foreign_category = create_inventory(cls.other, Category, name='PRIVATE category')
        cls.helmet = create_inventory(cls.owner, Item, name='Shared helmet', category=category)
        cls.shoes = create_inventory(cls.owner, Item, name='Shoes', category=category)
        cls.foreign_item = create_inventory(cls.other, Item, name='PRIVATE item', category=foreign_category)
        cls.bike = create_inventory(cls.owner, Bike, name='Road')
        cls.foreign_bike = create_inventory(cls.other, Bike, name='PRIVATE bike')
        cls.ride = create_manual_ride(cls.owner, started_at=instant(5), name='Own ride', sport_type='cycling', bike=cls.bike.pk)
        cls.foreign_ride = create_manual_ride(cls.other, started_at=instant(5), name='PRIVATE ride')
        cls.profile = create_profile_history(cls.owner, items=[cls.helmet], name='Shared gear', started_at=instant(1), sport_type='cycling')
        cls.foreign_profile = create_profile_history(cls.other, items=[cls.foreign_item], name='PRIVATE profile', started_at=instant(1))

    def setUp(self):
        self.client.force_login(self.owner)

    def url(self, name, *args):
        return reverse('garage:usage-' + name, args=args)

    def data(self, **changes):
        data = {'name': 'New profile', 'items': [str(self.shoes.pk)], 'sport_type': 'cycling', 'timing': 'now', 'time_zone': 'UTC'}
        data.update(changes)
        return data

    def test_authentication_and_scoped_lists_even_superuser(self):
        self.client.logout()
        for name in ('profile-list', 'profile-create', 'ride-list'):
            self.assertEqual(self.client.get(self.url(name)).status_code, 302)
        for actor in (self.owner, self.admin):
            self.client.force_login(actor)
            self.assertNotContains(self.client.get(self.url('profile-list')), 'PRIVATE profile')
            self.assertNotContains(self.client.get(self.url('ride-list')), 'PRIVATE ride')
            self.assertEqual(self.client.get(self.url('profile-detail', self.foreign_profile.pk)).status_code, 404)
            self.assertEqual(self.client.post(self.url('ride-detail', self.foreign_ride.pk), {}).status_code, 404)

    def test_foreign_profile_get_post_paths_and_choices(self):
        for path in ('profile-revise', 'profile-history'):
            self.assertEqual(self.client.get(self.url(path, self.foreign_profile.pk)).status_code, 404)
            self.assertEqual(self.client.post(self.url(path, self.foreign_profile.pk), self.data()).status_code, 404)
        response = self.client.get(self.url('profile-create'))
        self.assertNotContains(response, 'PRIVATE item')
        self.assertNotContains(response, 'PRIVATE bike')
        for changes in ({'items': [str(self.foreign_item.pk)]}, {'bike': str(self.foreign_bike.pk)}):
            response = self.client.post(self.url('profile-create'), self.data(**changes))
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context['form'].errors)

    def test_now_captured_on_post_and_new_version_keeps_old_history(self):
        response = self.client.get(self.url('profile-revise', self.profile.pk))
        self.assertNotIn('at', response.context['form'].initial)
        with patch('garage.services.usage_profiles.timezone.now', return_value=instant(10)):
            response = self.client.post(self.url('profile-revise', self.profile.pk), self.data())
        self.assertEqual(response.status_code, 302)
        self.profile.refresh_from_db()
        revised = UsageProfile.objects.get(owner=self.owner, name='New profile')
        self.assertEqual(self.profile.ended_at, instant(10))
        self.assertEqual(revised.started_at, instant(10))
        self.assertEqual(revised.series_id, self.profile.series_id)
        self.assertEqual(resolve_ride_usage(self.owner, self.ride.pk).item_ids, {self.helmet.pk})
        later = create_manual_ride(self.owner, started_at=instant(11), sport_type='cycling', bike=self.bike.pk)
        self.assertEqual(resolve_ride_usage(self.owner, later.pk).item_ids, {self.shoes.pk})
        self.assertContains(self.client.get(self.url('profile-detail', revised.pk)), 'Historial de versiones')

    def test_future_date_required_and_past_rejected_without_history(self):
        with patch('garage.services.usage_profiles.timezone.now', return_value=instant(10)):
            response = self.client.post(self.url('profile-create'), self.data(timing='future'))
            self.assertIn('at', response.context['form'].errors)
            response = self.client.post(self.url('profile-create'), self.data(timing='future', at='2026-01-02T10:00:00'))
            self.assertEqual(response.status_code, 200)
            self.assertIn('at', response.context['form'].errors)
            response = self.client.post(self.url('profile-create'), self.data(timing='future', at='2026-01-12T11:00:00.123456', time_zone='Europe/Madrid'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(UsageProfile.objects.get(name='New profile').started_at, instant(12).replace(microsecond=123456))

    def test_history_create_requires_confirmation_and_explicit_date(self):
        for changes in ({'at': '2026-01-02T10:00:00'}, {'confirm_history': 'on'}):
            response = self.client.post(self.url('profile-create'), self.data(timing='history', **changes))
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context['form'].errors)
        response = self.client.post(self.url('profile-create'), self.data(timing='history', at='2026-01-02T10:00:00', confirm_history='on'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(UsageProfile.objects.get(name='New profile').started_at, instant(2))

    def test_history_correction_requires_choice_and_keeps_overrides(self):
        override = set_usage_override(self.owner, ride=self.ride, item=self.helmet, action='exclude')
        response = self.client.get(self.url('profile-history', self.profile.pk))
        self.assertNotIn('at', response.context['form'].initial)
        for changes in ({'timing': 'now'}, {'timing': 'history', 'at': '2026-01-01T10:00:00'}):
            response = self.client.post(self.url('profile-history', self.profile.pk), self.data(**changes))
            self.assertEqual(response.status_code, 200)
        response = self.client.post(self.url('profile-history', self.profile.pk), self.data(timing='history', at='2026-01-01T10:00:00', confirm_history='on'))
        self.assertEqual(response.status_code, 302)
        self.profile.refresh_from_db()
        self.assertEqual(list(self.profile.items.all()), [self.shoes])
        self.assertTrue(UsageOverride.objects.filter(pk=override.pk).exists())

    def test_normal_now_rejects_supplied_date_and_dst_errors(self):
        response = self.client.post(self.url('profile-create'), self.data(at='2026-01-01T10:00:00'))
        self.assertIn('at', response.context['form'].errors)
        response = self.client.post(self.url('profile-create'), self.data(timing='future', at='2026-10-25T02:30:00', time_zone='Europe/Madrid'))
        self.assertIn('at', response.context['form'].errors)

    def test_override_include_exclude_upsert_delete_post_only(self):
        url = self.url('ride-detail', self.ride.pk)
        response = self.client.post(url, {'item': str(self.shoes.pk), 'action': 'include', 'ride': str(self.foreign_ride.pk)})
        self.assertEqual(response.status_code, 302)
        override = UsageOverride.objects.get()
        self.assertEqual(override.ride_id, self.ride.pk)
        self.assertEqual(resolve_ride_usage(self.owner, self.ride.pk).item_ids, {self.helmet.pk, self.shoes.pk})
        self.assertEqual(self.client.post(url, {'item': str(self.shoes.pk), 'action': 'exclude'}).status_code, 302)
        self.assertEqual(UsageOverride.objects.get().pk, override.pk)
        self.assertEqual(self.client.get(self.url('override-delete', override.pk)).status_code, 405)
        self.assertEqual(self.client.post(self.url('override-delete', override.pk)).status_code, 302)
        self.assertFalse(UsageOverride.objects.exists())

    def test_override_foreign_choices_and_foreign_deletion_denied(self):
        response = self.client.post(self.url('ride-detail', self.ride.pk), {'item': str(self.foreign_item.pk), 'action': 'include'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('item', response.context['form'].errors)
        override = set_usage_override(self.other, ride=self.foreign_ride, item=self.foreign_item, action='include')
        self.assertEqual(self.client.post(self.url('override-delete', override.pk)).status_code, 404)
        self.assertTrue(UsageOverride.objects.filter(pk=override.pk).exists())

    def test_unknown_ride_shows_pending_and_no_resolved_material(self):
        ride, source = import_fit_session(self.owner, file_hash='c' * 64, session_index=0, parser_version='synthetic', observations={'started_at': instant(5), 'sport_type': 'cycling'})
        withdraw_source(self.owner, source.pk)
        response = self.client.get(self.url('ride-detail', ride.pk))
        self.assertContains(response, 'Pendiente: sin inicio confirmado; no genera contador.')
        self.assertEqual(list(response.context['items']), [])
        self.assertContains(self.client.get(self.url('ride-list')), 'Inicio desconocido')

    def test_retirement_gap_preserved_on_reactivation_and_resolution(self):
        retire_inventory(self.owner, Item, self.helmet.pk, at=instant(4))
        reactivate_inventory(self.owner, Item, self.helmet.pk, at=instant(8))
        self.assertNotIn(self.helmet.pk, resolve_ride_usage(self.owner, self.ride.pk).item_ids)
        response = self.client.get(self.url('ride-detail', self.ride.pk))
        self.assertEqual(list(response.context['items']), [])
        after = create_manual_ride(self.owner, started_at=instant(9), sport_type='cycling')
        self.assertContains(self.client.get(self.url('ride-detail', after.pk)), 'Shared helmet')

    def test_reactivate_error_is_controlled_prg_message(self):
        with patch('garage.views.reactivate_inventory', side_effect=ValidationError({'retired_at': 'Explicit correction required'})):
            response = self.client.post(reverse('garage:item-reactivate', args=[self.helmet.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertContains(self.client.get(response.url), 'Explicit correction required')

    def test_escape_profile_notes_and_paginated_own_rides(self):
        text = '<script>alert(1)</script>'
        profile = create_profile_history(self.owner, items=[], name=text, notes=text, started_at=instant(1))
        response = self.client.get(self.url('profile-detail', profile.pk))
        self.assertNotContains(response, text)
        self.assertContains(response, '&lt;script&gt;')
        for number in range(21):
            create_manual_ride(self.owner, started_at=instant(5), name=f'Pagination {number}')
        response = self.client.get(self.url('ride-list') + '?q=Pagination&page=2')
        self.assertEqual(len(response.context['rows']), 1)
        self.assertNotContains(response, 'PRIVATE ride')
        self.assertContains(response, 'Página 2 de 2')

    def test_csrf_and_get_do_not_write_profiles_or_overrides(self):
        count = UsageProfile.objects.count()
        self.client.get(self.url('profile-revise', self.profile.pk))
        self.client.get(self.url('profile-history', self.profile.pk))
        self.client.get(self.url('ride-detail', self.ride.pk))
        self.assertEqual(UsageProfile.objects.count(), count)
        self.assertFalse(UsageOverride.objects.exists())
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        self.assertEqual(client.post(self.url('profile-create'), self.data()).status_code, 403)
        self.assertEqual(client.post(self.url('ride-detail', self.ride.pk), {'item': str(self.helmet.pk), 'action': 'exclude'}).status_code, 403)
        client.get(self.url('profile-create'))
        override = set_usage_override(self.owner, ride=self.ride, item=self.helmet, action='exclude')
        self.assertEqual(client.post(self.url('override-delete', override.pk)).status_code, 403)
        self.assertTrue(UsageOverride.objects.filter(pk=override.pk).exists())
        data = self.data(csrfmiddlewaretoken=client.cookies['csrftoken'].value)
        self.assertEqual(client.post(self.url('profile-create'), data).status_code, 302)

    def test_create_profile_client_owner_and_series_uuid_are_ignored(self):
        response = self.client.post(self.url('profile-create'), self.data(owner=str(self.other.pk), series_id=str(self.foreign_profile.series_id), id=str(self.foreign_profile.pk)))
        self.assertEqual(response.status_code, 302)
        profile = UsageProfile.objects.get(owner=self.owner, name='New profile')
        self.assertNotEqual(profile.pk, self.foreign_profile.pk)
        self.assertNotEqual(profile.series_id, self.foreign_profile.series_id)
