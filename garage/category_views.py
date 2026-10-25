"""«Crear las categorías habituales» (garage-041): one POST, idempotent, back to where it was offered."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from .services.categories import create_starter_categories

# Screens that offer the button; anything else posted as `next` goes back to Categorías.
RETURNS = ("category-list", "item-list", "item-create", "item-used-create")


def starter_message(result):
    """«Creadas 30 categorías; 12 ya existían», with singulars; never «Creadas 0»."""
    created, existing = len(result.created), len(result.existing)
    if not created:
        return f"No faltaba ninguna: {'la' if existing == 1 else 'las'} {existing} ya {'existía' if existing == 1 else 'existían'}."
    text = "Creada 1 categoría" if created == 1 else f"Creadas {created} categorías"
    return f"{text}; {existing} ya {'existía' if existing == 1 else 'existían'}."


@login_required
@require_POST
def starter(request):
    result = create_starter_categories(request.user)
    messages.success(request, starter_message(result))
    target = request.POST.get("next")
    return redirect("garage:" + (target if target in RETURNS else "category-list"))
