"""garage-041: starter categories with icons, icon choice and icon deduction."""
import csv
import io
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .category_views import starter_message
from .icons import _KEYWORDS, ICON_CHOICES, ICON_KEYS, category_icon_key, item_icon_key, match_icon
from .models import Category, Item
from .services.categories import (STARTER, StarterResult, create_starter_categories, missing_starter, starter_offer,
                                  suggest_icon)
from .services.export import csv_zip, export_snapshot
from .services.ownership import CategoryNameConflict, _lock_owner, create_inventory, update_inventory
from .web_forms import CategoryWebForm
from .templatetags.garage_ui import category_icon, icon_label, item_icon

WRITES = {"INSERT", "UPDATE", "DELETE"}
SPRITE = "garage/templates/garage/_icons.html"


def writes(queries):
    return [q["sql"] for q in queries if q["sql"].lstrip().split()[0].upper() in WRITES]


@pytest.fixture
def owner(db):
    return get_user_model().objects.create_user("cat-owner", password="test-only-password")


@pytest.fixture
def other(db):
    return get_user_model().objects.create_user("cat-other", password="test-only-password")


@pytest.fixture
def logged(owner, client):
    client.force_login(owner)
    return client


class TestIconCatalogue:
    def test_every_key_has_a_symbol_and_a_safe_shape(self):
        from pathlib import Path
        from django.conf import settings
        sprite = (Path(settings.BASE_DIR) / SPRITE).read_text()
        symbols = set(re.findall(r'<symbol id="i-([a-z_]+)"', sprite))
        keys = [key for key, _, _ in ICON_CHOICES]
        assert len(keys) == len(set(keys)) and set(keys) <= symbols
        assert all(re.fullmatch(r"[a-z_]+", key) and len(key) <= 32 for key in keys)
        assert {"chain", "tire", "wheel", "brake", "cassette", "saddle", "shoe", "helmet", "light", "part", "bike"} <= ICON_KEYS
        # The starter set needs 32 new symbols, all drawn in the same 24x24 stroke style.
        new = {icon for _, _, icon in STARTER} - {"chain", "tire", "wheel", "brake", "cassette", "saddle", "shoe", "helmet", "light"}
        assert len(new) == 32
        for key in new:
            assert re.search(rf'<symbol id="i-{key}" viewBox="0 0 24 24">', sprite)
        assert "fill=" not in sprite.split('id="i-chainring"')[1]  # line icons: no filled shapes among the new ones

    def test_labels_are_spanish_and_shown_by_filter(self):
        assert icon_label("brake_lever") == "Maneta de freno" and icon_label("nope") == ""

    def test_starter_is_the_spec_list(self):
        assert len(STARTER) == 42 and len({name.lower() for _, name, _ in STARTER}) == 42
        groups = list(dict.fromkeys(group for group, _, _ in STARTER))
        assert groups == ["Transmisión", "Ruedas", "Frenos", "Dirección y postura", "Suspensión", "Pedales", "Equipación"]
        assert ("Frenos", "Manetas de freno", "brake_lever") in STARTER and ("Equipación", "Bidón y portabidón", "bottle") in STARTER


class TestSuggestion:
    def test_each_starter_name_suggests_its_own_icon(self):
        assert [(name, suggest_icon(name)) for _, name, icon in STARTER] == [(name, icon) for _, name, icon in STARTER]

    @pytest.mark.parametrize("name,icon", [
        ("CÁMARAS 29", "tube"), ("camara", "tube"), ("Piñón", "cassette"), ("Sillin", "saddle"), ("Cadenas", "chain"),
        ("Cinta de manillar", "grips"), ("Mando de cambio", "shifter"), ("Cables de cambio", "cable"),
        ("Pinzas de freno", "caliper"), ("Discos de freno", "disc"), ("Medidor de potencia", "sensor"),
        ("Suspensión trasera", "shock"), ("Cubierta tubeless", "tire"), ("Funda de sillín", "saddle"),
        ("Pedalier BSA", "bottom_bracket"), ("Varios", ""), ("", ""), ("Carretera", ""),
        # The word written first (the head noun) wins, whatever its length or the catalogue order
        # (review and re-verification of garage-041).
        ("Llave de radios", "tool"), ("Radios de rueda", "spoke"), ("Llave de pedales", "tool"),
        ("Rueda con radios", "wheel"), ("Llave de cadena", "tool"), ("Llave de casete", "tool"),
        ("Luz de casco", "light"), ("Bolsa de sillín", "bag"), ("Bolsa de manillar", "bag"),
        ("Funda para casco", "helmet"), ("Fundas de freno", "cable"),  # a bare «funda» is any cover
        # Whole words only, with a plural: no «cambio» in «Recambios», no «hub» in «Chubasquero».
        ("Recambios varios", ""), ("Chubasquero", ""), ("Escalador", ""), ("Discreto", ""),
        ("Discos 160", "disc"), ("discs", "disc"), ("Neumáticos 28", "tire"), ("Cubierta/cámara", "tire"),
    ])
    def test_specific_keywords_win_and_accents_do_not_matter(self, name, icon):
        assert suggest_icon(name) == match_icon(name) == icon

    def test_ties_never_depend_on_the_catalogue_order(self):
        words = [word for word, _, _ in _KEYWORDS]
        assert len(words) == len(set(words))  # a keyword names one icon only
        # «radio» (spoke) is listed before «llave» (tool); position decides, both ways round.
        assert match_icon("llave radio") == "tool" and match_icon("radio llave") == "spoke"


class TestItemIcon:
    def test_category_icon_first_then_item_name_then_category_name(self):
        cat = SimpleNamespace(name="Ruedas", icon="wheel")
        assert item_icon(SimpleNamespace(name="Cubierta GP5000", category=cat)) == "wheel"
        cat.icon = ""
        assert item_icon(SimpleNamespace(name="Cubierta GP5000", category=cat)) == "tire"  # the item refines
        assert item_icon(SimpleNamespace(name="Sin pistas", category=cat)) == "wheel"
        assert item_icon(SimpleNamespace(name="Sin pistas", category=SimpleNamespace(name="Varios", icon=""))) == "part"
        # Pre-041 behaviour kept: «Cadenas» / «Cadena 11v» -> chain; no category at all.
        assert item_icon(SimpleNamespace(name="Cadena 11v", category=SimpleNamespace(name="Cadenas", icon=""))) == "chain"
        assert item_icon_key(SimpleNamespace(name="Luz trasera")) == "light"

    @pytest.mark.parametrize("category,item,before,now", [
        # Pre-041 table: category + item text, first keyword in table order. Now the item's own name first,
        # with the new icons (documented in the handoff as a visible change for the user to confirm).
        ("Frenos", "Disco delantero", "brake", "disc"), ("Ruedas", "Llanta trasera", "wheel", "rim"),
        ("Transmisión", "Plato 50", "cassette", "chainring"), ("Pedales", "Calas SPD", "shoe", "cleat"),
        ("Cubiertas", "Cámara 29", "tire", "tube"), ("Ruedas", "Cubierta GP5000", "tire", "tire"),
    ])
    def test_change_from_the_pre_041_deduction(self, category, item, before, now):
        assert item_icon(SimpleNamespace(name=item, category=SimpleNamespace(name=category, icon=""))) == now

    @pytest.mark.parametrize("name,category,hint", [
        ("Llanta trasera", "Ruedas", "Orientativo para una rueda: <b>unos 20.000 km</b>"),  # kept: same text as before
        ("Cubierta GP5000", "Ruedas", "Orientativo para una cubierta: <b>unos 4.000 km</b>"),
        ("Disco delantero", "Frenos", None), ("Plato 50", "Transmisión", None), ("Calas SPD", "Pedales", None),
        ("Cámara 29", "Cubiertas", None),  # these used to borrow another part's figure
    ])
    def test_lifespan_hint_follows_the_deduced_icon(self, owner, logged, name, category, hint):
        item = create_inventory(owner, Item, name=name, category=create_inventory(owner, Category, name=category))
        html = logged.get(reverse("garage:item-lifespan", args=[item.pk])).content.decode()
        assert (hint in html) if hint else "Orientativo para" not in html

    def test_unknown_stored_key_falls_back_to_the_names(self):
        assert item_icon_key(SimpleNamespace(name="Casco", category=SimpleNamespace(name="X", icon="retired_key"))) == "helmet"

    def test_category_glyph(self):
        assert category_icon(SimpleNamespace(name="Lo que sea", icon="tool")) == "tool"
        assert category_icon(SimpleNamespace(name="Zapatillas", icon="")) == "shoe"
        assert category_icon_key(SimpleNamespace(name="Varios", icon="")) == "tag"

    def test_rendered_with_the_category_icon(self, owner, logged):
        cat = create_inventory(owner, Category, name="Cosas", icon="bottle")
        item = create_inventory(owner, Item, name="Cadena vieja", category=cat)
        assert 'href="#i-bottle"' in logged.get(reverse("garage:item-detail", args=[item.pk])).content.decode()
        items = logged.get(reverse("garage:item-list")).content.decode()
        assert 'href="#i-bottle"' in items and 'href="#i-chain"' not in items


class TestModel:
    def test_valid_and_invalid_icons(self, owner):
        assert create_inventory(owner, Category, name="A", icon="").icon == ""
        cat = create_inventory(owner, Category, name="B", icon="brake_lever")
        with pytest.raises(ValidationError) as error:
            create_inventory(owner, Category, name="C", icon="rocket")
        assert error.value.message_dict["icon"] == ["Choose one of the listed icons."]
        with pytest.raises(ValidationError):
            update_inventory(owner, Category, cat.pk, icon="Chain")
        assert not Category.objects.filter(name="C").exists() and Category.objects.get(pk=cat.pk).icon == "brake_lever"

    def test_database_check(self, owner):
        cat = create_inventory(owner, Category, name="A")
        Category.objects.filter(pk=cat.pk).update(icon="key_from_the_future")  # the shape only: the list may grow
        for bad in ("Chain", "bad-icon", " chain", "ч"):
            with pytest.raises(IntegrityError), transaction.atomic():
                Category.objects.filter(pk=cat.pk).update(icon=bad)


class TestStarterService:
    def test_creates_all_with_icons_then_nothing(self, owner):
        first = create_starter_categories(owner)
        assert isinstance(first, StarterResult) and len(first.created) == 42 and first.existing == ()
        rows = {cat.name: cat.icon for cat in Category.objects.filter(owner=owner)}
        assert rows == {name: icon for _, name, icon in STARTER}
        second = create_starter_categories(owner)
        assert second.created == () and len(second.existing) == 42 and Category.objects.filter(owner=owner).count() == 42
        assert missing_starter(owner) == 0 and starter_offer(owner, "category-list") is None

    def test_case_insensitive_and_never_touches_existing(self, owner):
        lower = create_inventory(owner, Category, name="cadena", notes="mía", icon="")
        upper = create_inventory(owner, Category, name="CÁMARA", icon="bag")
        archived = create_inventory(owner, Category, name="Casco", is_archived=True)
        mine = create_inventory(owner, Category, name="Mis cosas")
        assert missing_starter(owner) == 39
        result = create_starter_categories(owner)
        assert len(result.created) == 39 and set(result.existing) == {"Cadena", "Cámara", "Casco"}
        for obj, values in ((lower, ("cadena", "mía", "", False)), (upper, ("CÁMARA", "", "bag", False)),
                            (archived, ("Casco", "", "", True)), (mine, ("Mis cosas", "", "", False))):
            obj.refresh_from_db()
            assert (obj.name, obj.notes, obj.icon, obj.is_archived) == values
        assert Category.objects.filter(owner=owner).count() == 43

    def test_ownership(self, owner, other):
        create_inventory(other, Category, name="Cadena", icon="chain")
        create_starter_categories(other)
        before = list(Category.objects.filter(owner=other).values_list("pk", "name", "icon", "updated_at").order_by("pk"))
        result = create_starter_categories(owner)
        assert len(result.created) == 42 and all(cat.owner_id == owner.pk for cat in result.created)
        assert list(Category.objects.filter(owner=other).values_list("pk", "name", "icon", "updated_at").order_by("pk")) == before

    def test_under_the_owner_lock_in_few_queries(self, owner):
        with CaptureQueriesContext(connection) as queries:
            create_starter_categories(owner)
        sql = [q["sql"] for q in queries]
        lock = next(i for i, text in enumerate(sql) if "FOR UPDATE" in text and "auth_user" in text)
        insert = next(i for i, text in enumerate(sql) if text.startswith("INSERT"))
        assert lock < insert and len(writes(queries)) == 1 and len(sql) <= 8

    def test_inactive_user_cannot(self, owner):
        owner.is_active = False
        owner.save()
        with pytest.raises(PermissionDenied):
            create_starter_categories(owner)
        assert not Category.objects.exists()

    def test_messages(self):
        def result(created, existing):
            return StarterResult(tuple(range(created)), tuple(range(existing)))
        assert starter_message(result(30, 12)) == "Creadas 30 categorías; 12 ya existían."
        assert starter_message(result(1, 41)) == "Creada 1 categoría; 41 ya existían."
        assert starter_message(result(41, 1)) == "Creadas 41 categorías; 1 ya existía."
        assert starter_message(result(42, 0)) == "Creadas 42 categorías; 0 ya existían."
        assert starter_message(result(0, 42)) == "No faltaba ninguna: las 42 ya existían."


class TestStarterScreens:
    def test_categories_list_offers_it_with_the_missing_count(self, owner, logged):
        html = logged.get(reverse("garage:category-list")).content.decode()
        assert "Crear las categorías habituales" in html and "Crea de una vez las 42 habituales" in html
        assert f'action="{reverse("garage:category-starter")}"' in html and 'name="next" value="category-list"' in html
        assert re.search(r'<form method="post" action="[^"]+"><input type="hidden" name="csrfmiddlewaretoken"', html)
        create_inventory(owner, Category, name="Cadena")
        html = logged.get(reverse("garage:category-list")).content.decode()
        assert "Te faltan 41 de las 42 habituales" in html
        assert '<h1>Categorías</h1>' in html and '<h2 id="starter-title">Categorías habituales</h2>' in html and "<h3" not in html
        create_starter_categories(owner)
        assert "Crear las categorías habituales" not in logged.get(reverse("garage:category-list")).content.decode()
        Category.objects.filter(owner=owner, name="Cadena").delete()
        html = logged.get(reverse("garage:category-list")).content.decode()
        assert "Te falta 1 de las 42 habituales" in html and "Te faltan 1 " not in html

    def test_post_creates_and_returns(self, owner, logged):
        create_inventory(owner, Category, name="PASTILLAS")
        response = logged.post(reverse("garage:category-starter"), {"next": "item-list"})
        assert response.status_code == 302 and response["Location"] == reverse("garage:item-list")
        assert [str(m) for m in get_messages(response.wsgi_request)] == ["Creadas 41 categorías; 1 ya existía."]
        response = logged.post(reverse("garage:category-starter"), {"next": "https://evil.example/"})
        assert response["Location"] == reverse("garage:category-list")
        assert Category.objects.filter(owner=owner).count() == 42

    def test_category_list_rows_show_their_icon(self, owner, logged):
        create_starter_categories(owner)
        create_inventory(owner, Category, name="Zapatos viejos")  # no icon: deduced from the name
        html = logged.get(reverse("garage:category-list"), {"q": "maneta"}).content.decode()
        assert 'href="#i-brake_lever"' in html and 'href="#i-shifter"' in html
        detail = logged.get(reverse("garage:category-detail", args=[Category.objects.get(owner=owner, name="Bidón y portabidón").pk]))
        assert 'href="#i-bottle"' in detail.content.decode()

    def test_material_offers_it_only_while_empty(self, owner, logged):
        html = logged.get(reverse("garage:item-list")).content.decode()
        assert "Crear las categorías habituales" in html and 'name="next" value="item-list"' in html
        cat = create_inventory(owner, Category, name="Cosas")
        assert "Crear las categorías habituales" in logged.get(reverse("garage:item-list")).content.decode()
        create_inventory(owner, Item, name="Algo", category=cat)
        assert "Crear las categorías habituales" not in logged.get(reverse("garage:item-list")).content.decode()
        # A search without results is not an empty Material.
        assert "Crear las categorías habituales" not in logged.get(reverse("garage:item-list"), {"q": "zzz"}).content.decode()

    @pytest.mark.parametrize("route", ["item-create", "item-used-create"])
    def test_item_form_without_categories(self, owner, logged, route):
        html = logged.get(reverse("garage:" + route)).content.decode()
        assert "Cada objeto necesita una categoría." in html and f'name="next" value="{route}"' in html
        # Outside the item form: no nested forms.
        assert html.index('action="' + reverse("garage:category-starter")) < html.index('<form method="post" novalidate class="form">')
        response = logged.post(reverse("garage:category-starter"), {"next": route})
        assert response["Location"] == reverse("garage:" + route)
        html = logged.get(reverse("garage:" + route)).content.decode()
        assert "Crear las categorías habituales" not in html and "Manetas de freno" in html  # now in the category select

    def test_post_only_csrf_and_login(self, owner, client):
        url = reverse("garage:category-starter")
        assert client.post(url)["Location"].startswith("/accounts/login/")
        client.force_login(owner)
        assert client.get(url).status_code == 405
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(owner)
        assert strict.post(url).status_code == 403 and not Category.objects.exists()
        strict.get(reverse("garage:category-list"))
        assert strict.post(url, {"csrfmiddlewaretoken": strict.cookies["csrftoken"].value}).status_code == 302
        assert Category.objects.filter(owner=owner).count() == 42


class TestCategoryForm:
    def test_grid_of_radio_icons(self, logged):
        html = logged.get(reverse("garage:category-create")).content.decode()
        start = html.index('<fieldset class="field icon-field')
        grid = html[start:html.index("</fieldset>", start)]
        radios = re.findall(r'<input type="radio" name="icon" id="(id_icon_\d+)" value="([a-z_]*)" aria-label="([^"]+)"( checked)?>', grid)
        assert len(radios) == len(ICON_CHOICES) + 1
        assert radios[0][1:] == ("", "Según el nombre", " checked") and not any(r[3] for r in radios[1:])
        assert '<use href="#i-tag"/></svg><span>Según el nombre</span>' in grid  # nothing typed yet: the generic tag
        for radio_id, value, label, _ in radios[1:]:
            assert f'<label for="{radio_id}"><svg class="ic" aria-hidden="true"><use href="#i-{value}"/></svg><span>{label}</span></label>' in grid
        # Each radio inside its own positioned tile, right before its label (review: focus box and scrolling).
        tiles = re.findall(r'<span class="tile"><input type="radio"[^>]*>\s*<label for="id_icon_\d+">.*?</label></span>', grid)
        assert len(tiles) == len(radios) and grid.count("<input") == len(radios)
        assert "<legend>Icono</legend>" in grid and not re.search(r"<script(?![^>]*\bsrc=)|\bon(click|change)=", html)  # no JavaScript

    def test_grid_inputs_sit_over_their_own_tile(self):
        from pathlib import Path
        from django.conf import settings
        css = (Path(settings.BASE_DIR) / "garage/static/garage/garage.css").read_text()
        rule = lambda selector: re.search(re.escape(selector) + r" \{([^}]*)\}", css).group(1)
        assert "position: relative" in rule(".choice.icons .tile")
        assert "inset: 0" in rule(".choice.icons input") and "position: relative" not in rule(".choice.icons")
        assert "position: absolute" in rule(".choice input")  # hidden over its tile, still focusable

    def test_chosen_icon_is_saved(self, owner, logged):
        response = logged.post(reverse("garage:category-create"), {"name": "Cosas de bici", "icon": "tool"})
        assert response.status_code == 302 and Category.objects.get(owner=owner).icon == "tool"

    def test_by_name_stores_nothing_and_each_item_refines(self, owner, logged):
        logged.post(reverse("garage:category-create"), {"name": "  Cubiertas de invierno ", "icon": ""})
        logged.post(reverse("garage:category-create"), {"name": "Varios"})
        logged.post(reverse("garage:category-create"), {"name": "Ruedas y cubiertas", "icon": ""})
        assert dict(Category.objects.filter(owner=owner).values_list("name", "icon")) == {
            "Cubiertas de invierno": "", "Varios": "", "Ruedas y cubiertas": ""}
        mixed = Category.objects.get(owner=owner, name="Ruedas y cubiertas")
        wheel = create_inventory(owner, Item, name="Rueda trasera", category=mixed)
        tire = create_inventory(owner, Item, name="Cubierta GP5000", category=mixed)
        # The category suggests its head noun («Ruedas»); each item still refines by its own name.
        assert (item_icon(wheel), item_icon(tire), category_icon(mixed)) == ("wheel", "tire", "wheel")
        html = logged.get(reverse("garage:item-lifespan", args=[wheel.pk])).content.decode()
        assert "Orientativo para una rueda" in html and "una cubierta" not in html

    def test_editing_only_the_notes_of_an_older_category_changes_no_icon(self, owner, logged):
        # Review of garage-041: «Según el nombre» used to freeze the suggestion, so the category icon then
        # overrode the item names (a tyre got the wheel's lifespan hint).
        cat = create_inventory(owner, Category, name="Ruedas")  # pre-041: no icon
        tire = create_inventory(owner, Item, name="Cubierta GP5000", category=cat)
        lifespan = reverse("garage:item-lifespan", args=[tire.pk])
        assert "Orientativo para una cubierta: <b>unos 4.000 km</b>" in logged.get(lifespan).content.decode()
        edit = reverse("garage:category-edit", args=[cat.pk])
        html = logged.get(edit).content.decode()
        assert re.search(r'value="" aria-label="Según el nombre \(Rueda\)" checked>', html)
        assert len(re.findall(r'type="radio"[^>]* checked>', html)) == 1
        response = logged.post(edit, {"name": "Ruedas", "notes": "solo notas", "icon": ""})
        assert response.status_code == 302
        cat.refresh_from_db()
        assert (cat.notes, cat.icon) == ("solo notas", "")
        assert item_icon(Item.objects.select_related("category").get(pk=tire.pk)) == "tire"
        after = logged.get(lifespan).content.decode()
        assert "Orientativo para una cubierta: <b>unos 4.000 km</b>" in after and "una rueda" not in after
        assert re.search(r'value="" aria-label="Según el nombre \(Rueda\)" checked>', logged.get(edit).content.decode())

    def test_invalid_icon_is_a_spanish_error(self, owner, logged):
        response = logged.post(reverse("garage:category-create"), {"name": "X", "icon": "rocket"})
        html = response.content.decode()
        assert response.status_code == 200 and "Elige uno de los iconos de la lista." in html and "has-error" in html
        assert not Category.objects.exists()

    def test_older_category_keeps_by_name_checked_with_its_glyph(self, owner, logged):
        cat = create_inventory(owner, Category, name="Guantes de invierno")
        html = logged.get(reverse("garage:category-edit", args=[cat.pk])).content.decode()
        assert re.search(r'value="" aria-label="Según el nombre \(Guantes\)" checked>', html)
        assert '<use href="#i-gloves"/></svg><span>Según el nombre</span>' in html
        assert not re.search(r'value="gloves"[^>]*checked', html)
        mine = create_inventory(owner, Category, name="Guantes finos", icon="bag")
        html = logged.get(reverse("garage:category-edit", args=[mine.pk])).content.decode()
        assert re.search(r'value="bag" aria-label="Bolsa" checked>', html) and not re.search(r'value=""[^>]*checked', html)
        cat.refresh_from_db()
        assert cat.icon == ""  # showing the form never writes

    def test_new_and_edit_forms_are_told_apart_by_the_resource_id(self, owner):
        # Review of garage-041: instance.pk is set on a new category too (uuid4 default).
        new = CategoryWebForm(user=owner)
        assert new.instance.pk is not None and new.instance._state.adding and new.editing is False
        assert new.fields["icon"].widget.suggested == ""
        cat = create_inventory(owner, Category, name="Cascos")
        edit = CategoryWebForm(user=owner, instance=cat)
        assert edit.editing is True and edit.fields["icon"].widget.suggested == "helmet"
        bound = CategoryWebForm({"name": "Pastillas", "icon": ""}, user=owner)
        assert bound.editing is False and bound.fields["icon"].widget.suggested == "brake"

    def test_a_key_no_longer_offered_never_blocks_an_edit(self, owner, logged):
        cat = create_inventory(owner, Category, name="Varios")
        Category.objects.filter(pk=cat.pk).update(icon="key_from_the_future")  # e.g. removed from ICON_CHOICES
        edit = reverse("garage:category-edit", args=[cat.pk])
        html = logged.get(edit).content.decode()
        assert re.search(r'value="" aria-label="Según el nombre" checked>', html)  # a valid choice gets posted
        assert logged.post(edit, {"name": "Varios", "notes": "n", "icon": ""}).status_code == 302
        cat.refresh_from_db()
        assert (cat.notes, cat.icon) == ("n", "")
        Category.objects.filter(pk=cat.pk).update(icon="key_from_the_future")
        # Nothing checked posts nothing: that is «Según el nombre», never «keep the stored key».
        assert logged.post(edit, {"name": "Varios", "notes": "m"}).status_code == 302
        cat.refresh_from_db()
        assert (cat.notes, cat.icon) == ("m", "")

    def test_model_rejection_of_a_key_is_shown_in_spanish(self, owner, logged, monkeypatch):
        # The form still offers «tool» but the model no longer accepts it: Category.clean() decides.
        monkeypatch.setattr("garage.models.ICON_KEYS", ICON_KEYS - {"tool"})
        response = logged.post(reverse("garage:category-create"), {"name": "Pastillas", "icon": "tool"})
        html = response.content.decode()
        assert response.status_code == 200 and "Elige uno de los iconos de la lista." in html
        assert "Choose one of the listed icons." not in html and not Category.objects.exists()
        assert '<use href="#i-brake"/></svg><span>Según el nombre</span>' in html  # the posted name's glyph

    def test_editing_keeps_other_fields(self, owner, logged):
        cat = create_inventory(owner, Category, name="Luces", notes="n", icon="light")
        logged.post(reverse("garage:category-edit", args=[cat.pk]), {"name": "Luces", "notes": "n", "icon": "battery", "is_archived": "on"})
        cat.refresh_from_db()
        assert (cat.icon, cat.notes, cat.is_archived) == ("battery", "n", True)

    def test_admin_offers_the_list(self, db, django_user_model):
        admin = django_user_model.objects.create_superuser("cat-admin", password="test-only-password")
        client = Client()
        client.force_login(admin)
        html = client.get(reverse("admin:garage_category_add")).content.decode()
        assert '<option value="brake_lever">Maneta de freno</option>' in html


class TestExport:
    def test_icon_column(self, owner):
        create_inventory(owner, Category, name="Mía")
        create_inventory(owner, Category, name="Cadena", icon="chain")
        snapshot = export_snapshot(owner)
        assert {row["name"]: row["icon"] for row in snapshot["tables"]["categories"]} == {"Mía": "", "Cadena": "chain"}
        with ZipFile(io.BytesIO(csv_zip(snapshot))) as archive:
            rows = list(csv.reader(io.StringIO(archive.read("categories.csv").decode())))
            manifest = json.loads(archive.read("manifest.json"))
        assert rows[0] == ["id", "created_at", "updated_at", "name", "notes", "is_archived", "icon"]
        assert manifest["csv"]["tables"]["categories"]["columns"][-1] == "icon"
        assert {row[3]: row[6] for row in rows[1:]} == {"Mía": "", "Cadena": "chain"}


class TestReadsAndBudgets:
    def test_get_screens_never_write(self, owner, logged):
        cat = create_inventory(owner, Category, name="Guantes")
        urls = [reverse("garage:category-list"), reverse("garage:item-list"), reverse("garage:item-create"),
                reverse("garage:item-used-create"), reverse("garage:category-create"),
                reverse("garage:category-edit", args=[cat.pk]), reverse("garage:category-detail", args=[cat.pk])]
        for url in urls:
            with CaptureQueriesContext(connection) as queries:
                assert logged.get(url).status_code == 200
            assert writes(queries) == [], url
        Category.objects.filter(pk=cat.pk).delete()
        for url in urls[:4]:  # also while offering the starter set
            with CaptureQueriesContext(connection) as queries:
                logged.get(url)
            assert writes(queries) == [], url

    def _count(self, client, url):
        with CaptureQueriesContext(connection) as queries:
            assert client.get(url).status_code == 200
        return len(queries)

    def test_list_budgets_do_not_grow_with_rows(self, owner, logged):
        empty_items = self._count(logged, reverse("garage:item-list"))
        empty_categories = self._count(logged, reverse("garage:category-list"))
        cats = [create_inventory(owner, Category, name=f"Cat {n}", icon="") for n in range(3)]
        for n in range(3):
            create_inventory(owner, Item, name=f"Cadena {n}", category=cats[n])
        few = (self._count(logged, reverse("garage:category-list")), self._count(logged, reverse("garage:item-list")))
        create_starter_categories(owner)
        for n, cat in enumerate(Category.objects.filter(owner=owner)[:15]):
            create_inventory(owner, Item, name=f"Objeto {n}", category=cat)
        many = (self._count(logged, reverse("garage:category-list")), self._count(logged, reverse("garage:item-list")))
        assert many == few  # the missing count is one read whatever the number of rows
        assert max(empty_items, empty_categories, *few, *many) <= 10


def _in_thread(django_user_model, actor, work):
    close_old_connections()
    try:
        return work(django_user_model.objects.get(pk=actor.pk))
    finally:
        close_old_connections()


@pytest.mark.django_db(transaction=True)
def test_two_simultaneous_starter_clicks_create_each_category_once(django_user_model):
    actor = django_user_model.objects.create_user(username="starter-race")
    barrier = Barrier(2)

    def click(local):
        barrier.wait(timeout=10)
        result = create_starter_categories(local)
        return len(result.created), len(result.existing)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(_in_thread, django_user_model, actor, click) for _ in range(2)]
        outcomes = sorted(future.result(timeout=30) for future in futures)
    assert outcomes == [(0, 42), (42, 0)]
    assert Category.objects.filter(owner=actor).count() == len(STARTER)


@pytest.mark.django_db(transaction=True)
def test_starter_waits_for_a_manual_create_with_other_case(django_user_model):
    """«CADENA» is being created under the owner lock; the starter set waits and then counts it as existing."""
    actor = django_user_model.objects.create_user(username="starter-vs-manual")
    locked = Event()

    def manual(local):
        with transaction.atomic():
            _lock_owner(local)
            create_inventory(local, Category, name="CADENA")
            locked.set()
            # Commit only once the starter set is really blocked behind this transaction.
            deadline = time.monotonic() + 10
            with connection.cursor() as cursor:
                while time.monotonic() < deadline:
                    cursor.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                                   "AND wait_event_type = 'Lock' AND pid <> pg_backend_pid()")
                    if cursor.fetchone()[0]:
                        return "created after a waiter"
                    time.sleep(0.02)
            return "nobody waited"

    def starter(local):
        assert locked.wait(timeout=10)
        try:
            result = create_starter_categories(local)
        except CategoryNameConflict:
            return "conflict"
        return len(result.created), result.existing

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(_in_thread, django_user_model, actor, manual)
        second = executor.submit(_in_thread, django_user_model, actor, starter)
        outcomes = (first.result(timeout=30), second.result(timeout=30))
    assert outcomes == ("created after a waiter", (41, ("Cadena",)))
    names = list(Category.objects.filter(owner=actor).values_list("name", flat=True))
    assert len(names) == 42 and "CADENA" in names and "Cadena" not in names


class CategoryIconMigrationTests(TransactionTestCase):
    BEFORE = [("garage", "0010_strava_source")]
    AFTER = [("garage", "0011_category_icon")]

    @staticmethod
    def migrate(targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_existing_rows_get_an_empty_icon_and_the_check(self):
        apps = self.migrate(self.BEFORE)
        user = apps.get_model("auth", "User").objects.create(username="migration-owner")
        old = apps.get_model("garage", "Category").objects.create(owner=user, name="Cadenas", notes="antes")
        apps = self.migrate(self.AFTER)
        Category = apps.get_model("garage", "Category")
        row = Category.objects.get(pk=old.pk)
        self.assertEqual((row.name, row.notes, row.icon, row.is_archived), ("Cadenas", "antes", "", False))
        Category.objects.filter(pk=old.pk).update(icon="chain")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Category.objects.filter(pk=old.pk).update(icon="Not valid")
        apps = self.migrate(self.BEFORE)  # reversible: the column and its CHECK go away
        self.assertEqual(apps.get_model("garage", "Category").objects.get(pk=old.pk).name, "Cadenas")
