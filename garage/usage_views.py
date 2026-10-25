"""Private HTML access to usage defaults, versions and per-ride exceptions."""
from urllib.parse import urlencode
from uuid import UUID

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from .models import ActivitySource, Bike, Item, Ride, UsageOverride, UsageProfile
from .services.ownership import get_inventory, scoped_inventory
from .services.usage_profiles import resolve_ride_usage, delete_usage_override
from .usage_forms import ProfileWebForm, OverrideWebForm
from .views import show_errors, form_page


@login_required
@require_http_methods(['GET'])
def profile_list(request):
    query = scoped_inventory(request.user, UsageProfile).select_related('bike').prefetch_related('items').order_by('-started_at', '-pk')
    page = Paginator(query, 20).get_page(request.GET.get('page'))
    return render(request, 'garage/usage_profiles.html', {'title': 'Perfiles de uso', 'page': page,
                                                         'back_url': reverse('garage:more'), 'back_label': 'Más'})


@login_required
@require_http_methods(['GET'])
def profile_detail(request, pk):
    profile = get_inventory(request.user, UsageProfile, pk)
    versions = scoped_inventory(request.user, UsageProfile).filter(series_id=profile.series_id).prefetch_related('items').order_by('started_at', 'pk')
    return render(request, 'garage/usage_profile.html', {'title': profile.name, 'profile': profile, 'versions': versions,
                                                        'back_url': reverse('garage:usage-profile-list'), 'back_label': 'Perfiles de uso'})


@login_required
@require_http_methods(['GET', 'POST'])
def profile_edit(request, pk=None, correction=False):
    profile = get_inventory(request.user, UsageProfile, pk) if pk else None
    form = ProfileWebForm(request.POST if request.method == 'POST' else None,
                          user=request.user, profile=profile, correction=correction)
    if request.method == 'POST' and form.is_valid():
        try:
            saved = form.save()
        except ValidationError as error:
            # Service fields use started_at, whereas the web form uses at.
            if hasattr(error, 'error_dict') and 'started_at' in error.error_dict:
                error.error_dict['at'] = error.error_dict.pop('started_at')
            show_errors(form, error)
        else:
            messages.success(request, 'Perfil guardado. Las excepciones por salida se conservan.')
            return redirect('garage:usage-profile-detail', pk=saved.pk)
    back = reverse('garage:usage-profile-detail', args=[profile.pk]) if profile else reverse('garage:usage-profile-list')
    title = 'Corregir versión histórica' if correction else ('Nueva versión del perfil' if profile else 'Crear perfil de uso')
    return form_page(request, form, title, back,
        'Los cambios ordinarios crean una vigencia desde ahora o futura. Aplicar o corregir el histórico requiere fecha y confirmación explícitas; puede cambiar el material de salidas pasadas.')


def resolved_context(request, ride):
    resolution = resolve_ride_usage(request.user, ride.pk)
    items = scoped_inventory(request.user, Item).filter(pk__in=resolution.item_ids).order_by('name', 'pk')
    return resolution, items


@login_required
@require_http_methods(['GET'])
def ride_list(request):
    q = request.GET.get('q', '')[:200].strip()
    pending = request.GET.get('pending') == '1'
    rides = scoped_inventory(request.user, Ride).select_related('bike').order_by('-started_at', '-pk')
    if pending:
        from .services.home import pending_rides
        rides = pending_rides(request.user).select_related('bike').order_by('-started_at', '-pk')
    bike = None
    if 'bike' in request.GET:
        # Own bike only; foreign or malformed identifiers are 404.
        try:
            bike = get_inventory(request.user, Bike, UUID(request.GET['bike']))
        except ValueError:
            raise Http404 from None
        rides = rides.filter(bike=bike)
    if q:
        rides = rides.filter(Q(name__icontains=q) | Q(sport_type__icontains=q))
    page = Paginator(rides, 20).get_page(request.GET.get('page'))
    # One locked resolver snapshot for the whole page instead of one per row.
    from .services.ride_review import resolve_rides
    resolutions = resolve_rides(request.user, list(page))
    names = {item.pk: item for item in scoped_inventory(request.user, Item).filter(
        pk__in={pk for resolution in resolutions.values() for pk in resolution.item_ids})}
    from .services.strava_sources import ride_origins
    origins = ride_origins(request.user, [ride.pk for ride in page])
    rows = [{'ride': ride, 'resolution': resolutions[ride.pk], 'origin': origins[ride.pk][0], 'duplicate': origins[ride.pk][1],
             'items': sorted((names[pk] for pk in resolutions[ride.pk].item_ids), key=lambda item: (item.name, str(item.pk)))}
            for ride in page]
    return render(request, 'garage/usage_rides.html', {'title': 'Salidas', 'tab': 'rides', 'rows': rows, 'pending': pending, 'bike': bike,
                   'has_strava': any('Strava' in row['origin'] for row in rows),
                   'page': page, 'q': q, 'query': urlencode({'q': q, **({'pending': '1'} if pending else {}), **({'bike': bike.pk} if bike else {})})})


@login_required
@require_http_methods(['GET', 'POST'])
def ride_detail(request, pk):
    ride = get_inventory(request.user, Ride, pk)
    form = OverrideWebForm(request.POST if request.method == 'POST' else None, user=request.user, ride=ride)
    if request.method == 'POST' and form.is_valid():
        try:
            form.save()
        except ValidationError as error:
            show_errors(form, error)
        else:
            messages.success(request, 'Excepción guardada.')
            return redirect('garage:usage-ride-detail', pk=ride.pk)
    resolution, items = resolved_context(request, ride)
    overrides = scoped_inventory(request.user, UsageOverride).filter(ride=ride).select_related('item').order_by('item__name', 'pk')
    sources = list(scoped_inventory(request.user, ActivitySource).filter(ride=ride).order_by('source_kind', 'started_at', 'pk'))
    active = [source for source in sources if source.withdrawn_at is None]
    from .services.strava_sources import origin_label
    from .presentation import ride_speed
    return render(request, 'garage/usage_ride.html', {'title': ride.name or 'Salida propia', 'ride': ride, 'tab': 'rides',
                   'speed': ride_speed(ride),
                   'back_url': reverse('garage:ride-review', args=[ride.pk]), 'back_label': 'Revisión',
                   'resolution': resolution, 'items': items, 'overrides': overrides, 'form': form,
                   'sources': sources, 'can_separate': len(active) > 1, 'has_strava': any(s.source_kind == 'strava' for s in sources),
                   'origin': origin_label({source.source_kind for source in active}) if active else ('Manual' if ride.manual_overrides else 'Sin fuentes activas')})


@login_required
@require_POST
def override_delete(request, pk):
    override = get_inventory(request.user, UsageOverride, pk)
    ride_id = override.ride_id
    delete_usage_override(request.user, pk)
    messages.success(request, 'Excepción eliminada. Vuelven a aplicarse perfiles y montajes vigentes.')
    return redirect('garage:usage-ride-detail', pk=ride_id)
