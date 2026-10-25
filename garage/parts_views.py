"""Mount a part inside a component from the component's screen (garage-035)."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .models import Item
from .part_forms import PartWebForm
from .services.ownership import get_inventory
from .services.parts import add_part
from .views import form_page


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def part_create(request, pk):
    parent = get_inventory(request.user, Item, pk)
    back = reverse("garage:item-detail", args=[parent.pk])
    if parent.retired_at is not None:
        messages.error(request, f"{parent.name} está retirado o tiene un retiro programado: no admite piezas nuevas.")
        return redirect(back)
    form = PartWebForm(request.POST if request.method == "POST" else None, user=request.user, parent=parent)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            add_part(request.user, parent, data["item"], at=data["at"], slot=data["slot"], notes=data["notes"])
        except ValidationError as error:
            for message in error.messages:
                form.add_error(None, message)
        else:
            messages.success(request, f"Pieza añadida: {data['item'].name} en {parent.name}.")
            return redirect(back)
    return form_page(request, form, f"Añadir pieza a {parent.name}", back,
                     "Una pieza va dentro de este objeto (casete o disco en una rueda, por ejemplo) y cuenta el uso de este. "
                     "Se desmonta, reemplaza o mueve desde su propia ficha.", back_label=parent.name)
