"""Private history inspection, uploads and manual corrections; no external API."""
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from .history_forms import (HistoryFilterForm, FitPreviewForm, FitExecuteForm, FitResumeForm,
                           BikeBatchForm, ManualRideForm, RideCorrectionForm)
from .models import ActivitySource, ImportRun, Ride
from .services.import_history import (preview_fit, start_fit_import, resume_fit_import, cancel_fit_import,
                                     assign_pending_bikes, history_queryset, coverage)
from .services.ownership import get_inventory, scoped_inventory
from .services.rides import withdraw_source
from .local_forms import localize
from .templatetags.garage_ui import datetime_text
from .timezones import user_time_zone
from .views import form_page, show_errors


@login_required
@require_http_methods(['GET'])
def history(request):
    data = {key: value for key, value in request.GET.items() if key in HistoryFilterForm.base_fields}
    data.setdefault('time_zone', user_time_zone(request).key)
    form = localize(HistoryFilterForm(data), user_time_zone(request))  # native pickers; the zone is already the viewer's
    valid = form.is_valid()
    values = form.cleaned_data if valid else {'requested_from': None, 'requested_to': None, 'pending': False}
    rides = history_queryset(request.user, **{name: values.get(name) for name in ('requested_from', 'requested_to', 'pending')})
    if not valid:
        rides = rides.none()
    page = Paginator(rides, 20).get_page(request.GET.get('page'))
    stats = coverage(request.user, requested_from=values.get('requested_from'), requested_to=values.get('requested_to')) if valid else None
    runs = scoped_inventory(request.user, ImportRun).order_by('-created_at', '-pk')[:10]
    return render(request, 'garage/history_index.html', {'title': 'Histórico propio', 'form': form, 'page': page, 'tab': 'rides',
                  'back_url': reverse('garage:usage-ride-list'), 'back_label': 'Salidas',
                  'coverage': stats, 'coverage_fields': [(label, stats['missing_fields'][key]) for key, label in
                      [('distance_m', 'Distancia'), ('moving_time_s', 'Movimiento'), ('timer_time_s', 'Temporizador'), ('elapsed_time_s', 'Transcurrido')]] if stats else [],
                  'runs': runs, 'query': urlencode(data)})


@login_required
@require_http_methods(['GET', 'POST'])
def fit_preview(request):
    form = localize(FitPreviewForm(request.POST if request.method == 'POST' else None, request.FILES or None), user_time_zone(request))
    preview = None
    if request.method == 'POST' and form.is_valid():
        values = form.cleaned_data
        try:
            preview = preview_fit(request.user, values['file'], session_indices=values['session_indices'],
                requested_from=values['requested_from'], requested_to=values['requested_to'])
        except ValidationError as error:
            show_errors(form, error)
    execute_form = FitExecuteForm(initial={'preview_token': preview.token}) if preview and preview.token else None
    return render(request, 'garage/history_preview.html', {'title': 'Previsualizar FIT propio', 'form': form,
                  'preview': preview, 'execute_form': execute_form})


@login_required
@require_POST
def fit_execute(request):
    form = FitExecuteForm(request.POST, request.FILES)
    if form.is_valid():
        try:
            run = start_fit_import(request.user, form.cleaned_data['file'], form.cleaned_data['preview_token'])
        except ValidationError as error:
            show_errors(form, error)
        else:
            return redirect('garage:history-run', pk=run.pk)
    return render(request, 'garage/history_execute.html', {'title': 'Ejecutar importación', 'form': form})


RUN_ERROR_LABELS = {
    'rate_limited': 'Strava pidió esperar (límite de peticiones). Reintenta en 15 minutos; las páginas confirmadas se conservan.',
    'unauthorized': 'Strava rechazó el token de Stravagancia. Renuévalo y continúa.',
    'invalid_metric': 'Alguna actividad traía datos no válidos y se omitió.',
    'unexpected_failure': 'No se pudo hablar con Strava o algo falló. Continúa más tarde; las páginas confirmadas se conservan.',
}


def _strava_run(request, run):
    """A Strava history job resumes without any file (garage-030)."""
    from .services.strava_sync import STEP_BUDGET, resume_strava_import
    if request.method == 'POST':
        try:
            run = resume_strava_import(request.user, run.pk, budget=STEP_BUDGET)
        except ValidationError as error:
            messages.error(request, ' '.join(error.messages))
        return redirect('garage:history-run', pk=run.pk)
    return render(request, 'garage/history_run.html', {'title': 'Trabajo de importación', 'run': run, 'strava': True,
                  'back_url': reverse('garage:strava'), 'back_label': 'Strava',
                  'run_errors': [{'label': RUN_ERROR_LABELS.get(entry['code'], RUN_ERROR_LABELS['unexpected_failure'])} for entry in run.errors]})


@login_required
@require_http_methods(['GET', 'POST'])
def import_run(request, pk):
    run = get_inventory(request.user, ImportRun, pk)
    if run.source_kind == 'strava':
        return _strava_run(request, run)
    form = FitResumeForm(request.POST if request.method == 'POST' else None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        try:
            run = resume_fit_import(request.user, pk, form.cleaned_data['file'])
        except ValidationError as error:
            show_errors(form, error)
        else:
            return redirect('garage:history-run', pk=run.pk)
    return render(request, 'garage/history_run.html', {'title': 'Trabajo de importación', 'run': run, 'form': form, 'run_errors': [
                      {'label': 'No se pudo guardar la sesión. Revisa sus fuentes y vuelve a intentarlo.', 'session_index': entry['session_index']}
                      for entry in run.errors]})


@login_required
@require_POST
def import_cancel(request, pk):
    run = get_inventory(request.user, ImportRun, pk)
    try:
        cancel_fit_import(request.user, pk)
    except ValidationError as error:
        messages.error(request, 'No se pudo cancelar: ' + ' '.join(error.messages))
    else:
        messages.success(request, 'Trabajo cancelado. Se conserva las sesiones ya guardadas.')
    return redirect('garage:history-run', pk=run.pk)


@login_required
@require_http_methods(['GET', 'POST'])
def bike_batch(request):
    form = BikeBatchForm(request.POST if request.method == 'POST' else None, user=request.user)
    zone = user_time_zone(request)
    form.fields['rides'].label_from_instance = lambda ride: f"{datetime_text(ride.started_at, zone) or 'Inicio desconocido'} · {ride.name or 'Sin nombre'}"
    if request.method == 'POST' and form.is_valid():
        try:
            result = assign_pending_bikes(request.user, list(form.cleaned_data['rides'].values_list('pk', flat=True)), form.cleaned_data['bike'])
        except ValidationError as error:
            show_errors(form, error)
        else:
            messages.success(request, f'Asignación manual: {len(result.changed_ids)} salidas; {len(result.skipped_ids)} conservadas por tener bici o corrección propia.')
            return redirect('garage:history')
    return form_page(request, form, 'Asignar bicis por lote', reverse('garage:history'),
        'Solo cambia pendientes sin corrección manual de bici. Marcar desconocido expresa una decisión manual y se conserva al reimportar. Queda registrada procedencia manual por campo e instante.')


@login_required
@require_http_methods(['GET', 'POST'])
def manual_ride(request, pk=None):
    ride = get_inventory(request.user, Ride, pk) if pk else None
    form = (RideCorrectionForm(request.POST if request.method == 'POST' else None, user=request.user, ride=ride)
            if ride else ManualRideForm(request.POST if request.method == 'POST' else None, user=request.user))
    if request.method == 'POST' and form.is_valid():
        try:
            saved = form.save()
        except ValidationError as error:
            show_errors(form, error)
        else:
            messages.success(request, 'Salida propia guardada. Las correcciones manuales prevalecen sobre futuras importaciones.')
            return redirect('garage:usage-ride-detail', pk=saved.pk)
    return form_page(request, form, 'Corregir salida histórica' if ride else 'Añadir salida manual',
                     reverse('garage:usage-ride-detail', args=[ride.pk]) if ride else reverse('garage:history'),
                     'Movimiento, temporizador y transcurrido son independientes. Vacío significa desconocido, cero es conocido. Al editar, elige la acción por campo; mantener conserva también lo marcado explícitamente como desconocido.')


@login_required
@require_http_methods(['GET', 'POST'])
def source_withdraw(request, pk):
    source = get_inventory(request.user, ActivitySource, pk)
    from django import forms
    class ConfirmForm(forms.Form):
        confirm = forms.BooleanField(label='Confirmo retirar esta fuente y recalcular sus campos y material; las correcciones manuales permanecen.')
    form = ConfirmForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        try:
            withdraw_source(request.user, pk)
        except ValidationError as error:
            show_errors(form, error)
        else:
            messages.success(request, 'Fuente retirada. Su reactivación requiere una operación explícita; sincronizar con Strava no la reactiva.')
            return redirect('garage:usage-ride-detail', pk=source.ride_id)
    return form_page(request, form, 'Retirar fuente de Strava' if source.source_kind == 'strava' else 'Retirar fuente FIT',
                     reverse('garage:usage-ride-detail', args=[source.ride_id]),
                     'Puede dejar campos o inicio desconocidos. No se elimina ni reetiqueta la procedencia de datos.')
