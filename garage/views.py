"""Private server-rendered Garage. All writes pass through actor-bound services."""
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from .models import Bike, Category, Installation, Item, UsageBaseline
from .services.ownership import get_inventory, scoped_inventory, reactivate_inventory
from .services.installations import close_installation, replace_installation, transfer_installation
from .web_forms import (CategoryWebForm, BikeWebForm, ItemWebForm, UsedItemWebForm,
    TemporalActionForm, InstallationWebForm, ReplacementWebForm, TransferWebForm, BaselineWebForm)

KINDS = {'bike': (Bike, BikeWebForm, 'Bicis'), 'item': (Item, ItemWebForm, 'Material'),
         'category': (Category, CategoryWebForm, 'Categorías')}


def detail_url(kind, obj):
    return reverse('garage:' + kind + '-detail', args=[obj.pk])


def show_errors(form, error):
    if hasattr(error, 'error_dict'):
        for field, errors in error.error_dict.items():
            form.add_error(field if field in form.fields else None, errors)
    else:
        form.add_error(None, error)


def form_page(request, form, title, back, explanation='', back_label='la página anterior', extra=None):
    # Every form page shows times in the viewer's zone with native pickers (garage-032).
    return render(request, 'garage/form.html', {'form': local(request, form), 'title': title, 'back': back, 'explanation': explanation,
                                                'back_url': back, 'back_label': back_label, **(extra or {})})


def local(request, form):
    """Viewer's zone preselected and native date-time pickers (garage-032)."""
    from .local_forms import localize
    from .timezones import user_time_zone
    return localize(form, user_time_zone(request))


@never_cache
@login_required
@require_http_methods(['GET'])
def index(request):
    from .services.home import home_snapshot
    return render(request, 'garage/index.html', {'home': home_snapshot(request.user), 'title': 'Garaje', 'tab': 'garage'})


@login_required
@require_http_methods(['GET'])
def inventory_list(request, kind):
    from django.utils import timezone
    from .services import lifecycle
    model, _, label = KINDS[kind]
    objects = scoped_inventory(request.user, model)
    q = request.GET.get('q', '')[:200].strip()
    state = request.GET.get('state', 'all')
    if state not in (lifecycle.FILTERS if kind == 'item' else ('active', 'retired')):
        state = 'all'
    if q:
        objects = objects.filter(name__icontains=q)
    now = timezone.now()
    if kind == 'item':
        # Mounted, available, in use or retired now (garage-042), filtered in the database so that pages of 20 hold.
        objects = lifecycle.filter_state(objects, state, at=now).select_related('category')
    elif state != 'all':
        objects = objects.filter(**({'is_archived': state == 'retired'} if kind == 'category'
                                   else {'retired_at__isnull': state == 'active'}))
    page = Paginator(objects.order_by('name', 'pk'), 20).get_page(request.GET.get('page'))
    if kind == 'item':
        page.object_list = list(page.object_list)
        lives = lifecycle.item_lifecycles(request.user, page.object_list, at=now)  # the whole page in at most three reads
        for item in page.object_list:
            item.lifecycle = lives[item.pk]
    starter = None
    if kind == 'category' or (kind == 'item' and not q and state == 'all' and not page.paginator.count):
        # «Crear las categorías habituales» (garage-041): always in Categorías, in Material while it is empty.
        from .services.categories import starter_offer
        starter = starter_offer(request.user, kind + '-list')
    states = lifecycle.CHIPS if kind == 'item' else (('active', 'Activas'), ('retired', 'Archivadas' if kind == 'category' else 'Retiradas'),
                                                     ('all', 'Todas'))
    return render(request, 'garage/list.html', {'kind': kind, 'title': label, 'page': page, 'states': states,
        'q': q, 'state': state, 'query': urlencode({'q': q, 'state': state}), 'starter': starter,
        'back_url': reverse('garage:more' if kind == 'category' else 'garage:index'), 'back_label': 'Más' if kind == 'category' else 'Garaje'})


@login_required
@require_http_methods(['GET'])
def inventory_detail(request, kind, pk):
    model = KINDS[kind][0]
    obj = get_inventory(request.user, model, pk)
    context = {'object': obj, 'kind': kind, 'title': obj.name}
    if kind == 'category':
        from .services.service_usage import category_comparison
        from .timezones import user_time_zone
        # How long each one lasts, most used first (garage-036); it also lists every item of the category.
        context['lives'] = category_comparison(request.user, obj, zone=user_time_zone(request))
        context['user_tz'] = user_time_zone(request)
        context.update(back_url=reverse('garage:category-list'), back_label='Categorías')
    else:
        from .services.photos import owned_photos
        context['photos'] = owned_photos(request.user).filter(**{kind: obj}).select_related('storage_object')
        periods = scoped_inventory(request.user, Installation).select_related('item', 'bike', 'parent_item')
        context['periods'] = periods.filter(bike=obj) if kind == 'bike' else periods.filter(item=obj)
        context['periods'] = context['periods'].order_by('-started_at', '-pk')
        if kind == 'item':
            context['children'] = periods.filter(parent_item=obj).order_by('-started_at', '-pk')
            context['readings'] = scoped_inventory(request.user, UsageBaseline).filter(item=obj).order_by('-cut_at', '-pk')
            context.update(item_dashboard(request, obj))
            return render(request, 'garage/item_detail.html', context)
        context.update(bike_dashboard(request, obj))
        return render(request, 'garage/bike_detail.html', context)
    return render(request, 'garage/detail.html', context)


def item_dashboard(request, item):
    """Read-only blocks of the mobile component screen (garage-031.3)."""
    from django.utils import timezone
    from .charts import line_chart
    from .presentation import by_severity, wear
    from .services.maintenance_due import maintenance_due
    from .services.monthly import monthly_usage
    from .services.statistics import statistics
    from .timezones import user_time_zone
    zone = user_time_zone(request)
    now = timezone.now()
    report = statistics(request.user, item=item, started_to=now)
    row = report.rows[0] if report.rows else None
    series = monthly_usage(request.user, item=item, tz=zone, at=now)
    mounts = tuple(reversed(row.installations)) if row else ()
    current = next((block.reference for block in mounts if block.reference.started_at <= now
                    and (block.reference.ended_at is None or block.reference.ended_at > now)), None)
    from .services.lifespan import is_life
    from .services.parts import placement
    dues = maintenance_due(request.user, at=now)
    wears = by_severity([wear(due) for due in dues if due.rule.item_id == item.pk])
    wears.sort(key=lambda item_wear: not is_life(item_wear.rule))  # the useful life first; stable: severity order kept
    # Parts mounted inside this item now (garage-035), each with its most severe rule.
    parts, _ = placement(request.user, item, at=now)
    part_ids = {mount.item_id for mount in parts}
    worst = {}
    for item_wear in by_severity([wear(due) for due in dues if due.rule.item_id in part_ids]):
        worst.setdefault(item_wear.rule.item_id, item_wear)
    # Its state line with the words of the Material list and the home screen (garage-042): retired (no query),
    # mounted (one query), in use, available or never used (up to three). A retirement still to come is not «retirado».
    from .services.lifecycle import item_lifecycles
    lifecycle = item_lifecycles(request.user, [item], at=now)[item.pk]
    return {'wears': wears, 'lifecycle': lifecycle, 'life': next((w for w in wears if is_life(w.rule)), None),
            'parts': [{'mount': mount, 'wear': worst.get(mount.item_id)} for mount in parts],
            'stats': row, 'usage_current': report.materialization_current, 'monthly': series,
            'chart': line_chart(series.buckets), 'mounts': mounts, 'current_mount': current,
            'interventions': _with_previous(row.interventions if row else ()), 'user_tz': zone,
            'back_url': reverse('garage:index'), 'back_label': 'Garaje'}


def _with_previous(blocks):
    """Newest first, each with the usage since the previous intervention of its type (garage-036)."""
    from types import SimpleNamespace
    from .services.service_usage import item_spans, previous_spans
    since = previous_spans(item_spans(blocks), [block.reference for block in blocks])
    ordered = sorted(blocks, key=lambda block: (block.reference.performed_at, block.reference.created_at, str(block.reference.pk)), reverse=True)
    return tuple(SimpleNamespace(reference=block.reference, since=since.get(block.reference.pk)) for block in ordered)


RECENT_RIDES = 5


def bike_dashboard(request, bike):
    """Read-only blocks of the mobile bike screen (garage-032.2)."""
    from django.db.models import Count, Q, Sum
    from django.utils import timezone
    from .charts import line_chart
    from .models import Ride, ServiceEvent
    from .presentation import by_severity, wear
    from .services.home import HomeAlert, mount_resolver
    from .services.maintenance_due import maintenance_due
    from .services.monthly import monthly_usage
    from .timezones import user_time_zone
    zone = user_time_zone(request)
    now = timezone.now()
    owner = request.user
    open_now = list(scoped_inventory(owner, Installation).filter(started_at__lte=now).filter(Q(ended_at__isnull=True) | Q(ended_at__gt=now))
                    .select_related('item__category', 'parent_item').order_by('started_at', 'pk'))
    mount_of = mount_resolver([(m.item_id, m.bike_id, m.parent_item_id) for m in open_now],
                              {bike.pk: bike.name}, {m.item_id: m.item.name for m in open_now})
    mounted = [m for m in open_now if mount_of(m.item_id)[0] == bike.pk]
    mounted_ids = {m.item_id for m in mounted}
    parents = {m.item_id: m.parent_item for m in mounted if m.bike_id is None}
    wears = [item_wear for item_wear in by_severity([wear(due) for due in maintenance_due(owner, at=now)
                                                     if due.rule.bike_id == bike.pk or due.rule.item_id in mounted_ids])
             if item_wear.target.retired_at is None or item_wear.target.retired_at > now]
    worst = {}
    for item_wear in wears:
        if item_wear.rule.item_id and item_wear.rule.item_id not in worst:
            worst[item_wear.rule.item_id] = item_wear
    rides = scoped_inventory(owner, Ride).filter(bike=bike, started_at__isnull=False, started_at__lt=now)
    totals = rides.aggregate(distance=Sum('distance_m'), moving=Sum('moving_time_s'), count=Count('id'),
                             no_distance=Count('id', filter=Q(distance_m__isnull=True)),
                             no_time=Count('id', filter=Q(moving_time_s__isnull=True)),
                             elevation=Sum('elevation_gain_m'), no_elevation=Count('id', filter=Q(elevation_gain_m__isnull=True)))

    def place(item_wear):
        # On its own screen the bike's name adds nothing; a nested part names its parent.
        if item_wear.rule.item_id in parents:
            return f"sobre {parents[item_wear.rule.item_id].name}"
        return "" if item_wear.rule.item_id else "bici"
    series = monthly_usage(owner, bike=bike, tz=zone, at=now)
    from .services.service_usage import bike_spans, previous_spans
    events = list(scoped_inventory(owner, ServiceEvent).filter(bike=bike).select_related('service_type').order_by('-performed_at', '-created_at', '-id'))
    past = [event for event in events if event.performed_at <= now]  # one registered ahead has no usage yet
    since = previous_spans(bike_spans(list(rides.only('id', 'started_at', 'bike_id', 'distance_m', 'moving_time_s', 'elevation_gain_m')),
                                      past, now), past)
    for event in events:
        event.since = since.get(event.pk)  # usage since the previous one of its type (garage-036)
    return {'attention': [HomeAlert(item_wear, place(item_wear)) for item_wear in wears if item_wear.needs_attention],
            'snoozed': [HomeAlert(item_wear, place(item_wear)) for item_wear in wears if item_wear.state == 'snoozed'],
            'calm': [HomeAlert(item_wear, place(item_wear)) for item_wear in wears if not item_wear.needs_attention and item_wear.state != 'snoozed'],
            'mounted': [{'mount': m, 'nested': m.bike_id is None, 'wear': worst.get(m.item_id)} for m in mounted],
            'totals': totals, 'monthly': series, 'chart': line_chart(series.buckets),
            'recent': list(rides.order_by('-started_at', '-pk')[:RECENT_RIDES]),
            'events': events,
            'user_tz': zone, 'back_url': reverse('garage:index'), 'back_label': 'Garaje'}


@login_required
@require_http_methods(['GET', 'POST'])
def inventory_edit(request, kind, pk=None, used=False):
    model, form_class, label = KINDS[kind]
    obj = get_inventory(request.user, model, pk) if pk else None
    if used:
        form_class = UsedItemWebForm
    form = form_class(request.POST if request.method == 'POST' else None, user=request.user, instance=obj)
    back = detail_url(kind, obj) if obj else reverse('garage:' + kind + '-list')
    if request.method == 'POST' and form.is_valid():
        try:
            saved = form.save_with_readings() if used else form.save()
        except ValidationError as error:
            show_errors(form, error)
        else:
            messages.success(request, 'Guardado correctamente.')
            return redirect(detail_url(kind, saved))
    extra = None
    if kind == 'item' and obj is None and not form.fields['category'].queryset.exists():
        # No category yet, and an item needs one: offer the starter set here too (garage-041).
        from .services.categories import starter_offer
        extra = {'starter': starter_offer(request.user, 'item-used-create' if used else 'item-create')}
    return form_page(request, form, ('Editar ' if obj else 'Crear ') + label.lower(), back,
        'Cada lectura es independiente. Vacío significa desconocido; no sumamos lecturas históricas.' if used else '',
        back_label=obj.name if obj else label, extra=extra)


@login_required
@require_http_methods(['GET', 'POST'])
def retire(request, kind, pk):
    from django.utils import timezone
    from .services.retirement import PartsChanged, mounted_in, retire_with_parts
    from .web_forms import RetireWebForm
    obj = get_inventory(request.user, KINDS[kind][0], pk)
    # With a retirement already scheduled its mounts close at that date: parts are retired from their own screens.
    inside = mounted_in(request.user, obj) if kind in ('bike', 'item') and obj.retired_at is None else ()
    form = RetireWebForm(request.POST if request.method == 'POST' else None, user=request.user, inside=inside)
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        try:
            also = retire_with_parts(request.user, obj, at=data['at'], parts=data.get('with_parts', False),
                                     expected=data.get('shown_parts'))
        except PartsChanged as error:
            # The list at that date is the one confirmed by saving again.
            posted = request.POST.copy()
            posted['shown_parts'] = ','.join(str(pk) for pk in error.ids)
            form = RetireWebForm(posted, user=request.user, inside=inside)
            form.is_valid()
            show_errors(form, error)
        except ValidationError as error:
            show_errors(form, error)
        else:
            done = 'Retirada' if kind == 'bike' else 'Retirado'
            plural = 'También retirados: ' if len(also) > 1 else 'También retirado: '
            messages.success(request, f'{done}. El historial se conserva.' + (' ' + plural + ', '.join(item.name for item in also) + '.' if also else ''))
            return redirect(detail_url(kind, obj))
    return form_page(request, form, 'Retirar ' + obj.name, detail_url(kind, obj),
                     'Se cerrarán los montajes abiertos compatibles con este instante. El historial permanece disponible.', back_label=obj.name)


@login_required
@require_POST
def reactivate(request, kind, pk):
    obj = get_inventory(request.user, KINDS[kind][0], pk)
    try:
        reactivate_inventory(request.user, type(obj), pk)
    except ValidationError as error:
        messages.error(request, 'No se pudo reactivar: ' + ' '.join(error.messages))
    else:
        messages.success(request, ('Reactivada' if kind == 'bike' else 'Reactivado') + '. Los períodos cerrados no se reabren.')
    return redirect(detail_url(kind, obj))


@login_required
@require_http_methods(['GET', 'POST'])
def installation_edit(request, item_pk=None, pk=None):
    installation = get_inventory(request.user, Installation, pk) if pk else None
    item = get_inventory(request.user, Item, installation.item_id if installation else item_pk)
    form = InstallationWebForm(request.POST if request.method == 'POST' else None,
        user=request.user, item=item, installation=installation)
    if request.method == 'POST' and form.is_valid():
        try:
            form.save()
        except ValidationError as error:
            show_errors(form, error)
        else:
            messages.success(request, 'Período de montaje guardado.')
            return redirect(detail_url('item', item))
    return form_page(request, form, ('Editar montaje de ' if installation else 'Montar ') + item.name,
        detail_url('item', item), 'Un solo destino. Los intervalos incluyen el inicio y excluyen el final; puedes remontar después del cierre.',
        back_label=item.name)


@login_required
@require_http_methods(['GET', 'POST'])
def installation_action(request, pk, action):
    period = get_inventory(request.user, Installation, pk)
    item = get_inventory(request.user, Item, period.item_id)
    form_class = {'close': TemporalActionForm, 'replace': ReplacementWebForm, 'transfer': TransferWebForm}[action]
    kwargs = {'user': request.user}
    if action != 'close':
        kwargs['installation'] = period
    form = form_class(request.POST if request.method == 'POST' else None, **kwargs)
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        try:
            if action == 'close':
                close_installation(request.user, pk, at=data['at'])
            elif action == 'replace':
                from django.db import transaction
                from .presentation import thresholds
                from .services.lifespan import inherit_lifespan
                from django.utils import timezone
                from .services.lifespan import lifespan_rule
                copied = None
                inherit = data.get('inherit_lifespan') and data['at'] <= timezone.now()
                from .services.retirement import direct_parts, retire_one
                retire_outgoing = data.get('retire_outgoing') and data['at'] <= timezone.now()
                released = []
                with transaction.atomic():  # the replacement, its inherited useful life and the retirement, or none
                    replace_installation(request.user, pk, incoming_item=data['incoming_item'], at=data['at'])
                    if inherit:
                        copied = inherit_lifespan(request.user, outgoing=item, incoming=data['incoming_item'], at=data['at'])
                    if retire_outgoing:
                        released = direct_parts(request.user, item, at=data['at'])
                        retire_one(request.user, item, at=data['at'])
                if data.get('retire_outgoing') and not retire_outgoing:
                    messages.info(request, "Reemplazo futuro: lo que sale no se retira. Retíralo cuando ocurra.")
                if data.get('inherit_lifespan') and not inherit:
                    messages.info(request, "Reemplazo futuro: la vida útil no se hereda. Defínela en la pieza nueva cuando la montes.")
                elif copied is not None:
                    messages.info(request, f"{data['incoming_item'].name} hereda la vida útil: {thresholds(copied, separator=' o ')}, desde el reemplazo.")
                elif inherit:
                    messages.info(request, f"{data['incoming_item'].name} ya tenía su vida útil: no se cambia.")
                outgoing_life = lifespan_rule(request.user, item) if data.get('inherit_lifespan') and not retire_outgoing else None
                if retire_outgoing:
                    messages.info(request, f"{item.name}: retirado desde el reemplazo. Se puede reactivar desde su ficha." +
                                  (" Sus piezas quedan desmontadas y disponibles: " + ", ".join(obj.name for obj in released) + "." if released else ""))
                if outgoing_life is not None and outgoing_life.calendar_days is not None:
                    messages.info(request, f"La pieza que sale ({item.name}) sigue contando días aunque ya no esté montada: retira la pieza o quita su vida útil si no la vas a usar.")
            else:
                transfer_installation(request.user, pk, at=data['at'], bike=data['bike'],
                                      parent_item=data['parent_item'], slot=data['slot'])
        except ValidationError as error:
            show_errors(form, error)
        else:
            messages.success(request, 'Historial actualizado.')
            return redirect(detail_url('item', item))
    titles = {'close': 'Desmontar ', 'replace': 'Reemplazar ', 'transfer': 'Transferir '}
    return form_page(request, form, titles[action] + item.name, detail_url('item', item),
                     'El período anterior se conserva. El cambio debe respetar los destinos, posiciones y fechas del historial.', back_label=item.name)


@login_required
@require_http_methods(['GET', 'POST'])
def baseline_edit(request, item_pk=None, pk=None):
    reading = get_inventory(request.user, UsageBaseline, pk) if pk else None
    item = get_inventory(request.user, Item, reading.item_id if reading else item_pk)
    form = BaselineWebForm(request.POST if request.method == 'POST' else None,
                           user=request.user, item=item, instance=reading)
    if request.method == 'POST' and form.is_valid():
        try:
            form.save()
        except ValidationError as error:
            show_errors(form, error)
        else:
            messages.success(request, 'Lectura guardada.')
            return redirect(detail_url('item', item))
    return form_page(request, form, 'Lectura de ' + item.name, detail_url('item', item),
        'Una métrica, un ámbito y un instante. Cero es conocido; una métrica sin lectura permanece desconocida. Una nueva lectura no se suma a la anterior.',
        back_label=item.name)
