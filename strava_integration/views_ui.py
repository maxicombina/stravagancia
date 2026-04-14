import time
from django.views.generic import TemplateView, ListView, DetailView
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.admin.views.decorators import staff_member_required
from django.utils.decorators import method_decorator

from .models import Athlete, Activity, MissingActivity
from .services import (
    fetch_and_store_athlete,
    detect_and_save_missing_activities,
    fetch_activity_detail,
    store_activity_from_strava_data,
)


@method_decorator(staff_member_required, name='dispatch')
class DashboardView(TemplateView):
    template_name = 'strava_integration/dashboard.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['activities_count'] = Activity.objects.count()
        ctx['missing_total'] = MissingActivity.objects.count()
        ctx['missing_unloaded'] = MissingActivity.objects.filter(loaded=False).count()
        ctx['athlete'] = Athlete.objects.first()
        ctx['last_activity'] = Activity.objects.order_by('-start_date_local').first()
        return ctx


@method_decorator(staff_member_required, name='dispatch')
class ChartsView(TemplateView):
    template_name = 'strava_integration/charts.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['grafana_url'] = 'http://localhost:3001'
        ctx['public_token'] = '298efab5710541fea26bf5f5c920ed6d'
        return ctx


@staff_member_required
@require_POST
def load_athlete_api(request):
    try:
        athlete, created = fetch_and_store_athlete()
        data = {
            'status': 'ok',
            'created': created,
            'athlete': {
                'strava_id': athlete.strava_id,
                'first_name': athlete.first_name,
                'last_name': athlete.last_name,
                'username': athlete.username,
            },
        }
        return JsonResponse(data)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@staff_member_required
@require_POST
def detect_missing_api(request):
    # Accept dry_run as form field or query param
    dry_run = request.POST.get('dry_run') in ('1', 'true', 'True') or request.GET.get('dry_run') in ('1', 'true', 'True')
    try:
        summary = detect_and_save_missing_activities(dry_run=dry_run)
        return JsonResponse({'status': 'ok', **summary})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@staff_member_required
@require_POST
def load_missing_api(request):
    # Optional parameters: delay (seconds), limit (int)
    try:
        delay = int(request.POST.get('delay', request.GET.get('delay', 0)) or 0)
    except ValueError:
        delay = 0
    try:
        limit = request.POST.get('limit', request.GET.get('limit'))
        limit = int(limit) if limit is not None and limit != '' else None
    except ValueError:
        limit = None

    queryset = MissingActivity.objects.filter(loaded=False).order_by('strava_id')
    total_to_load = queryset.count()
    if limit:
        queryset = queryset[:limit]

    loaded_count = 0
    errors = []

    for missing in queryset:
        activity_id = missing.strava_id
        try:
            data = fetch_activity_detail(activity_id)
            activity, created = store_activity_from_strava_data(data)
            missing.loaded = True
            missing.save()
            loaded_count += 1
        except Exception as e:
            errors.append({'id': activity_id, 'error': str(e)})
        if delay > 0:
            time.sleep(delay)

    return JsonResponse({
        'status': 'ok',
        'requested': total_to_load,
        'processed': loaded_count,
        'errors': errors,
    })


@staff_member_required
def status_api(request):
    last = Activity.objects.order_by('-start_date_local').first()
    return JsonResponse({
        'activities_count': Activity.objects.count(),
        'missing_total': MissingActivity.objects.count(),
        'missing_unloaded': MissingActivity.objects.filter(loaded=False).count(),
        'last_activity': {
            'name': last.name,
            'date': last.start_date_local.strftime('%-d %b %Y'),
            'distance_km': last.distance_km,
            'url': last.activity_url,
        } if last else None,
    })


@method_decorator(staff_member_required, name='dispatch')
class ActivityListView(ListView):
    model = Activity
    template_name = 'strava_integration/activity_list.html'
    context_object_name = 'activities'
    paginate_by = 30

    SORTABLE_FIELDS = {
        'date': 'start_date_local',
        'distance': 'distance',
        'time': 'moving_time',
        'elevation': 'total_elevation_gain',
        'hr': 'average_heartrate',
    }
    DEFAULT_SORT = 'date'
    DEFAULT_DIR = 'desc'

    def get_ordering(self):
        sort = self.request.GET.get('sort', self.DEFAULT_SORT)
        direction = self.request.GET.get('dir', self.DEFAULT_DIR)
        field = self.SORTABLE_FIELDS.get(sort, self.SORTABLE_FIELDS[self.DEFAULT_SORT])
        return f'-{field}' if direction == 'desc' else field

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['current_sort'] = self.request.GET.get('sort', self.DEFAULT_SORT)
        ctx['current_dir'] = self.request.GET.get('dir', self.DEFAULT_DIR)
        return ctx


@method_decorator(staff_member_required, name='dispatch')
class ActivityDetailView(DetailView):
    model = Activity
    template_name = 'strava_integration/activity_detail.html'
    context_object_name = 'activity'
