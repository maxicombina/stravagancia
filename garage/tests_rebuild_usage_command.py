from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.exceptions import PermissionDenied

from .models import ItemUsage
from .tests_usage_materialization import instant, profile, ride, usage


@pytest.mark.django_db
def test_cli_dry_run_and_apply_rebuild_preexisting_facts_for_explicit_owner(usage):
    profile(usage)
    own = ride(usage)
    ItemUsage.objects.filter(ride=own).delete()
    output = StringIO()
    call_command("rebuild_usage", owner=usage.owner.pk, started_from="2026-01-04T00:00:00Z", started_to="2026-01-06T00:00:00+00:00", dry_run=True, stdout=output)
    assert "dry-run: rides=1 created=1" in output.getvalue() and not ItemUsage.objects.exists()
    output = StringIO()
    call_command("rebuild_usage", owner=usage.owner.pk, stdout=output)
    assert "rebuilt: rides=1 created=1" in output.getvalue() and ItemUsage.objects.get().ride_id == own.pk
    output = StringIO()
    call_command("rebuild_usage", owner=usage.owner.pk, stdout=output)
    assert "created=0 updated=0 deleted=0 unchanged=1" in output.getvalue()


@pytest.mark.parametrize("dates", [{"started_from": "2026-01-04"}, {"started_to": "not-a-date"},
                                    {"started_from": "2026-01-06T00:00:00Z", "started_to": "2026-01-05T00:00:00Z"}])
@pytest.mark.django_db
def test_cli_rejects_naive_malformed_and_reversed_intervals(dates, usage):
    with pytest.raises(CommandError):
        call_command("rebuild_usage", owner=usage.owner.pk, **dates)


@pytest.mark.django_db
def test_cli_requires_explicit_existing_active_owner(usage, django_user_model):
    with pytest.raises(CommandError):
        call_command("rebuild_usage")
    with pytest.raises(CommandError):
        call_command("rebuild_usage", owner=999999)
    django_user_model.objects.filter(pk=usage.owner.pk).update(is_active=False)
    with pytest.raises(CommandError):
        call_command("rebuild_usage", owner=usage.owner.pk)


@pytest.mark.django_db
def test_cli_catches_actor_deactivation_race_without_hiding_unexpected_errors(monkeypatch, usage):
    from .management.commands import rebuild_usage as command
    def denied(*args, **kwargs):
        raise PermissionDenied("inactive")
    monkeypatch.setattr(command, "rebuild_usage", denied)
    with pytest.raises(CommandError):
        call_command("rebuild_usage", owner=usage.owner.pk)
    def unexpected(*args, **kwargs):
        raise RuntimeError("synthetic unexpected bug")
    monkeypatch.setattr(command, "rebuild_usage", unexpected)
    with pytest.raises(RuntimeError):
        call_command("rebuild_usage", owner=usage.owner.pk)
