"""Private photo endpoints; signed URLs are generated only after authorization."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from .models import Bike, Item, ServiceEvent
from .photo_forms import PhotoUploadForm
from .services.ownership import get_inventory
from .services.photos import delete_photo, get_photo, photo_usage, signed_photo_url, upload_photo


def _destination(photo):
    return ("bike", photo.bike) if photo.bike_id else ("item", photo.item) if photo.item_id else ("service-event", photo.service_event)


@transaction.non_atomic_requests
@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def photo_upload(request, kind=None, target_pk=None, pk=None):
    previous = get_photo(request.user, pk) if pk else None
    if previous:
        kind, target = _destination(previous)
    else:
        target = get_inventory(request.user, {"bike": Bike, "item": Item, "service-event": ServiceEvent}[kind], target_pk)
    back = reverse("garage:" + kind + "-detail", args=[target.pk])
    form = PhotoUploadForm(request.POST if request.method == "POST" else None,
                           request.FILES if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            upload_photo(request.user, target_model=type(target), target_id=target.pk,
                         source=form.cleaned_data["photo"], replace_id=previous.pk if previous else None)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, "Foto sustituida." if previous else "Foto guardada.")
            return redirect(back)
    try:
        usage = photo_usage(request.user)
    except ValidationError:
        usage = None
    return render(request, "garage/photo_form.html", {"form": form, "back": back,
        "title": "Sustituir foto" if previous else "Añadir foto", "usage": usage})


@login_required
@never_cache
@require_http_methods(["GET"])
def photo_content(request, pk):
    try:
        url = signed_photo_url(request.user, pk)
    except ValidationError:
        response = HttpResponse("La foto no está disponible.", status=503, content_type="text/plain")
    else:
        response = HttpResponseRedirect(url)
    response["Cache-Control"] = "private, no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response


@transaction.non_atomic_requests
@login_required
@never_cache
@require_POST
def photo_delete(request, pk):
    photo = get_photo(request.user, pk)
    kind, target = _destination(photo)
    back = reverse("garage:" + kind + "-detail", args=[target.pk])
    try:
        delete_photo(request.user, pk)
    except ValidationError:
        messages.error(request, "No se pudo eliminar la foto.")
    else:
        messages.success(request, "Foto eliminada. La limpieza del archivo se reintenta si es necesario.")
    return redirect(back)
