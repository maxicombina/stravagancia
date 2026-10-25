"""Actor-bound forms for versioned defaults and explicit ride exceptions."""
import re
from zoneinfo import ZoneInfo

from django import forms
from django.core.exceptions import ValidationError

from .forms import LocalDateTimeField
from .models import Bike, Item, Ride, UsageProfile
from .services.ownership import get_inventory, require_actor, scoped_inventory
from .services import usage_profiles
from .web_forms import LOCAL_WIDGET, ZONE_HELP, clean_zone, convert_local_fields


class ProfileWebForm(forms.Form):
    name = forms.CharField(max_length=150, label='Nombre del perfil')
    bike = forms.ModelChoiceField(queryset=Bike.objects.none(), required=False, label='Bici',
                                 empty_label='Todas mis bicis / sin bici asignada')
    sport_type = forms.CharField(max_length=80, required=False, label='Modalidad',
        help_text='cycling para ciclismo; vacío para cualquier modalidad. Clave en minúsculas, números y guiones bajos.')
    items = forms.ModelMultipleChoiceField(queryset=Item.objects.none(), required=False, label='Material habitual',
        widget=forms.CheckboxSelectMultiple, help_text='Selecciona tus objetos; sus conjuntos montados se propagan sin duplicarlos.')
    notes = forms.CharField(required=False, widget=forms.Textarea, label='Notas')
    timing = forms.ChoiceField(choices=[('now', 'Desde ahora (hora del servidor al guardar)'),
        ('future', 'Desde una fecha futura explícita'), ('history', 'Aplicar explícitamente al histórico')],
        initial='now', label='Vigencia del cambio')
    time_zone = forms.CharField(initial='UTC', label='Zona horaria IANA', help_text=ZONE_HELP)
    at = LocalDateTimeField(required=False, widget=LOCAL_WIDGET, label='Inicio / instante del cambio',
        help_text='Déjalo vacío para «Desde ahora». Las otras opciones necesitan una fecha explícita.')
    ended_at = LocalDateTimeField(required=False, widget=LOCAL_WIDGET, label='Final de vigencia (opcional)')
    confirm_history = forms.BooleanField(required=False, label='Confirmo que esta operación puede cambiar el material resuelto de salidas pasadas; sus excepciones manuales se conservan.')

    def __init__(self, *args, user, profile=None, correction=False, **kwargs):
        self.actor, self.correction = require_actor(user), correction
        profile = get_inventory(self.actor, UsageProfile, profile.pk) if profile is not None else None
        self.profile = profile
        super().__init__(*args, **kwargs)
        self.fields['bike'].queryset = scoped_inventory(self.actor, Bike)
        self.fields['items'].queryset = scoped_inventory(self.actor, Item)
        if profile is not None:
            for field in ('name', 'bike', 'sport_type', 'notes'):
                self.initial[field] = getattr(profile, field)
            self.initial['items'] = list(profile.items.filter(owner=self.actor).values_list('pk', flat=True))
            if not correction:
                self.fields.pop('ended_at')  # Revisions inherit the existing end.
        if correction:
            self.fields['timing'].choices = [('history', 'Corregir explícitamente esta versión histórica')]
            self.fields['timing'].initial = 'history'
            # No prefilled start: historical effects require an explicit date.
            self.fields['at'].help_text = 'Introduce explícitamente el inicio que tendrá esta versión histórica.'
            if profile and profile.ended_at:
                self.initial['ended_at'] = profile.ended_at.astimezone(ZoneInfo('UTC')).replace(tzinfo=None)

    def clean_time_zone(self):
        return clean_zone(self.cleaned_data['time_zone'])

    def clean_sport_type(self):
        value = self.cleaned_data['sport_type'].strip().lower()
        if re.fullmatch(r'[a-z0-9_]*', value) is None:
            raise ValidationError('Usa una clave de modalidad válida.', code='invalid_sport_type')
        return value

    def clean(self):
        cleaned = super().clean()
        convert_local_fields(self, cleaned, ('at', 'ended_at'))
        timing = cleaned.get('timing')
        if timing in ('future', 'history') and cleaned.get('at') is None and 'at' not in self.errors:
            self.add_error('at', 'Introduce explícitamente el instante de vigencia.')
        if timing == 'now' and cleaned.get('at') is not None:
            self.add_error('at', 'Deja la fecha vacía para usar la hora del servidor o elige otra opción de vigencia.')
        if timing == 'history' and not cleaned.get('confirm_history'):
            self.add_error('confirm_history', 'Confirma explícitamente el efecto sobre el histórico.')
        if cleaned.get('at') and cleaned.get('ended_at') and cleaned['ended_at'] <= cleaned['at']:
            self.add_error('ended_at', 'El final debe ser posterior al inicio.')
        return cleaned

    def save(self):
        data = self.cleaned_data
        values = {field: data[field] for field in ('name', 'bike', 'sport_type', 'notes')}
        items = list(data['items'])
        if self.correction:
            return usage_profiles.update_profile_history(self.actor, self.profile.pk, items=items,
                started_at=data['at'], ended_at=data.get('ended_at'), **values)
        if self.profile is not None:
            if data['timing'] == 'history':
                return usage_profiles.revise_profile_history(self.actor, self.profile.pk, at=data['at'], items=items, **values)
            return usage_profiles.revise_profile(self.actor, self.profile.pk,
                at=None if data['timing'] == 'now' else data['at'], items=items, **values)
        values['ended_at'] = data.get('ended_at')
        if data['timing'] == 'history':
            return usage_profiles.create_profile_history(self.actor, started_at=data['at'], items=items, **values)
        return usage_profiles.create_profile(self.actor, at=None if data['timing'] == 'now' else data['at'], items=items, **values)


class OverrideWebForm(forms.Form):
    item = forms.ModelChoiceField(queryset=Item.objects.none(), label='Objeto')
    action = forms.ChoiceField(choices=[('include', 'Incluir este objeto y su conjunto'),
                                      ('exclude', 'Excluir este objeto y su conjunto')], label='Excepción')

    def __init__(self, *args, user, ride, **kwargs):
        self.actor = require_actor(user)
        self.ride = get_inventory(self.actor, Ride, ride.pk)
        super().__init__(*args, **kwargs)
        self.fields['item'].queryset = scoped_inventory(self.actor, Item)

    def save(self):
        return usage_profiles.set_usage_override(self.actor, ride=self.ride,
            item=self.cleaned_data['item'], action=self.cleaned_data['action'])
