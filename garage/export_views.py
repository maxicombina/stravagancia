"""Private download endpoints; errors never expose corrupt records."""
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .services.export import ExportError, csv_zip, export_snapshot, json_bytes


@never_cache
@login_required
@require_GET
def export_page(request):
    return render(request, 'garage/export.html', {'title': 'Exportar', 'back_url': reverse('garage:more'), 'back_label': 'Más'})


@never_cache
@login_required
@require_GET
def download(request, kind):
    try:
        snapshot = export_snapshot(request.user)
    except ExportError as error:
        return HttpResponse(str(error), status=413 if error.too_large else 409, content_type='text/plain; charset=utf-8')
    body = json_bytes(snapshot) if kind == 'json' else csv_zip(snapshot)
    extension = 'json' if kind == 'json' else 'zip'
    response = HttpResponse(body, content_type='application/json' if kind == 'json' else 'application/zip')
    response['Content-Disposition'] = f'attachment; filename="garage-export-v1.{extension}"'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
