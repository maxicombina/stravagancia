"""garage-047 B2b (D25): the rest of the phone forms speak Spanish too, say each error once and save nothing.

B2 covered inventory, mounts and readings (tests_views.SpanishFormTests). These are the other web forms: a ride's
exception, usage profiles, manual rides and their correction, the FIT pages, the bike batch, photos, statistics and
the history filter, and withdrawing a source.
"""
from datetime import datetime, timezone as dt_timezone
from types import SimpleNamespace

from django import forms
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from .history_forms import FORM_FIELDS
from .models import ActivitySource, Bike, Category, ImportRun, Item, Photo, Ride, UsageOverride, UsageProfile
from .services.import_history import preview_fit, start_fit_import
from .services.ownership import create_inventory
from .services.rides import clear_manual_corrections, create_manual_ride
from .services.usage_profiles import create_profile, create_profile_history, revise_profile_history
from .tests_fit_import import activity, session
from .tests_views import ENGLISH, errors_under, every_error, page_of, page_text

UTC = dt_timezone.utc
REQUIRED = 'Este campo es obligatorio.'
CHOICE = 'Elige una opción válida.'
# What these pages said before B2b, as fragments, besides the ones B2 already looks for.
MORE_ENGLISH = ('No file was submitted', 'submitted file is empty', 'Ensure this', 'explicit historical operation',
                'Split strictly', 'cannot overlap', 'only known start', 'supported field value')
PAST = 'Esa fecha ya ha pasado: para fechas pasadas, elige «Aplicar explícitamente al histórico».'
SPLIT = ('La nueva versión tiene que empezar dentro de la vigencia de esta: después de su inicio y, si tiene final, '
         'antes de él.')
OVERLAP = 'Las versiones de un mismo perfil no pueden solaparse.'
NO_START = 'Ninguna fuente aporta el inicio: sin la corrección, quedaría desconocido.'
EMPTY_FILE = 'El archivo está vacío.'
NO_FILE = 'No llegó ningún archivo: vuelve a elegirlo.'
ABOVE = '(above the form)'  # errors that no field shows: the form's own, or a hidden field's


def day(number, month=1):
    return datetime(2026, month, number, 10, tzinfo=UTC)


def upload(raw, name='synthetic.fit'):
    return SimpleUploadedFile(name, raw, content_type='application/octet-stream')


class SpanishRestOfFormsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user('spanish-rest', password='test-only-password')
        cls.other = get_user_model().objects.create_user('spanish-rest-other', password='test-only-password')
        category = create_inventory(cls.user, Category, name='Cascos')
        cls.helmet = create_inventory(cls.user, Item, name='Casco', category=category)
        cls.bike = create_inventory(cls.user, Bike, name='Gravel')
        cls.foreign_bike = create_inventory(cls.other, Bike, name='Ajena')
        cls.ride = create_manual_ride(cls.user, started_at=day(5), name='Salida a mano', sport_type='cycling')
        cls.assigned = create_manual_ride(cls.user, started_at=day(6), name='Con bici', bike=cls.bike.pk)
        cls.profile = create_profile_history(cls.user, items=[cls.helmet], name='Habitual', started_at=day(1),
                                             sport_type='cycling')

    def setUp(self):
        self.client.force_login(self.user)
        self.client.cookies['garage_tz'] = 'UTC'
        self.run = None

    def url(self, name, *args):
        return reverse('garage:' + name, args=args)

    def saved(self):
        """Everything these pages can write: a refused request leaves it as it was."""
        return {
            'rides': list(Ride.objects.order_by('pk').values_list('pk', 'updated_at')),
            'profiles': list(UsageProfile.objects.order_by('pk').values_list('pk', 'started_at', 'ended_at', 'updated_at')),
            'overrides': list(UsageOverride.objects.order_by('pk').values_list('pk', 'action', 'updated_at')),
            'runs': list(ImportRun.objects.order_by('pk').values_list('pk', 'state', 'cursor', 'updated_at')),
            'sources': list(ActivitySource.objects.order_by('pk').values_list('pk', 'withdrawn_at')),
            'photos': Photo.objects.count(),
        }

    def paused_run(self):
        """A FIT job that imported one of its two sessions: one active source, and a page that asks for the file again."""
        if self.run is None:
            raw = activity(session(), session(start=1_100_010_000))
            preview = preview_fit(self.user, raw, session_indices=[0, 1])
            self.run = start_fit_import(self.user, raw, preview.token, budget=1)
        return self.run

    def profile_data(self, **changes):
        data = {'name': 'Habitual', 'items': [str(self.helmet.pk)], 'sport_type': 'cycling', 'timing': 'now', 'time_zone': 'UTC'}
        data.update(changes)
        return data

    def modes(self, **changes):
        data = {name + '_mode': 'keep' for name in FORM_FIELDS}
        data.update(time_zone='UTC', confirm_history='on')
        data.update(changes)
        return data

    def manual(self, **changes):
        data = {'started_at': '2026-02-01T10:00', 'time_zone': 'UTC'}
        data.update(changes)
        return data

    def refused(self, method, url, data, expected):
        """Send it, then: these errors under these fields, each once and no other, only Spanish, and nothing saved."""
        before = self.saved()
        response = getattr(self.client, method)(url, data)
        self.assertIn(response.status_code, (200, 400), response)
        page = page_of(response)
        self.assertEqual({name: errors_under(page, name) for name in expected if name != ABOVE},
                         {name: errors for name, errors in expected.items() if name != ABOVE})
        self.assertEqual(sorted(every_error(page)), sorted(error for errors in expected.values() for error in errors),
                         'each error once, and none that nobody made')
        text = page_text(page)
        self.assertEqual([english for english in ENGLISH + MORE_ENGLISH if english in text], [])
        self.assertEqual(self.saved(), before)
        return response

    # Sent empty

    def empty_cases(self):
        run = self.paused_run()
        source = ActivitySource.objects.get()
        later = revise_profile_history(self.user, self.profile.pk, at=day(10), items=[self.helmet])
        profile = [REQUIRED]
        return [
            ('excepción de una salida', 'post', self.url('usage-ride-detail', self.ride.pk), {},
             {'item': [REQUIRED], 'action': [REQUIRED]}),
            ('perfil nuevo', 'post', self.url('usage-profile-create'), {},
             {'name': profile, 'timing': profile, 'time_zone': profile}),
            ('nueva versión del perfil', 'post', self.url('usage-profile-revise', later.pk), {},
             {'name': profile, 'timing': profile, 'time_zone': profile}),
            ('corrección de una versión', 'post', self.url('usage-profile-history', later.pk), {},
             {'name': profile, 'timing': profile, 'time_zone': profile}),
            ('salida manual', 'post', self.url('history-manual-create'), {},
             {'started_at': [REQUIRED], 'time_zone': [REQUIRED]}),
            ('corrección de una salida', 'post', self.url('history-manual-edit', self.ride.pk), {},
             {'time_zone': [REQUIRED], **{name + '_mode': [REQUIRED] for name in FORM_FIELDS}}),
            ('lote de bicis', 'post', self.url('history-bike-batch'), {},
             {'rides': [REQUIRED], 'confirm_history': [REQUIRED]}),
            ('vista previa del FIT', 'post', self.url('history-preview'), {},
             {'file': [REQUIRED], 'time_zone': [REQUIRED]}),
            ('ejecución del FIT', 'post', self.url('history-execute'), {},
             {'file': [REQUIRED], ABOVE: [REQUIRED]}),  # and the hidden preview token
            ('reanudación del FIT', 'post', self.url('history-run', run.pk), {}, {'file': [REQUIRED]}),
            ('foto', 'post', self.url('bike-photo-create', self.bike.pk), {}, {'photo': [REQUIRED]}),
            ('retirar una fuente', 'post', self.url('history-source-withdraw', source.pk), {}, {'confirm': [REQUIRED]}),
            ('estadísticas con la zona vacía', 'get', self.url('statistics'), {'started_from': '', 'time_zone': ''},
             {'time_zone': [REQUIRED]}),
            ('histórico con la zona vacía', 'get', self.url('history'), {'time_zone': ''}, {'time_zone': [REQUIRED]}),
        ]

    def test_empty_forms_say_so_in_spanish_once_and_save_nothing(self):
        for case, method, url, data, expected in self.empty_cases():
            with self.subTest(case=case):
                self.refused(method, url, data, expected)

    # Sent with values typed wrong

    def mistyped_cases(self):
        run = self.paused_run()
        number, decimals = ['Introduce un número.'], ['El valor exacto admite como máximo 3 decimales.']
        out_of_range = ['Escribe un valor positivo o cero, dentro del máximo admitido.']
        return [
            ('salida manual: texto en la distancia', self.url('history-manual-create'), self.manual(distance_m='mucho'),
             {'distance_m': number}),
            ('salida manual: cuatro decimales', self.url('history-manual-create'), self.manual(distance_m='1.2345'),
             {'distance_m': decimals}),
            ('salida manual: negativo', self.url('history-manual-create'), self.manual(moving_time_s='-1'),
             {'moving_time_s': out_of_range}),
            ('salida manual: dieciocho cifras', self.url('history-manual-create'),
             self.manual(elevation_gain_m='123456789012345678'), {'elevation_gain_m': out_of_range}),
            ('salida manual: carácter nulo', self.url('history-manual-create'), self.manual(name='a\x00b'),
             {'name': ['No se admiten caracteres nulos.']}),
            ('salida manual: nombre largo', self.url('history-manual-create'), self.manual(name='x' * 151),
             {'name': ['Como máximo 150 caracteres.']}),
            ('salida manual: bici ajena', self.url('history-manual-create'), self.manual(bike=str(self.foreign_bike.pk)),
             {'bike': [CHOICE]}),
            ('corrección: texto en la distancia', self.url('history-manual-edit', self.ride.pk),
             self.modes(distance_m_mode='set', distance_m='mucho'), {'distance_m': number}),
            ('corrección: cuatro decimales', self.url('history-manual-edit', self.ride.pk),
             self.modes(distance_m_mode='set', distance_m='1.2345'), {'distance_m': decimals}),
            ('corrección: acción inventada', self.url('history-manual-edit', self.ride.pk),
             self.modes(distance_m_mode='inventada'), {'distance_m_mode': [CHOICE]}),
            ('perfil: bici ajena', self.url('usage-profile-create'), self.profile_data(bike=str(self.foreign_bike.pk)),
             {'bike': [CHOICE]}),
            ('perfil: carácter nulo en las notas', self.url('usage-profile-create'), self.profile_data(notes='\x00'),
             {'notes': ['No se admiten caracteres nulos.']}),
            ('excepción: acción inventada', self.url('usage-ride-detail', self.ride.pk),
             {'item': str(self.helmet.pk), 'action': 'otra'}, {'action': [CHOICE]}),
            ('lote: una salida que ya tiene bici', self.url('history-bike-batch'),
             {'rides': [str(self.assigned.pk)], 'confirm_history': 'on'}, {'rides': [CHOICE]}),
            ('vista previa: archivo vacío', self.url('history-preview'), {'file': upload(b''), 'time_zone': 'UTC'},
             {'file': [EMPTY_FILE]}),
            ('ejecución: archivo vacío', self.url('history-execute'), {'file': upload(b''), 'preview_token': 'x'},
             {'file': [EMPTY_FILE]}),
            ('reanudación: archivo vacío', self.url('history-run', run.pk), {'file': upload(b'')}, {'file': [EMPTY_FILE]}),
            ('foto: archivo vacío', self.url('bike-photo-create', self.bike.pk), {'photo': upload(b'', 'foto.jpg')},
             {'photo': [EMPTY_FILE]}),
        ]

    def test_mistyped_values_say_so_in_spanish_once_and_save_nothing(self):
        for case, url, data, expected in self.mistyped_cases():
            with self.subTest(case=case):
                self.refused('post', url, data, expected)

    # What the services refuse after the form

    def test_dates_the_profile_service_refuses_say_so_in_spanish(self):
        later = revise_profile_history(self.user, self.profile.pk, at=day(10), items=[self.helmet])
        cases = [
            ('una vigencia futura que ya pasó', self.url('usage-profile-create'),
             self.profile_data(name='Otro', timing='future', at='2020-01-01T10:00'), PAST, 'historical_change_required'),
            ('una versión nueva antes de que empiece la actual', self.url('usage-profile-revise', later.pk),
             self.profile_data(timing='history', at='2026-01-05T10:00', confirm_history='on'), SPLIT, 'invalid_interval'),
            ('una corrección que pisa la versión anterior', self.url('usage-profile-history', later.pk),
             self.profile_data(timing='history', at='2026-01-05T10:00', confirm_history='on'), OVERLAP, 'profile_overlap'),
        ]
        for case, url, data, message, code in cases:
            with self.subTest(case=case):
                response = self.refused('post', url, data, {'at': [message]})
                self.assertEqual([error.code for error in response.context['form'].errors.as_data()['at']], [code],
                                 'only the words change')

    def test_a_correction_that_would_lose_the_start_says_so_in_spanish(self):
        """A ride written by hand has no source: going back to the sources would leave it without a start."""
        response = self.refused('post', self.url('history-manual-edit', self.ride.pk), self.modes(started_at_mode='source'),
                                {'started_at': [NO_START]})
        self.assertEqual([error.code for error in response.context['form'].errors.as_data()['started_at']], ['start_required'])

    def test_a_file_that_does_not_arrive_whole_says_so_in_spanish(self):
        """What a browser does not send, but a broken upload can: something that is not a file, or a file without a name."""
        from .photo_forms import PhotoUploadForm
        for case, files in (('no es un archivo', {'photo': 'texto'}), ('sin nombre', {'photo': SimpleNamespace(name='', size=1)})):
            with self.subTest(case=case):
                self.assertEqual(PhotoUploadForm({}, files).errors, {'photo': [NO_FILE]})

    def test_a_file_name_limit_says_so_in_spanish_with_its_number(self):
        """No page sets one today; a file field that does must not borrow the text of a character limit."""
        from .maintenance_forms import SpanishWebMixin

        class Named(SpanishWebMixin, forms.Form):
            file = forms.FileField(max_length=5)

        self.assertEqual(Named({}, {'file': upload(b'x', 'largo.fit')}).errors,
                         {'file': ['El nombre del archivo admite como máximo 5 caracteres.']})

    def test_no_other_web_form_page_shows_a_known_english_message(self):
        """The sweep of B2, over these pages: every case above, refused, in Spanish."""
        cases = ([(case, method, url, data) for case, method, url, data, _ in self.empty_cases()]
                 + [(case, 'post', url, data) for case, url, data, _ in self.mistyped_cases()])
        for case, method, url, data in cases:
            with self.subTest(case=case):
                page = page_of(getattr(self.client, method)(url, data))
                self.assertTrue(every_error(page), 'a refused request shows why')
                text = page_text(page)
                self.assertEqual([english for english in ENGLISH + MORE_ENGLISH if english in text], [])

    # Review of B2b, round 1

    def test_a_correction_with_a_start_typed_wrong_says_only_why(self):
        """A date was typed: «convertir el inicio en desconocido» would be a false second error (B2b-R1-01)."""
        url = self.url('history-manual-edit', self.ride.pk)
        cases = [
            ('una hora que no existe', '2026-03-29T02:30', 'Europe/Madrid', 'Esa hora local no existe (cambio de hora): elige otra.'),
            ('una hora que se repite', '2026-10-25T02:30', 'Europe/Madrid', 'Esa hora local se repite (cambio de hora): elige otra.'),
            ('una hora antes del año 1 en UTC', '0001-01-01T00:30', 'Asia/Tokyo',
             'Esa hora local está fuera del intervalo admitido.'),
            ('una fecha mal escrita', 'mañana', 'UTC', 'Introduce una fecha y hora local.'),
        ]
        for case, typed, zone, message in cases:
            with self.subTest(case=case):
                self.refused('post', url, self.modes(started_at_mode='set', started_at=typed, time_zone=zone),
                             {'started_at': [message]})

    def test_a_correction_that_empties_the_start_still_says_it_cannot(self):
        self.refused('post', self.url('history-manual-edit', self.ride.pk), self.modes(started_at_mode='set', started_at=''),
                     {'started_at': ['No puedes convertir el inicio en desconocido; confirma una fecha o vuelve a su fuente.']})

    def test_a_forged_choice_that_is_not_even_a_key_says_choose_a_valid_option(self):
        """Only a forged POST sends one: the model's key field refuses it, in English and with the value in the text,
        before the choice is looked up (B2b-R1-02). Checkboxes and selects."""
        pending = str(self.ride.pk)
        cases = [
            ('lote: la salida', self.url('history-bike-batch'), {'rides': ['abc'], 'confirm_history': 'on'}, 'rides'),
            ('lote: una salida buena y otra no', self.url('history-bike-batch'),
             {'rides': [pending, 'abc'], 'confirm_history': 'on'}, 'rides'),
            ('lote: la bici', self.url('history-bike-batch'), {'rides': [pending], 'bike': 'abc', 'confirm_history': 'on'}, 'bike'),
            ('perfil: el material', self.url('usage-profile-create'), self.profile_data(name='Otro', items=['abc']), 'items'),
            ('perfil: la bici', self.url('usage-profile-create'), self.profile_data(name='Otro', bike='abc'), 'bike'),
            ('salida manual: la bici', self.url('history-manual-create'), self.manual(bike='abc'), 'bike'),
            ('corrección: la bici', self.url('history-manual-edit', self.ride.pk), self.modes(bike_mode='set', bike='abc'), 'bike'),
            ('excepción: el objeto', self.url('usage-ride-detail', self.ride.pk), {'item': 'abc', 'action': 'include'}, 'item'),
        ]  # Statistics answers 404 to a malformed id before its form runs (StatisticsForm.__init__).
        for case, url, data, field in cases:
            with self.subTest(case=case):
                self.refused('post', url, data, {field: [CHOICE]})

    def test_a_modality_over_its_limit_once_in_lowercase_says_so_under_it(self):
        """It is saved in lowercase, and «İ» lowercases to two characters: 150 typed are 300 saved (B2b-R1-03)."""
        message = 'Se guarda en minúsculas y así pasa de 150 caracteres: acórtala.'
        cases = [
            ('salida manual', self.url('history-manual-create'), self.manual(sport_type='İ' * 150)),
            ('salida manual, por dos', self.url('history-manual-create'), self.manual(sport_type='İ' * 76)),
            ('corrección', self.url('history-manual-edit', self.ride.pk), self.modes(sport_type_mode='set', sport_type='İ' * 150)),
        ]
        for case, url, data in cases:
            with self.subTest(case=case):
                self.refused('post', url, data, {'sport_type': [message]})

    def test_a_modality_that_fits_once_in_lowercase_is_saved_in_lowercase(self):
        cases = [('İ' * 75, 'i̇' * 75), ('A' * 150, 'a' * 150), ('  Gravel ', 'gravel'), ('', '')]
        for typed, saved in cases:
            with self.subTest(typed=typed):
                before = set(Ride.objects.values_list('pk', flat=True))
                response = self.client.post(self.url('history-manual-create'), self.manual(sport_type=typed))
                self.assertEqual(response.status_code, 302)
                self.assertEqual(list(Ride.objects.exclude(pk__in=before).values_list('sport_type', flat=True)), [saved])
        response = self.client.post(self.url('history-manual-edit', self.ride.pk), self.modes(sport_type_mode='set', sport_type=' MTB'))
        self.assertEqual(response.status_code, 302)
        self.ride.refresh_from_db()
        self.assertEqual(self.ride.sport_type, 'mtb')

    # Guards: what already spoke Spanish keeps its words, and the services keep their own

    def test_messages_already_in_spanish_do_not_change(self):
        cases = [
            ('perfil futuro sin fecha', self.url('usage-profile-create'), self.profile_data(timing='future'),
             {'at': ['Introduce explícitamente el instante de vigencia.']}),
            ('perfil histórico sin confirmar', self.url('usage-profile-create'),
             self.profile_data(timing='history', at='2026-01-02T10:00'),
             {'confirm_history': ['Confirma explícitamente el efecto sobre el histórico.']}),
            ('perfil con modalidad mal escrita', self.url('usage-profile-create'), self.profile_data(sport_type='ci clismo'),
             {'sport_type': ['Usa una clave de modalidad válida.']}),
            ('corrección sin confirmar', self.url('history-manual-edit', self.ride.pk),
             self.modes(confirm_history='', distance_m_mode='source'),
             {'confirm_history': ['Confirma explícitamente el efecto histórico de las correcciones.']}),
            ('salida manual en una hora que no existe', self.url('history-manual-create'),
             self.manual(started_at='2026-03-29T02:30', time_zone='Europe/Madrid'),
             {'started_at': ['Esa hora local no existe (cambio de hora): elige otra.']}),
            ('salida manual en una zona que no existe', self.url('history-manual-create'), self.manual(time_zone='Marte/Olimpo'),
             {'time_zone': ['Elige una zona horaria IANA válida.']}),
            ('vista previa con índices mal escritos', self.url('history-preview'),
             {'file': upload(activity()), 'time_zone': 'UTC', 'session_indices': '0,a'},
             {'session_indices': ['Introduce índices enteros separados por comas.']}),
        ]
        for case, url, data, expected in cases:
            with self.subTest(case=case):
                page = page_of(self.client.post(url, data))
                self.assertEqual({name: errors_under(page, name) for name in expected}, expected)
        page = page_of(self.client.get(self.url('statistics'), {'started_from': '2026-02-01T00:00', 'started_to': '2026-01-01T00:00',
                                                               'time_zone': 'UTC'}))
        self.assertEqual(errors_under(page, 'started_to'), ['El final debe seguir al inicio.'])

    def test_the_services_keep_their_own_words(self):
        """Only the phone pages translate: the domain, the admin and other callers see the same messages and codes."""
        from .services.ownership import InventoryWriteError
        with self.assertRaises(InventoryWriteError) as raised:
            create_profile(self.user, items=[], name='Otro', at=day(1))
        self.assertEqual([(error.code, error.message) for error in raised.exception.error_dict['started_at']],
                         [('historical_change_required', 'Use an explicit historical operation for past dates.')])
        with self.assertRaises(InventoryWriteError) as raised:
            clear_manual_corrections(self.user, self.ride.pk, fields=['started_at'])
        self.assertEqual([(error.code, error.message) for error in raised.exception.error_dict['started_at']],
                         [('start_required', 'A correction cannot remove the only known start.')])
