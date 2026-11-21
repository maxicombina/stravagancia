from datetime import datetime, timezone as utc_timezone
from decimal import Decimal
from types import SimpleNamespace
import uuid

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from django.utils import timezone

from .forms import ItemForm, UsageBaselineForm
from .models import Category, Item, ServiceEvent, ServiceType, UsageBaseline
from .services.baselines import record_baseline
from .services.maintenance import save_maintenance
from .services.ownership import InventoryNotFound, create_inventory
from .test_html import find_all, parse, visible_text
from .validators import MAX_USAGE_VALUE


@pytest.fixture
def inventory(db, django_user_model):
    owner = django_user_model.objects.create_user(username="reading-form-owner")
    other = django_user_model.objects.create_user(username="reading-form-other")
    category = create_inventory(owner, Category, name="Parts")
    item = create_inventory(owner, Item, name="Helmet", category=category,
                            acquisition_anchor_at=datetime(2026, 1, 1, tzinfo=utc_timezone.utc))
    foreign = create_inventory(other, Item, name="SECRET", category=create_inventory(other, Category, name="Parts"))
    return owner, other, item, foreign


def payload(item, **changes):
    return {"item": str(item.pk), "metric": "distance_m", "scope": "lifetime", "cut_at": "2026-01-02",
            "time_zone": "UTC", "value": "1000000", "source": "manual", **changes}


@pytest.mark.parametrize("zone,wall,expected", [
    ("Europe/Madrid", "2026-01-02", datetime(2026, 1, 1, 23, tzinfo=utc_timezone.utc)),
    ("Europe/Madrid", "2026-07-02", datetime(2026, 7, 1, 22, tzinfo=utc_timezone.utc)),
    ("America/New_York", "2026-01-02", datetime(2026, 1, 2, 5, tzinfo=utc_timezone.utc)),
    ("UTC", "2026-01-02", datetime(2026, 1, 2, tzinfo=utc_timezone.utc)),
])
def test_local_reading_date_means_midnight_in_explicit_zone(inventory, zone, wall, expected):
    owner, _, item, _ = inventory
    with timezone.override("Asia/Tokyo"):
        form = UsageBaselineForm(data=payload(item, time_zone=zone, cut_at=wall), user=owner)
        assert form.is_valid(), form.errors
        result = form.save()
    result.refresh_from_db()
    assert result.cut_at == expected


@pytest.mark.parametrize("zone,wall,field,code", [
    ("Europe/Madrid", "2026-03-29 02:30:00", "cut_at", "nonexistent_local_time"),
    ("Europe/Madrid", "2026-10-25 02:30:00", "cut_at", "ambiguous_local_time"),
    ("Pacific/Apia", "2011-12-30", "cut_at", "nonexistent_local_time"),
    ("Not/AZone", "2026-01-02", "time_zone", "invalid_time_zone"),
    ("", "2026-01-02", "time_zone", "required"),
    ("Europe/Madrid", "2026-01-02T00:00:00+01:00", "cut_at", "invalid_local_time"),
])
def test_reading_form_rejects_ambiguous_missing_or_implicit_zone(inventory, zone, wall, field, code):
    owner, _, item, _ = inventory
    form = UsageBaselineForm(data=payload(item, time_zone=zone, cut_at=wall), user=owner)
    assert not form.is_valid()
    assert form.errors.as_data()[field][0].code == code
    assert not UsageBaseline.objects.exists()


def test_edit_render_and_save_preserve_instant_independent_of_active_zone(inventory):
    owner, _, item, _ = inventory
    instant = datetime(2026, 1, 2, 10, tzinfo=utc_timezone.utc)
    reading = record_baseline(owner, item=item, metric="distance_m", scope="lifetime", cut_at=instant, value=Decimal("1"))
    with timezone.override("America/New_York"):
        initial = UsageBaselineForm(user=owner, instance=reading, time_zone="Europe/Madrid")
        assert 'value="2026-01-02 11:00:00"' in str(initial["cut_at"])
        form = UsageBaselineForm(data=payload(item, cut_at="2026-01-02 11:00:00", time_zone="Europe/Madrid", value="2"), user=owner, instance=reading)
        assert form.is_valid(), form.errors
        edited = form.save()
    assert edited.pk == reading.pk and edited.cut_at == instant and edited.value == Decimal("2")
    form = UsageBaselineForm(data=payload(item, cut_at="2026-01-02 11:00:00", time_zone="UTC", value="3"), user=owner, instance=edited)
    assert form.is_valid(), form.errors
    assert form.save().cut_at == datetime(2026, 1, 2, 11, tzinfo=utc_timezone.utc)


@pytest.mark.parametrize("metric,value,valid", [("moving_time_s", "1.2300", True), ("distance_m", "1.2345", False),
                                               ("ride_count", "1.250", False), ("ride_count", "0", True)])
def test_reading_form_preserves_exact_precision_and_integral_ride_counts(inventory, metric, value, valid):
    owner, _, item, _ = inventory
    form = UsageBaselineForm(data=payload(item, metric=metric, value=value), user=owner)
    assert form.is_valid() is valid, form.errors
    if valid:
        assert form.save().value == Decimal(value)
    else:
        assert "value" in form.errors and not UsageBaseline.objects.exists()


def test_reading_form_actor_scope_commit_false_and_forged_fields(inventory):
    owner, other, item, foreign = inventory
    fake = uuid.uuid4()
    form = UsageBaselineForm(data=payload(item, owner=other.pk, id=str(fake)), user=owner)
    assert form.is_valid(), form.errors
    candidate = form.save(commit=False)
    assert candidate.owner_id == owner.pk and candidate.pk != fake and not UsageBaseline.objects.exists()
    saved = form.save()
    foreign_form = UsageBaselineForm(data=payload(foreign), user=owner)
    assert not foreign_form.is_valid() and "item" in foreign_form.errors
    assert "SECRET" not in str(form["item"])
    saved.owner = other
    with pytest.raises(InventoryNotFound):
        UsageBaselineForm(user=other, instance=saved)
    with pytest.raises(PermissionDenied):
        UsageBaselineForm(user=AnonymousUser())
    owner.is_active = False
    owner.save(update_fields=["is_active"])
    with pytest.raises(PermissionDenied):
        UsageBaselineForm(user=owner)


@pytest.mark.parametrize("anchor", ["", "2026-01-03 00:00:00"])
def test_item_form_anchor_correction_cannot_invalidate_existing_reading(inventory, anchor):
    owner, _, item, _ = inventory
    reading = record_baseline(owner, item=item, metric="distance_m", scope="acquisition",
                              cut_at=datetime(2026, 1, 2, tzinfo=utc_timezone.utc), value=Decimal("0"))
    form = ItemForm(data={"name": "Forbidden edit", "category": str(item.category_id), "acquisition_anchor_at": anchor}, user=owner, instance=item)
    assert form.is_valid(), form.errors
    with pytest.raises(ValidationError):
        form.save()
    assert "acquisition_anchor_at" in form.errors
    item.refresh_from_db()
    reading.refresh_from_db()
    assert item.name == "Helmet" and item.acquisition_anchor_at == datetime(2026, 1, 1, tzinfo=utc_timezone.utc)
    assert reading.value == Decimal("0")


@pytest.mark.parametrize("scope,cut", [("acquisition", "2025-12-31"), ("acquisition", "2026-01-02")])
def test_reading_form_validates_acquisition_anchor(inventory, scope, cut):
    owner, _, item, _ = inventory
    if cut == "2026-01-02":
        item.acquisition_anchor_at = None
        item.save(update_fields=["acquisition_anchor_at"])
    form = UsageBaselineForm(data=payload(item, scope=scope, cut_at=cut), user=owner)
    assert not form.is_valid()
    assert ("scope" if cut == "2026-01-02" else "cut_at") in form.errors
    assert not UsageBaseline.objects.exists()


@pytest.mark.parametrize("zone,cut", [("Asia/Tokyo", "0001-01-01 00:00:00"), ("America/New_York", "9999-12-31 23:59:59")])
def test_extreme_civil_dates_return_form_errors_instead_of_utc_overflow(inventory, zone, cut):
    owner, _, item, _ = inventory
    form = UsageBaselineForm(data=payload(item, time_zone=zone, cut_at=cut), user=owner)
    assert not form.is_valid()
    assert form.errors.as_data()["cut_at"][0].code == "invalid_local_time"
    assert not UsageBaseline.objects.exists()


def test_duplicate_new_reading_form_requires_explicit_edit_for_correction(inventory):
    owner, _, item, _ = inventory
    first = UsageBaselineForm(data=payload(item), user=owner)
    assert first.is_valid(), first.errors
    original = first.save()
    duplicate = UsageBaselineForm(data=payload(item, value="900000"), user=owner)
    assert not duplicate.is_valid() and "__all__" in duplicate.errors
    original.refresh_from_db()
    assert original.value == Decimal("1000000") and UsageBaseline.objects.count() == 1
    correction = UsageBaselineForm(data=payload(item, value="900000"), user=owner, instance=original)
    assert correction.is_valid(), correction.errors
    saved = correction.save()
    assert saved.pk == original.pk and saved.value == Decimal("900000") and UsageBaseline.objects.count() == 1


# garage-047 F05 (D15): the reading page takes km, hours or rides. The exact metres or seconds still go through.

def reading_page(inventory, client, zone="UTC"):
    owner, _, item, _ = inventory
    client.force_login(owner)
    client.cookies["garage_tz"] = zone
    return SimpleNamespace(owner=owner, item=item, client=client, create=reverse("garage:baseline-create", args=[item.pk]))


def web_payload(**changes):
    return {"metric": "distance_m", "scope": "lifetime", "cut_at": "2026-01-02T10:00", "time_zone": "UTC", "source": "manual", **changes}


def refused(page, data, url=None):
    response = page.client.post(url or page.create, data)
    assert response.status_code in (200, 400), response
    return parse(response.content.decode())


def under(root, name):
    """The errors drawn in the `div.field` of the control `name`."""
    wrappers = [w for w in find_all(root, "div", cls="field") if find_all(w, "input", name=name) or find_all(w, "select", name=name)]
    assert len(wrappers) == 1, (name, len(wrappers))
    return [visible_text(li) for ul in find_all(wrappers[0], "ul", cls="errorlist") for li in find_all(ul, "li")]


def every_error(root):
    return [visible_text(li) for ul in find_all(root, "ul", cls="errorlist") for li in find_all(ul, "li")]


def inputs(root, name):
    return find_all(root, "input", name=name)


@pytest.mark.parametrize("metric,amount,stored", [
    ("moving_time_s", "83", Decimal("298800")),
    ("distance_m", "2.840,5", Decimal("2840500")),
    ("ride_count", "12", Decimal("12")),
    ("moving_time_s", "0,5", Decimal("1800")),
    ("distance_m", "0", Decimal("0")),  # a known zero, not «unknown»
    ("distance_m", "0,000001", Decimal("0.001")),  # one millimetre
    ("distance_m", "99.999.999.999.999,999999", MAX_USAGE_VALUE),  # the largest value a reading holds
    ("ride_count", "99999999999999999", Decimal("99999999999999999")),
])
def test_a_reading_is_written_in_km_hours_or_rides(inventory, client, metric, amount, stored):
    page = reading_page(inventory, client)
    response = page.client.post(page.create, web_payload(metric=metric, amount=amount))
    assert response.status_code == 302, every_error(parse(response.content.decode()))
    assert UsageBaseline.objects.get().value == stored


@pytest.mark.parametrize("amount", ["1,5", "0,0001"])
def test_a_fraction_of_a_ride_is_refused(inventory, client, amount):
    """Also with more decimals than a stored value holds: it is still no whole number of rides."""
    page = reading_page(inventory, client)
    root = refused(page, web_payload(metric="ride_count", amount=amount))
    assert under(root, "amount") == ["Las salidas son un número entero."] and every_error(root) == ["Las salidas son un número entero."]
    assert not UsageBaseline.objects.exists()


def test_an_inexact_time_is_refused(inventory, client):
    # 83,333333 h are 299 999,9988 s: no whole number of milliseconds.
    page = reading_page(inventory, client)
    message = "Ese tiempo no se puede guardar exacto (milisegundos): usa menos decimales."
    root = refused(page, web_payload(metric="moving_time_s", amount="83,333333"))
    assert under(root, "amount") == [message] and every_error(root) == [message]
    assert not UsageBaseline.objects.exists()


@pytest.mark.parametrize("amount", ["100.000.000.000.000,5", "100000000000000", "1000000000000000000000", "-1"])
def test_a_value_out_of_range_is_refused_once_in_spanish(inventory, client, amount):
    page = reading_page(inventory, client)
    root = refused(page, web_payload(amount=amount))
    assert every_error(root) == under(root, "amount") == ["Escribe un valor positivo o cero, dentro del máximo admitido."]
    assert not UsageBaseline.objects.exists()


def test_an_empty_value_is_asked_for_once(inventory, client):
    """Empty is no reading at all: one Spanish message, and the model's check of the missing value is not added to it."""
    page = reading_page(inventory, client)
    root = refused(page, web_payload(amount=""))
    assert every_error(root) == under(root, "amount") == ["Este campo es obligatorio."]
    assert not UsageBaseline.objects.exists()


def test_without_a_metric_the_value_is_not_blamed(inventory, client):
    """Without a metric the value has no unit: only the metric is wrong."""
    page = reading_page(inventory, client)
    root = refused(page, web_payload(metric="", amount="83"))
    assert under(root, "metric") == ["Este campo es obligatorio."] and under(root, "amount") == []
    assert every_error(root) == ["Este campo es obligatorio."]
    assert not UsageBaseline.objects.exists()


def test_the_value_says_its_units(inventory, client):
    page = reading_page(inventory, client)
    root = parse(page.client.get(page.create).content.decode())
    assert len(inputs(root, "amount")) == 1 and not inputs(root, "value")
    wrapper = [w for w in find_all(root, "div", cls="field") if inputs(w, "amount")][0]
    assert [visible_text(label) for label in find_all(wrapper, "label")] == ["Valor"]
    assert visible_text(find_all(wrapper, "div", cls="help")[0]) == ("En km, horas o salidas, según la métrica. Con coma decimal: 83,5. "
                                                                    "Cero es una lectura conocida.")
    metrics = [visible_text(option) for select in find_all(root, "select", name="metric") for option in find_all(select, "option")
               if option.attrs.get("value")]
    assert metrics == ["Distancia (km)", "Tiempo en movimiento (horas)", "Salidas"]


@pytest.mark.parametrize("value", ["12.345", "0", "1.5"])
def test_the_exact_value_is_still_accepted(inventory, client, value):
    """Guard: a page opened before km and hours posts `value`, in metres or seconds, and it is saved as it was sent."""
    page = reading_page(inventory, client)
    response = page.client.post(page.create, web_payload(metric="moving_time_s", value=value))
    assert response.status_code == 302
    assert UsageBaseline.objects.get().value == Decimal(value)


def test_with_both_the_value_written_in_km_wins(inventory, client):
    """Only a forged post sends both: the page shows one of them, and `value` alone is the page opened before."""
    page = reading_page(inventory, client)
    assert page.client.post(page.create, web_payload(amount="2,5", value="7")).status_code == 302
    assert UsageBaseline.objects.get().value == Decimal("2500")


@pytest.mark.parametrize("metric,stored,shown", [
    ("distance_m", Decimal("2840500"), "2840,5"),
    ("moving_time_s", Decimal("298800"), "83"),
    ("ride_count", Decimal("12"), "12"),
    ("distance_m", Decimal("0"), "0"),
    ("distance_m", Decimal("0.001"), "0,000001"),
    ("moving_time_s", Decimal("1.8"), "0,0005"),
])
def test_correcting_shows_km_or_hours_when_exact(inventory, client, metric, stored, shown):
    page = reading_page(inventory, client)
    reading = record_baseline(page.owner, item=page.item, metric=metric, scope="lifetime",
                              cut_at=datetime(2026, 1, 2, 10, tzinfo=utc_timezone.utc), value=stored)
    edit = reverse("garage:baseline-edit", args=[reading.pk])
    root = parse(page.client.get(edit).content.decode())
    assert [field.attrs.get("value") for field in inputs(root, "amount")] == [shown] and not inputs(root, "value")
    # Sending the page back unchanged keeps the reading exactly as it was.
    response = page.client.post(edit, web_payload(metric=metric, amount=shown))
    assert response.status_code == 302, every_error(parse(response.content.decode()))
    reading.refresh_from_db()
    assert reading.value == stored and UsageBaseline.objects.count() == 1


@pytest.mark.parametrize("stored", [Decimal("1000"), Decimal("1.001")])
def test_correcting_an_inexact_value_keeps_the_exact_field(inventory, client, stored):
    """1000 s are 0,2777… h: no km or hours field could hold them, so the exact seconds are shown, and kept."""
    page = reading_page(inventory, client)
    reading = record_baseline(page.owner, item=page.item, metric="moving_time_s", scope="lifetime",
                              cut_at=datetime(2026, 1, 2, 10, tzinfo=utc_timezone.utc), value=stored)
    edit = reverse("garage:baseline-edit", args=[reading.pk])
    root = parse(page.client.get(edit).content.decode())
    assert not inputs(root, "amount")
    [field] = inputs(root, "value")
    assert Decimal(field.attrs["value"]) == stored
    wrapper = [w for w in find_all(root, "div", cls="field") if inputs(w, "value")][0]
    assert [visible_text(label) for label in find_all(wrapper, "label")] == ["Valor exacto (metros o segundos)"]
    response = page.client.post(edit, web_payload(metric="moving_time_s", value=field.attrs["value"], notes="Revisada"))
    assert response.status_code == 302
    reading.refresh_from_db()
    assert reading.value == stored and reading.notes == "Revisada"


def metric_options(root):
    return [visible_text(option) for select in find_all(root, "select", name="metric") for option in find_all(select, "option")
            if option.attrs.get("value")]


def _edit_page(page, metric, stored):
    reading = record_baseline(page.owner, item=page.item, metric=metric, scope="lifetime",
                              cut_at=datetime(2026, 1, 2, 10, tzinfo=utc_timezone.utc), value=stored)
    return parse(page.client.get(reverse("garage:baseline-edit", args=[reading.pk])).content.decode())


IN_KM_OR_HOURS = ["Distancia (km)", "Tiempo en movimiento (horas)", "Salidas"]
EXACT = ["Distancia", "Tiempo en movimiento", "Salidas"]  # the field shown says «metros o segundos»
PAGES = {
    "new": lambda page: parse(page.client.get(page.create).content.decode()),
    "new, refused": lambda page: refused(page, web_payload(metric="moving_time_s", amount="83,333333")),
    "correcting exact hours": lambda page: _edit_page(page, "moving_time_s", Decimal("298800")),
    # Whole seconds, as an import writes them, seldom are exact hours: 1 234 567 s are 342,935277… h.
    "correcting whole seconds": lambda page: _edit_page(page, "moving_time_s", Decimal("1234567")),
    "correcting 1000 s": lambda page: _edit_page(page, "moving_time_s", Decimal("1000")),
    "opened before, refused": lambda page: refused(page, web_payload(metric="moving_time_s", value="1000", cut_at="")),
}


@pytest.mark.parametrize("shown,field,metrics", [
    ("new", "amount", IN_KM_OR_HOURS), ("new, refused", "amount", IN_KM_OR_HOURS),
    ("correcting exact hours", "amount", IN_KM_OR_HOURS), ("correcting whole seconds", "value", EXACT),
    ("correcting 1000 s", "value", EXACT), ("opened before, refused", "value", EXACT),
])
def test_the_metric_never_names_a_unit_the_field_shown_does_not_take(inventory, client, shown, field, metrics):
    """Over the exact field, a metric that said «(horas)» would have 340 typed for 340 h, and 340 s saved without a word."""
    page = reading_page(inventory, client)
    root = PAGES[shown](page)
    assert len(inputs(root, field)) == 1 and not inputs(root, "value" if field == "amount" else "amount")
    assert metric_options(root) == metrics


def test_intervention_options_show_the_local_date(inventory, client):
    page = reading_page(inventory, client, zone="Europe/Madrid")
    kind = save_maintenance(page.owner, ServiceType, name="Lubricación")
    save_maintenance(page.owner, ServiceEvent, item=page.item, service_type=kind, performed_at=datetime(2026, 2, 1, 10, tzinfo=utc_timezone.utc))
    save_maintenance(page.owner, ServiceEvent, item=page.item, service_type=kind, performed_at=datetime(2026, 7, 1, 10, 0, 30, tzinfo=utc_timezone.utc))
    html = page.client.get(page.create).content.decode()
    root = parse(html)
    [select] = find_all(root, "select", name="service_event")
    assert [visible_text(option) for option in find_all(select, "option")] == [
        "—", "Lubricación · 1 jul 2026, 12:00:30", "Lubricación · 1 feb 2026, 11:00"]  # newest first, in the viewer's zone
    assert "+00:00" not in html
    wrapper = [w for w in find_all(root, "div", cls="field") if find_all(w, "select", name="service_event")][0]
    assert [visible_text(label) for label in find_all(wrapper, "label")] == ["Intervención"]
    assert visible_text(find_all(wrapper, "div", cls="help")[0]) == "Sólo para «Desde una intervención concreta»."


def test_two_interventions_that_would_read_the_same_are_told_apart(inventory, client):
    page = reading_page(inventory, client)
    kind = save_maintenance(page.owner, ServiceType, name="Lubricación")
    when = datetime(2026, 2, 1, 10, tzinfo=utc_timezone.utc)
    for _ in range(2):
        save_maintenance(page.owner, ServiceEvent, item=page.item, service_type=kind, performed_at=when)
    [select] = find_all(parse(page.client.get(page.create).content.decode()), "select", name="service_event")
    assert [visible_text(option) for option in find_all(select, "option")][1:] == [
        "Lubricación · 1 feb 2026, 10:00", "Lubricación · 1 feb 2026, 10:00 (2)"]


@pytest.mark.parametrize("viewer,sent,shown", [
    ("Europe/Madrid", "UTC", "Lubricación · 1 feb 2026, 10:00"),  # west of the viewer's zone
    ("America/New_York", "Asia/Tokyo", "Lubricación · 1 feb 2026, 19:00"),  # east of it
    ("Europe/Madrid", "Marte/Olimpo", "Lubricación · 1 feb 2026, 11:00"),  # no zone at all: the viewer's hours
    ("Europe/Madrid", " UTC ", "Lubricación · 1 feb 2026, 10:00"),  # a phone keyboard's space: still UTC, as for the instant
])
def test_a_refused_page_names_the_interventions_in_the_zone_it_was_sent_with(inventory, client, viewer, sent, shown):
    """The options read in the hours of «Horas en …», those the instant is typed in, as Retirar does (garage-047 B8)."""
    page = reading_page(inventory, client, zone=viewer)
    kind = save_maintenance(page.owner, ServiceType, name="Lubricación")
    save_maintenance(page.owner, ServiceEvent, item=page.item, service_type=kind, performed_at=datetime(2026, 2, 1, 10, tzinfo=utc_timezone.utc))
    root = refused(page, web_payload(metric="moving_time_s", amount="", time_zone=sent))
    [select] = find_all(root, "select", name="service_event")
    assert [visible_text(option) for option in find_all(select, "option")][1:] == [shown]
    assert [visible_text(summary) for summary in find_all(root, "summary")] == [f"Horas en {sent.strip()} · Cambiar"]


def test_the_hour_an_option_reads_is_the_one_to_type_in_that_zone(inventory, client):
    """A viewer in New York sends the page in Tokyo's hours: the option says 19:00, a minute before it is refused, 19:00 is kept."""
    page = reading_page(inventory, client, zone="America/New_York")
    kind = save_maintenance(page.owner, ServiceType, name="Lubricación")
    event = save_maintenance(page.owner, ServiceEvent, item=page.item, service_type=kind,
                             performed_at=datetime(2026, 2, 1, 10, tzinfo=utc_timezone.utc))
    reading = web_payload(metric="moving_time_s", amount="83", scope="service", service_event=str(event.pk), time_zone="Asia/Tokyo")
    root = refused(page, {**reading, "cut_at": "2026-02-01T18:59"})
    assert every_error(root) == ["La lectura no puede ser anterior a la intervención."]
    [select] = find_all(root, "select", name="service_event")
    assert [visible_text(option) for option in find_all(select, "option") if "selected" in option.attrs] == [
        "Lubricación · 1 feb 2026, 19:00"]
    assert page.client.post(page.create, {**reading, "cut_at": "2026-02-01T19:00"}).status_code == 302
    assert UsageBaseline.objects.get().cut_at == event.performed_at


def test_the_conversion_is_exact_under_a_small_decimal_context(inventory):
    """A caller's decimal context with few digits would round 2 840 123,456 m: the form keeps its own."""
    from decimal import localcontext
    from .web_forms import BaselineWebForm
    owner, _, item, _ = inventory
    with localcontext() as context:
        context.prec = 6
        form = BaselineWebForm(data=web_payload(amount="2840,123456"), user=owner, item=item)
        assert form.is_valid(), form.errors
    assert form.cleaned_data["value"] == Decimal("2840123.456")


def test_more_interventions_do_not_cost_more_queries(inventory, client):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    page = reading_page(inventory, client)
    kind = save_maintenance(page.owner, ServiceType, name="Lubricación")

    def queries():
        with CaptureQueriesContext(connection) as captured:
            assert page.client.get(page.create).status_code == 200
        return len(captured)
    save_maintenance(page.owner, ServiceEvent, item=page.item, service_type=kind, performed_at=datetime(2026, 2, 1, tzinfo=utc_timezone.utc))
    one = queries()
    for day in range(2, 6):
        save_maintenance(page.owner, ServiceEvent, item=page.item, service_type=kind, performed_at=datetime(2026, 2, day, tzinfo=utc_timezone.utc))
    assert queries() == one
