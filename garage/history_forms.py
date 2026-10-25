"""Private upload, coverage and explicit manual history forms."""
import re
from zoneinfo import ZoneInfo

from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .forms import ExactUsageDecimalField, LocalDateTimeField
from .models import Bike, Ride
from .ride_values import RIDE_FIELDS, RIDE_METRICS
from .services.ownership import _lock_owner, get_inventory, require_actor, scoped_inventory
from .services.rides import clear_manual_corrections, correct_ride, create_manual_ride
from .web_forms import LOCAL_WIDGET, ZONE_HELP, clean_zone, convert_local_fields

FIELD_LABELS = {'started_at': 'Inicio local', 'name': 'Nombre', 'sport_type': 'Modalidad',
    'distance_m': 'Distancia (metros)', 'moving_time_s': 'Movimiento (segundos)',
    'timer_time_s': 'Temporizador (segundos)', 'elapsed_time_s': 'Transcurrido (segundos)',
    'elevation_gain_m': 'Desnivel positivo (metros)', 'average_power_w': 'Potencia media (W)',
    'max_power_w': 'Potencia máxima (W)', 'weighted_power_w': 'Potencia normalizada (W)', 'energy_kj': 'Energía (kJ)',
    'bike': 'Bici', 'notes': 'Notas'}
# Every ride field is editable here, elevation and power included (garage-030 phase 3).
FORM_FIELDS = tuple(name for name in RIDE_FIELDS if name in FIELD_LABELS)


class PeriodForm(forms.Form):
    requested_from = LocalDateTimeField(required=False, widget=LOCAL_WIDGET, label='Desde (incluido)')
    requested_to = LocalDateTimeField(required=False, widget=LOCAL_WIDGET, label='Hasta (excluido)')
    time_zone = forms.CharField(initial='UTC', label='Zona IANA', help_text=ZONE_HELP)

    def clean_time_zone(self):
        return clean_zone(self.cleaned_data['time_zone'])

    def clean(self):
        cleaned = super().clean()
        convert_local_fields(self, cleaned, ('requested_from', 'requested_to'))
        if cleaned.get('requested_from') and cleaned.get('requested_to') and cleaned['requested_to'] <= cleaned['requested_from']:
            self.add_error('requested_to', 'El final debe ser posterior al inicio.')
        return cleaned


class HistoryFilterForm(PeriodForm):
    pending = forms.BooleanField(required=False, label='Solo pendientes o campos desconocidos')


class FitPreviewForm(PeriodForm):
    file = forms.FileField(label='Archivo FIT original propio')
    session_indices = forms.CharField(required=False, max_length=399, label='Índices de sesiones a importar',
        help_text='Una sesión: puedes dejar vacío. Varias: previsualiza primero y reenvía el FIT con índices separados por comas, por ejemplo 0,2.')

    def clean_session_indices(self):
        value = self.cleaned_data['session_indices'].strip()
        if not value:
            return None
        parts = value.split(',')
        if len(parts) > 100 or any(re.fullmatch(r'[0-9]+', part.strip()) is None for part in parts):
            raise ValidationError('Introduce índices enteros separados por comas.')
        indices = [int(part.strip()) for part in parts]
        if len(set(indices)) != len(indices):
            raise ValidationError('No repitas índices.')
        return indices


class FitExecuteForm(forms.Form):
    file = forms.FileField(label='Reenvía el mismo FIT (no lo conservamos)')
    preview_token = forms.CharField(max_length=5000, widget=forms.HiddenInput)


class FitResumeForm(forms.Form):
    file = forms.FileField(label='Reenvía el FIT original para continuar')


class BikeBatchForm(forms.Form):
    rides = forms.ModelMultipleChoiceField(queryset=Ride.objects.none(), widget=forms.CheckboxSelectMultiple,
        label='Salidas propias pendientes', help_text='Solo cambia bici desconocida sin corrección manual previa; las demás se conservan.')
    bike = forms.ModelChoiceField(queryset=Bike.objects.none(), required=False, label='Bici de destino',
        empty_label='Desconocida marcada explícitamente (se conserva al reimportar)')
    confirm_history = forms.BooleanField(label='Confirmo la asignación manual de estas salidas históricas.')

    def __init__(self, *args, user, **kwargs):
        self.actor = require_actor(user)
        super().__init__(*args, **kwargs)
        self.fields['rides'].queryset = scoped_inventory(self.actor, Ride).filter(bike__isnull=True).order_by('-started_at', '-pk')
        self.fields['rides'].label_from_instance = lambda ride: f"{ride.started_at.isoformat() if ride.started_at else 'Inicio desconocido'} · {ride.name or 'Sin nombre'}"
        self.fields['bike'].queryset = scoped_inventory(self.actor, Bike)


def ride_fields(form, owner):
    fields = {
        'started_at': LocalDateTimeField(required=False, widget=LOCAL_WIDGET),
        'name': forms.CharField(required=False, max_length=150),
        'sport_type': forms.CharField(required=False, max_length=150, help_text='cycling para ciclismo; vacío significa desconocida.'),
        'bike': forms.ModelChoiceField(queryset=scoped_inventory(owner, Bike), required=False, empty_label='Bici desconocida'),
        'notes': forms.CharField(required=False, widget=forms.Textarea),
    }
    for name in RIDE_METRICS:
        fields[name] = ExactUsageDecimalField(required=False, max_digits=20, decimal_places=3,
            help_text='Vacío: desconocido. Cero: valor conocido. Hasta tres decimales; sin redondeo.')
    for name in FORM_FIELDS:
        fields[name].label = FIELD_LABELS[name]
        form.fields[name] = fields[name]


class ManualRideForm(forms.Form):
    time_zone = forms.CharField(initial='UTC', label='Zona IANA', help_text=ZONE_HELP)

    def __init__(self, *args, user, **kwargs):
        self.actor = require_actor(user)
        super().__init__(*args, **kwargs)
        ride_fields(self, self.actor)
        self.fields['started_at'].required = True

    def clean_time_zone(self):
        return clean_zone(self.cleaned_data['time_zone'])

    def clean(self):
        return convert_local_fields(self, super().clean(), ('started_at',))

    def save(self):
        values = {name: self.cleaned_data[name] for name in FORM_FIELDS}
        values['bike'] = values['bike'].pk if values['bike'] else None
        values['sport_type'] = values['sport_type'].strip().lower()
        return create_manual_ride(self.actor, **values)


class RideCorrectionForm(ManualRideForm):
    confirm_history = forms.BooleanField(required=False, label='Confirmo las correcciones sobre esta salida histórica y su material resuelto.')

    def __init__(self, *args, user, ride, **kwargs):
        super().__init__(*args, user=user, **kwargs)
        self.ride = get_inventory(self.actor, Ride, ride.pk)
        self.fields['started_at'].required = False
        fields = {}
        for name, field in self.fields.items():
            if name in FORM_FIELDS:
                fields[name + '_mode'] = forms.ChoiceField(choices=[('keep', 'Mantener valor y procedencia'),
                    ('set', 'Corregir manualmente (vacío = desconocido explícito)'),
                    ('source', 'Quitar corrección manual y volver a fuentes')], initial='keep', label='Acción para ' + FIELD_LABELS[name].lower())
                value = getattr(self.ride, name)
                if name == 'started_at' and value is not None:
                    value = value.astimezone(ZoneInfo('UTC')).replace(tzinfo=None)
                self.initial[name] = value
            fields[name] = field
        self.fields = fields

    def clean(self):
        cleaned = super().clean()
        changes = [name for name in FORM_FIELDS if cleaned.get(name + '_mode') in ('set', 'source')]
        if changes and not cleaned.get('confirm_history'):
            self.add_error('confirm_history', 'Confirma explícitamente el efecto histórico de las correcciones.')
        if cleaned.get('started_at_mode') == 'set' and cleaned.get('started_at') is None:
            self.add_error('started_at', 'No puedes convertir el inicio en desconocido; confirma una fecha o vuelve a su fuente.')
        return cleaned

    def save(self):
        values, restore = {}, []
        for name in FORM_FIELDS:
            mode = self.cleaned_data[name + '_mode']
            if mode == 'set':
                value = self.cleaned_data[name]
                if name == 'bike':
                    value = value.pk if value else None
                values[name] = value.strip().lower() if name == 'sport_type' else value
            elif mode == 'source':
                restore.append(name)
        with transaction.atomic():
            owner = _lock_owner(self.actor)
            ride = get_inventory(owner, Ride, self.ride.pk)
            if restore:
                ride = clear_manual_corrections(owner, ride.pk, fields=restore)
            if values:
                ride = correct_ride(owner, ride.pk, **values)
            return ride
