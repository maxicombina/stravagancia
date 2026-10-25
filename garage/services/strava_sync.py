"""Token-mode account, «Sincronizar ahora», resumable history and webhook hints (garage-030).

Token mode: GARAGE_STRAVA_USER names the Garage user that owns Stravagancia's
athlete; StravaAccount(mode='env') is created on the first manual sync or
import from GET /athlete and stores no token. Strava is only called when the
person presses «Sincronizar ahora» / «Importar» or a webhook hint is processed;
network calls (token renewal included) never run inside a transaction nor
while the owner lock is held. Every page or event is written under the owner
lock with a single usage reconstruction.

Bounded work per web request (gunicorn --timeout 60, Render→Neon): pages of
strava_client.PER_PAGE (50) activities, each page committed with its
checkpoint; no new Strava call starts after REQUEST_SECONDS and its connect
and read timeouts together are cut to what is left of RESPONSE_SECONDS
(garage-030 phase 3). requests has no total timeout, so DNS, a trickling body
or the token renewal can still add some seconds: about 30 s, not a hard limit
(gunicorn's 60 s is). What is left stays for the next press, the history job
or the webhook worker.

Webhook events are hints, never orders: they are persisted before Strava gets
its 200, then confirmed through the API (a delete only withdraws on 404; in
token mode activity:read_all is assumed because Stravagancia's token has it).
At most one worker per athlete runs in a process; each hint is claimed (an
attempt counted and committed) before its Strava call, which runs with no
transaction open, and is then written with the owner lock first and the event
row second, the same order as «Quitar lo sincronizado». Two processes may
confirm the same hint twice: harmless, every write is an idempotent snapshot
under the owner lock.

Daily operation (garage-030 phase 4): `sync_all` is what POST
/garage/strava/sync-all/ (the Cloudflare Worker, X-Sync-Token) and `manage.py
garage_strava_sync` run. Per account it does exactly what the button does
(`_sync_owner`), absence hints included, and from the 30th day (Madrid) after
Strava started rejecting the token, when Strava still rejects it in that very
run, it purges the account's Strava data as «Quitar lo sincronizado» does (API
Policy §7.4). Each call is bounded like one press; the Worker repeats it while
`pending` is not 0, never after a stop code.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone as datetime_timezone
import logging
import threading
import time
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models import DateTimeField, Exists, F, OuterRef, Value
from django.db.models.functions import Coalesce, Least
from django.utils import timezone

from garage.models import STRAVA_ERROR_CODES, ActivitySource, ImportRun, Ride, StravaAccount, StravaEvent
from garage.ride_values import aware_instant
from .ownership import _lock_owner, get_inventory, require_actor
from .rides import advance_import_run, create_import_run
from . import strava_client
from .strava_client import StravaClient, StravaError
from .strava_sources import StravaBatch, discard_source, parse_for, rebuild_rides_locked, refresh_gear, remove_strava_data

logger = logging.getLogger(__name__)

# Assumed for Stravagancia's manual token: without activity:read_all a ride made private looks deleted (absence
# hints, webhook deletes). Checked by hand before deploying (docs/garage-handoff.md, «Despliegue (garage-023)»).
ENV_SCOPES = "read,activity:read_all"
SYNC_DAYS = 7
SYNC_MAX_PAGES = 2       # pages of PER_PAGE: up to 100 activities in 7 days
SYNC_EVENTS = 10         # hints confirmed by one «Sincronizar ahora»
# At most 1 renewal + GET /athlete + SYNC_MAX_PAGES + SYNC_EVENTS = 14 Strava requests per
# «Sincronizar ahora» (a 401 adds one renewal and one repeat of that request).
SYNC_MAX_CALLS = 2 + SYNC_MAX_PAGES + SYNC_EVENTS
EVENT_BATCH = 50         # hints per webhook worker round
WORKER_ROUNDS = 3        # rounds of one worker while new hints keep arriving
PENDING_CAP = 500
MAX_ATTEMPTS = 5         # a hint failing for a non-recoverable reason is settled after this many attempts
EVENT_RETENTION = timedelta(days=30)
MAX_BUDGET = 5
STEP_BUDGET = 4          # history pages per «Importar» / «Continuar importación» press
REQUEST_SECONDS = 25     # no new Strava call starts after this
RESPONSE_SECONDS = 30    # and calls are cut to end by this (connect + read): about 30 s a press, not 14 × 25 s
STOP_CODES = ("rate_limited", "unauthorized", "network")
RUN_CODES = {"rate_limited": "rate_limited", "unauthorized": "unauthorized"}
TRANSIENT_RUN_CODES = frozenset(("rate_limited", "unauthorized", "unexpected_failure"))
UPDATE_KEYS = ("type", "sport_type", "private", "visibility", "authorized")
ABSENCE_HINTS = 20       # absence hints one run may create (phase 4); they count in `pending`
REVOKED_PURGE_DAYS = 30  # API Policy §7.4: Strava data of an account whose token Strava rejects this long is purged
# The Worker's daily run is at 09:05 in this zone: the purge day is a local date there, the one Más → Strava shows.
DAILY_SYNC_ZONE = ZoneInfo("Europe/Madrid")


def _fail(code, message):
    raise ValidationError(message, code=code)


class AccountGone(Exception):
    """A run that may not create the account (the daily one) found it removed by «Quitar lo sincronizado»."""


def purge_date(revoked_at):
    """The local day (DAILY_SYNC_ZONE) from which the daily run purges an account Strava rejects since `revoked_at`.

    The 30th day after the revocation's own local day: the daily run of that
    day (09:05 Madrid) purges, never a day later than the date shown, whatever
    the hour of the revocation or a summer-time change in between.
    """
    return timezone.localtime(revoked_at, DAILY_SYNC_ZONE).date() + timedelta(days=REVOKED_PURGE_DAYS)


def purge_due(revoked_at, now):
    return revoked_at is not None and timezone.localtime(now, DAILY_SYNC_ZONE).date() >= purge_date(revoked_at)


class _Deadline:
    """`passed()`: no new call should start; `left()`: seconds a call may still take (the client cuts its timeout)."""

    def __init__(self, seconds, limit=None):
        now = time.monotonic()
        self.end = now + seconds
        self.limit = now + (RESPONSE_SECONDS if limit is None else limit)

    def passed(self):
        return time.monotonic() >= self.end

    def left(self):
        return self.limit - time.monotonic()


def configured_owner():
    username = (getattr(settings, "GARAGE_STRAVA_USER", "") or "").strip()
    if not username:
        return None
    return get_user_model().objects.filter(username=username, is_active=True).first()


@dataclass(frozen=True)
class StravaStatus:
    configured: bool
    is_owner: bool
    account: StravaAccount | None


def strava_status(actor):
    """Read-only state for Más → Strava; never calls Strava."""
    owner = require_actor(actor)
    configured = configured_owner()
    is_owner = configured is not None and configured.pk == owner.pk
    account = StravaAccount.objects.filter(owner_id=owner.pk).first()
    return StravaStatus(configured is not None, is_owner, account)


def _athlete_name(athlete):
    parts = [athlete.get(key) for key in ("firstname", "lastname")]
    return " ".join(part.strip() for part in parts if isinstance(part, str) and part.strip())[:150]


def ensure_account(actor, client, *, create=True):
    """The configured owner's StravaAccount, created from GET /athlete on first use (AccountGone when not `create`)."""
    owner = require_actor(actor)
    configured = configured_owner()
    if configured is None or configured.pk != owner.pk:
        raise StravaError("not_configured")
    account = StravaAccount.objects.filter(owner_id=owner.pk).first()
    if account is not None:
        return account, None
    if not create:
        raise AccountGone
    athlete = client.athlete()
    athlete_id = athlete.get("id")
    if type(athlete_id) is not int or athlete_id <= 0:
        raise StravaError("invalid_response")
    with transaction.atomic():
        owner = _lock_owner(owner)
        account = StravaAccount.objects.filter(owner_id=owner.pk).first()
        if account is not None:
            return account, athlete
        if StravaAccount.objects.filter(athlete_id=athlete_id).exists():
            raise StravaError("athlete_taken")
        account = StravaAccount(owner=owner, athlete_id=athlete_id, athlete_name=_athlete_name(athlete),
                                mode=StravaAccount.Mode.ENV, scopes=ENV_SCOPES, connected_at=timezone.now())
        account.full_clean()
        account.save(force_insert=True)
        touched = set()
        refresh_gear(owner, athlete.get("bikes"), touched)
        rebuild_rides_locked(owner, touched)
    return account, athlete


def _record(account, *, status, error="", revoked=None):
    """Last sync summary on the account row (codes only). A missing configuration is not the account's error.

    revoked (the end of an owner's sync, phase 4): True when Strava rejected the token itself (the renewal, or
    a 401 after one renewal before GET /athlete answered) marks the account revoked once, its date never moving
    while it lasts; False (a successful end) clears it; None leaves it as it is: a network failure, a 429 or a
    later 401/403 proves nothing about the token.
    """
    if account is None or error == "not_configured":
        return
    now = timezone.now()
    values = {"last_sync_at": now, "last_sync_status": status, "updated_at": now,
              "last_error_code": error if error in STRAVA_ERROR_CODES else "unexpected_failure"}
    if revoked is not None:
        values["revoked_at"] = Coalesce(F("revoked_at"), Value(now, output_field=DateTimeField())) if revoked else None
    StravaAccount.objects.filter(pk=account.pk).update(**values)


@dataclass
class PageResult:
    imported: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    invalid: int = 0
    ids: set = field(default_factory=set)

    @property
    def stored(self):
        return self.imported + self.updated + self.unchanged


def _store_rows(owner, account, rows, *, run=None, require_athlete=False):
    """Owner lock held: one batch context, each activity in its own savepoint, one reconstruction at the end."""
    result, touched, observations = PageResult(), set(), []
    for data in rows:
        try:
            observations.append(parse_for(account, data, require_athlete=require_athlete))
        except ValueError as error:
            # A fixed code from the parser (athlete, id, start, payload…): never the payload itself.
            logger.warning("Garage Strava activity skipped: %s.", error.args[0] if error.args else "invalid")
            result.invalid += 1
    batch = StravaBatch(owner, account, observations, import_run=run)
    for observation in observations:
        try:
            with transaction.atomic():
                outcome = batch.store(observation, touched)
        except (ValueError, ValidationError, IntegrityError):
            result.invalid += 1
            batch.reload()  # the savepoint rolled this activity back: forget what it cached
            continue
        result.ids.add(observation.activity_id)
        if outcome.kind == "imported":
            result.imported += 1
        elif outcome.kind == "updated":
            result.updated += 1
        elif outcome.kind == "unchanged":
            result.unchanged += 1
        else:
            result.skipped += 1
    rebuild_rides_locked(owner, touched)
    return result


@dataclass(frozen=True)
class SyncResult:
    imported: int
    updated: int
    skipped: int
    events: int
    error: str = ""
    pending: int = 0      # hints still waiting (the next press or the webhook worker confirms them)
    complete: bool = True  # False when the time limit left pages unread
    status: str = "ok"    # ok, partial (unusable activities), failed, or idle (daily run: the account was removed)
    absences: int = 0     # absence hints this run created (phase 4)
    rejected: bool = False  # Strava rejected the token itself (renewal or GET /athlete): the account is revoked


def _epoch(instant):
    return int(aware_instant(instant).timestamp())


def _after_window(owner, account, seen_ids, window_start, complete):
    """A known Strava source of the week that the complete list did not name becomes a deletion hint (phase 4).

    Only after a week read complete and error-free (`complete`), and only with
    activity:read_all (assumed in token mode): without it a private activity is
    missing from the list too and its GET answers 404. Active sources (not
    withdrawn by hand) observed to start after the window's `after` that are not
    in `seen_ids` get a synthetic StravaEvent delete with updates={"origin":
    "absence"}, which the same path as a webhook delete confirms. One that
    already has a pending delete hint gets no other; at most ABSENCE_HINTS per
    run and the PENDING_CAP. Written under the owner lock, then the event rows.
    Returns how many hints were created.
    """
    if not complete or not account.can_confirm_deletes:
        return 0
    after = datetime.fromtimestamp(_epoch(window_start), tz=datetime_timezone.utc)  # exactly what Strava was asked
    waiting = StravaEvent.objects.filter(athlete_id=account.athlete_id, object_type="activity", aspect_type="delete",
                                         object_id=OuterRef("external_id"), processed_at__isnull=True)
    created = 0
    with transaction.atomic():
        locked = _lock_owner(owner)
        if not _account_alive(locked, account):
            return 0
        room = min(ABSENCE_HINTS, PENDING_CAP - _pending(account.athlete_id))
        if room <= 0:
            logger.warning("Garage Strava hints over the pending cap; absence not checked.")
            return 0
        absent = list(ActivitySource.objects.filter(owner_id=locked.pk, source_kind="strava", withdrawn_at__isnull=True,
                                                    external_id__isnull=False, started_at__gt=after)
                      .exclude(external_id__in=list(seen_ids)).exclude(Exists(waiting))
                      .order_by("started_at", "external_id").values_list("external_id", flat=True)[:room])
        for activity_id in absent:
            try:
                with transaction.atomic():
                    StravaEvent.objects.create(subscription_id=0, athlete_id=account.athlete_id, object_type="activity",
                                               aspect_type="delete", object_id=activity_id, event_time=after,
                                               updates={"origin": "absence"})
            except IntegrityError:
                continue  # the same hint of this very window already exists
            created += 1
    return created


def purge_events(now=None):
    return StravaEvent.objects.filter(received_at__lt=(now or timezone.now()) - EVENT_RETENTION).delete()[0]


def _pending(athlete_id):
    return StravaEvent.objects.filter(athlete_id=athlete_id, processed_at__isnull=True).count()


def sync_now(actor):
    """«Sincronizar ahora»: the bounded work of `_sync_owner` for the person who pressed it (never the 30-day purge)."""
    return _sync_owner(require_actor(actor))


def _still_there(locked, account, create):
    """Under the owner lock: a run that may not create the account (create=False) never writes for a removed one."""
    if not create and not StravaAccount.objects.filter(pk=account.pk, owner_id=locked.pk).exists():
        raise AccountGone
    return locked


def _sync_owner(owner, *, create=True):
    """Name and gear, the last 7 days, absence hints and some pending hints of one owner (button and sync_all).

    At most SYNC_MAX_CALLS (14) Strava requests, none started after
    REQUEST_SECONDS and each with its timeouts cut to end by RESPONSE_SECONDS
    (about 30 s in all, see strava_client): a page cut by that limit
    stays for the next press (complete=False) and a hint stays pending, never an
    error. A stop code from the hints (429, 401, network) fails the sync like one
    from the pages. Revocation (phase 4): only Strava rejecting the token itself
    (the renewal, or GET /athlete after one renewal: `rejected`) marks the account
    revoked, once; as soon as GET /athlete answers the mark goes, and a later
    401/403 (one hint, a missing scope) fails the run without marking it. Any
    other failure (network, 429) leaves the mark as it was.

    create=False (sync_all): the account is never created, and the run writes
    nothing for one removed meanwhile by «Quitar lo sincronizado» (rechecked
    under the owner lock before each write): it then ends as `idle`.
    """
    deadline = _Deadline(REQUEST_SECONDS)
    client = StravaClient(deadline=deadline)
    account = StravaAccount.objects.filter(owner_id=owner.pk).first()
    total = PageResult()
    events = EventsResult()
    complete = True
    absences = 0
    accepted = False  # GET /athlete answered: Strava accepts the token in this run
    try:
        account, athlete = ensure_account(owner, client, create=create)
        athlete = athlete or client.athlete()
        accepted = True
        with transaction.atomic():
            locked = _still_there(_lock_owner(owner), account, create)
            touched = set()
            changes = {}
            name = _athlete_name(athlete)
            if name and name != account.athlete_name:
                changes["athlete_name"] = name
            if account.revoked_at is not None:
                changes["revoked_at"] = None  # Strava accepted the token again: the webhook and the hints resume now
            if changes:
                StravaAccount.objects.filter(pk=account.pk).update(**changes, updated_at=timezone.now())
            refresh_gear(locked, athlete.get("bikes"), touched)
            rebuild_rides_locked(locked, touched)
        window = timezone.now() - timedelta(days=SYNC_DAYS)
        for page in range(1, SYNC_MAX_PAGES + 1):
            if page > 1 and deadline.passed():
                complete = False
                break
            try:
                rows = client.activities(after=_epoch(window), page=page)
            except StravaError as error:
                if error.code != "deadline":
                    raise
                complete = False  # out of time: the rest of the week is for the next press
                break
            with transaction.atomic():
                result = _store_rows(_still_there(_lock_owner(owner), account, create), account, rows)
            for name in ("imported", "updated", "unchanged", "skipped", "invalid"):
                setattr(total, name, getattr(total, name) + getattr(result, name))
            total.ids |= result.ids
            if len(rows) < strava_client.PER_PAGE:
                break
        else:
            complete = False  # a full last page: older activities of the week may remain
        # An unusable activity may be the «absent» one: no absence hints from that week.
        absences = _after_window(owner, account, total.ids, window, complete and not total.invalid)
        events = process_pending_events(account.athlete_id, limit=SYNC_EVENTS, client=client, deadline=deadline)
        if events.error:
            raise StravaError(events.error)
        # A batch cut by the time limit leaves its hints pending: `pending` tells, the week itself was read.
        purge_events()
    except AccountGone:
        # Removed by hand meanwhile (daily run only): nothing was written for it, nothing is recorded.
        return SyncResult(total.imported, total.updated + total.unchanged, total.skipped + total.invalid, events.settled,
                          complete=complete, status="idle")
    except StravaError as error:
        # Only the very first calls can run out of time here (a slow token renewal): Strava did not answer in time.
        code = "network" if error.code == "deadline" else error.code
        rejected = code == "unauthorized" and not accepted
        _record(account, status="failed", error=code, revoked=True if rejected else None)
        return SyncResult(total.imported, total.updated + total.unchanged, total.skipped + total.invalid, events.settled, code,
                          _pending(account.athlete_id) if account else 0, complete, "failed", absences, rejected)
    status = "ok" if not total.invalid else "partial"
    _record(account, status=status, revoked=False)
    return SyncResult(total.imported, total.updated + total.unchanged, total.skipped + total.invalid, events.settled,
                      pending=_pending(account.athlete_id), complete=complete, status=status, absences=absences)


@dataclass(frozen=True)
class SyncAllResult:
    accounts: int = 0     # accounts synced or purged
    pending: int = 0      # hints still pending, plus 1 per account whose week was left incomplete
    status: str = "idle"  # idle (no configured owner or no account), ok, partial or failed
    error: str = ""       # the stop code that ended the run (rate_limited, unauthorized, network…)
    purged: int = 0       # accounts purged 30 days after their revocation
    absences: int = 0     # absence hints created

    def as_json(self):
        return {"pending": self.pending, "status": self.status, "error": self.error, "accounts": self.accounts,
                "purged": self.purged, "absences": self.absences}


def _purge_revoked(account, now):
    """«Quitar lo sincronizado» for an account revoked since before its purge date, rechecked under the owner lock."""
    with transaction.atomic():
        owner = _lock_owner(account.owner)
        revoked_at = (StravaAccount.objects.filter(pk=account.pk, owner_id=owner.pk, revoked_at__isnull=False)
                      .values_list("revoked_at", flat=True).first())
        if not purge_due(revoked_at, now):
            return None  # not yet, Strava accepted the token again meanwhile, or the account is gone
        return remove_strava_data(owner)


def sync_all(now=None):
    """The daily run: old hints purged, then every active account (token mode: the configured owner's, if any).

    Every account gets exactly the button's bounded work (`_sync_owner`, never
    creating nor re-filling an account removed meanwhile). When Strava rejects
    the token itself in that run (`rejected`) and the account is revoked since
    before its purge date (`purge_due`, Madrid days), it is then purged like
    «Quitar lo sincronizado»: a token that works again, a network failure or a
    429 never purges. A stop code ends the run (failed, `error`) and leaves the
    pending hints as they are: nothing is retried within the same call. One
    INFO line with counters and codes, never a token or a name.
    """
    now = now or timezone.now()
    old_events = purge_events(now)
    owner = configured_owner()
    accounts = [] if owner is None else list(
        StravaAccount.objects.filter(owner_id=owner.pk, mode=StravaAccount.Mode.ENV).select_related("owner").order_by("pk"))
    handled = pending = purged = absences = 0
    status, error = "idle", ""
    for account in accounts:  # one at most in token mode; a loop for garage-040
        result = _sync_owner(account.owner, create=False)
        if result.status == "idle":
            continue  # removed by «Quitar lo sincronizado» meanwhile: neither synced nor re-created
        handled += 1
        if result.rejected and _purge_revoked(account, now):
            purged += 1
            status = "partial" if status == "partial" else "ok"
            continue
        pending += result.pending + (0 if result.complete else 1)  # an incomplete week: the Worker calls again
        absences += result.absences
        if result.error:
            status, error = "failed", result.error
            break
        status = "partial" if "partial" in (status, result.status) else "ok"
    outcome = SyncAllResult(handled, pending, status, error, purged, absences)
    logger.info("Garage Strava daily sync: status=%s error=%s accounts=%d purged=%d absences=%d pending=%d old_events=%d.",
                status, error or "none", handled, purged, absences, pending, old_events)
    return outcome


def default_after(actor):
    """Oldest Garage ride start, or 1 January of the previous year."""
    owner = require_actor(actor)
    oldest = Ride.objects.filter(owner_id=owner.pk, started_at__isnull=False).order_by("started_at").values_list("started_at", flat=True).first()
    return oldest or datetime(timezone.now().year - 1, 1, 1, tzinfo=datetime_timezone.utc)


def _budget(value):
    if type(value) is not int or not 1 <= value <= MAX_BUDGET:
        _fail("invalid_budget", f"Procesa entre una y {MAX_BUDGET} páginas por paso.")


def _merge_errors(current, new):
    """Durable summaries (invalid_metric) stay across pages; a newer failure replaces a transient one.

    Deduplicated and capped at 20, as validate_run_errors requires.
    """
    merged = []
    for entry in [*(entry for entry in current if entry["code"] not in TRANSIENT_RUN_CODES), *new]:
        if entry not in merged:
            merged.append(entry)
    return merged[:20]


def _fail_run(owner, run_id, code):
    with transaction.atomic():
        locked = _lock_owner(owner)
        run = get_inventory(locked, ImportRun, run_id)
        if run.state in ("completed", "cancelled"):
            return run
        if run.state in ("pending", "paused"):
            run = advance_import_run(locked, run.pk, state="running")
        account = StravaAccount.objects.filter(owner_id=locked.pk).first()
        _record(account, status="failed", error=code)
        return advance_import_run(locked, run.pk, state="failed",
                                  errors=_merge_errors(run.errors, [{"code": RUN_CODES.get(code, "unexpected_failure"), "session_index": None}]))


def start_strava_import(actor, *, after, budget=1):
    """Create a resumable Strava history job from `after` and run its first step."""
    owner = require_actor(actor)
    try:
        after = aware_instant(after)
    except ValidationError:
        _fail("invalid_period", "Elige una fecha válida.")
    if after >= timezone.now():
        _fail("invalid_period", "La fecha de inicio debe estar en el pasado.")
    _budget(budget)
    client = StravaClient()
    ensure_account(owner, client)
    run = create_import_run(owner, requested_from=after, source_kind="strava")
    return resume_strava_import(owner, run.pk, budget=budget, client=client)


def resume_strava_import(actor, run_id, *, budget=1, client=None):
    """Next pages of a Strava job: processed = cursor = confirmed pages; total stays unknown.

    Each page is committed with its checkpoint; no new page is requested after
    REQUEST_SECONDS (the job pauses and «Continuar» resumes it).
    """
    owner = require_actor(actor)
    run = get_inventory(owner, ImportRun, run_id)
    if run.source_kind != "strava":
        _fail("invalid_run", "Este trabajo no es de Strava.")
    if run.state in ("completed", "cancelled"):
        return run
    _budget(budget)
    deadline = _Deadline(REQUEST_SECONDS)
    client = client or StravaClient()
    client.deadline = deadline  # a page's timeouts are cut to end by RESPONSE_SECONDS: the job pauses instead
    try:
        account, _ = ensure_account(owner, client)
    except StravaError as error:
        return _fail_run(owner, run_id, "network" if error.code == "deadline" else error.code)
    for step in range(budget):
        if step and deadline.passed():
            break
        run = get_inventory(owner, ImportRun, run_id)
        if run.state in ("completed", "cancelled"):
            return run
        page = run.cursor + 1
        try:
            rows = client.activities(after=_epoch(run.requested_from), page=page)
        except StravaError as error:
            if error.code == "deadline":
                break  # paused below; «Continuar» asks for this page again
            return _fail_run(owner, run_id, error.code)
        with transaction.atomic():
            locked = _lock_owner(owner)
            run = get_inventory(locked, ImportRun, run_id)
            if run.state in ("completed", "cancelled") or run.cursor != page - 1:
                return run  # cancelled or advanced by another request meanwhile
            if run.state != "running":
                run = advance_import_run(locked, run.pk, state="running")
            if not rows:
                return advance_import_run(locked, run.pk, state="completed", errors=_merge_errors(run.errors, []))
            result = _store_rows(locked, account, rows, run=run)
            done = len(rows) < strava_client.PER_PAGE
            run = advance_import_run(locked, run.pk, state="completed" if done else "running", processed=page, cursor=page,
                                     items_imported=(run.items_imported or 0) + result.stored,
                                     items_skipped=(run.items_skipped or 0) + result.skipped + result.invalid,
                                     errors=_merge_errors(run.errors, [{"code": "invalid_metric", "session_index": None}] if result.invalid else []))
            if done:
                _record(account, status="ok")
                return run
    with transaction.atomic():
        locked = _lock_owner(owner)
        run = get_inventory(locked, ImportRun, run_id)
        if run.state == "pending":
            run = advance_import_run(locked, run.pk, state="running")  # its first page ran out of time
        if run.state == "running":
            run = advance_import_run(locked, run.pk, state="paused")
        return run


def cancel_strava_import(actor, run_id):
    return advance_import_run(actor, run_id, state="cancelled")


# Webhook hints ---------------------------------------------------------------

def _subscription_ok(subscription_id):
    expected = (str(getattr(settings, "STRAVA_WEBHOOK_SUBSCRIPTION_ID", "") or "")).strip()
    if not expected:
        return True
    return expected.isdecimal() and type(subscription_id) is int and subscription_id == int(expected)


def subscription_matches(event):
    """For the shared webhook view: False when a configured subscription id differs."""
    return _subscription_ok(event.get("subscription_id") if isinstance(event, dict) else None)


def _positive(value):
    return type(value) is int and 0 < value <= 2 ** 63 - 1


def _parse_event(event):
    if not isinstance(event, dict):
        return None
    if event.get("object_type") not in ("activity", "athlete") or event.get("aspect_type") not in ("create", "update", "delete"):
        return None
    if not all(_positive(event.get(key)) for key in ("object_id", "owner_id", "event_time")):
        return None
    subscription = event.get("subscription_id")
    if subscription is not None and type(subscription) is not int:
        return None
    try:
        event_time = datetime.fromtimestamp(event["event_time"], tz=datetime_timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    raw = event.get("updates") if isinstance(event.get("updates"), dict) else {}
    # Bounded and without personal text: no titles, only these short flags.
    updates = {key: str(raw[key])[:40] for key in UPDATE_KEYS if key in raw}
    return {"subscription_id": subscription or 0, "athlete_id": event["owner_id"], "object_type": event["object_type"],
            "aspect_type": event["aspect_type"], "object_id": event["object_id"], "event_time": event_time, "updates": updates}


def accept_event(event):
    """Persist a Garage hint for an athlete with a StravaAccount; its worker starts after commit. Never calls Strava."""
    values = _parse_event(event)
    if values is None or not _subscription_ok(values["subscription_id"] or None):
        return False
    account = StravaAccount.objects.filter(athlete_id=values["athlete_id"], revoked_at__isnull=True).only("id", "mode").first()
    if account is None:
        return False  # unknown athletes are dropped, not stored
    if values["object_type"] == "athlete" and account.mode == StravaAccount.Mode.ENV:
        return False  # deauthorization belongs to OAuth (garage-040)
    if _pending(values["athlete_id"]) >= PENDING_CAP:
        logger.warning("Garage Strava hints over the pending cap; event dropped.")
        return False
    try:
        with transaction.atomic():
            StravaEvent.objects.create(**values)
    except IntegrityError:
        return False  # Strava retried an event already stored
    athlete_id = values["athlete_id"]
    transaction.on_commit(lambda: _start_worker(athlete_id))
    return True


# At most one worker per athlete in this process: {athlete_id: [token, run_again]}.
_workers_lock = threading.Lock()
_workers = {}


def _enter(athlete_id):
    """A token when this caller may process the athlete's hints; None (and one more round requested) if busy."""
    with _workers_lock:
        entry = _workers.get(athlete_id)
        if entry is not None:
            entry[1] = True
            return None
        token = object()
        _workers[athlete_id] = [token, False]
        return token


def _again(athlete_id, token):
    """True once when hints arrived during the last round; otherwise the athlete is released."""
    with _workers_lock:
        entry = _workers.get(athlete_id)
        if entry is None or entry[0] is not token:
            return False
        if entry[1]:
            entry[1] = False
            return True
        del _workers[athlete_id]
        return False


def _release(athlete_id, token):
    """Release the athlete; True when another round had been requested meanwhile."""
    with _workers_lock:
        entry = _workers.get(athlete_id)
        if entry is None or entry[0] is not token:
            return False
        del _workers[athlete_id]
        return entry[1]


def _start_worker(athlete_id):
    """Start the athlete's background worker unless this process already runs one (it then takes one more round)."""
    token = _enter(athlete_id)
    if token is None:
        return False
    try:
        threading.Thread(target=_process_in_thread, args=(athlete_id, token), daemon=True,
                         name=f"garage-strava-{athlete_id}").start()
    except RuntimeError:
        _release(athlete_id, token)
        logger.error("Garage Strava worker could not start; the next sync confirms the hints.")
        return False
    return True


def _process_in_thread(athlete_id, token):
    try:
        process_pending_events(athlete_id, rounds=WORKER_ROUNDS, _token=token)
    except Exception as exc:  # the stored row is the truth; the next sync retries
        logger.error("Garage Strava hints failed: %s", type(exc).__name__)
    finally:
        _release(athlete_id, token)  # no-op when already released
        connection.close()


def _strava_source(owner, activity_id):
    return ActivitySource.objects.filter(owner_id=owner.pk, source_kind="strava", external_id=activity_id).first()


def _claim(event_id):
    """Count an attempt in its own committed statement before any Strava call; None if already settled."""
    if not StravaEvent.objects.filter(pk=event_id, processed_at__isnull=True).update(attempts=Least(F("attempts") + 1, Value(32767))):
        return None
    return StravaEvent.objects.filter(pk=event_id).first()


def _settle(event_id, code=""):
    """Mark a hint as settled. Outside a transaction it locks only the event row for one statement;
    inside one it must come after the owner lock."""
    return StravaEvent.objects.filter(pk=event_id, processed_at__isnull=True).update(processed_at=timezone.now(), error_code=code)


def _note(event_id, code):
    StravaEvent.objects.filter(pk=event_id, processed_at__isnull=True).update(error_code=code)


def _account_alive(owner, account):
    """Under the owner lock: «Quitar lo sincronizado» may have removed the account meanwhile."""
    return StravaAccount.objects.filter(pk=account.pk, owner_id=owner.pk, revoked_at__isnull=True).exists()


def _handle(account, event, client):
    """Confirm one claimed hint: Strava first with no transaction open, then the owner lock and the event row.

    A delete (from the webhook or an absence hint) withdraws only on 404 with activity:read_all. When the
    activity is still on Strava its fresh snapshot is stored like an update (phase 4): the source is kept and
    updated, or deleted if it is no longer cycling; a delete never creates a source.
    """
    owner = account.owner
    if event.object_type != "activity":
        return _settle(event.pk)
    deleting = event.aspect_type == "delete"
    if deleting and (not account.can_confirm_deletes or _strava_source(owner, event.object_id) is None):
        return _settle(event.pk)  # without activity:read_all a 404 proves nothing
    try:
        data = client.activity(event.object_id)
    except StravaError as error:
        if error.code != "not_found" or not deleting:
            raise
        with transaction.atomic():
            locked = _lock_owner(owner)
            if _account_alive(locked, account):
                source = _strava_source(locked, event.object_id)
                if source is not None:
                    touched = set()
                    discard_source(locked, source, touched)
                    rebuild_rides_locked(locked, touched)
            return _settle(event.pk)
    with transaction.atomic():
        locked = _lock_owner(owner)
        if _account_alive(locked, account) and not (deleting and _strava_source(locked, event.object_id) is None):
            result = _store_rows(locked, account, [data], require_athlete=True)
            if result.invalid:
                raise ValueError("activity")
        return _settle(event.pk)


@dataclass(frozen=True)
class EventsResult:
    settled: int = 0
    error: str = ""     # a stop code (rate_limited, unauthorized, network) that halted the batch
    busy: bool = False  # this process already had a worker for the athlete (it takes one more round)
    cut: bool = False   # the time limit stopped the batch: the rest waits for the next press or worker


@dataclass(frozen=True)
class _Batch:
    settled: int = 0
    error: str = ""
    # `limit` hints were pending and some got settled: more may be waiting behind them. A full batch that
    # settled nothing (every hint failed for now) is not repeated at once: Strava is not hammered.
    more: bool = False
    cut: bool = False


def _process_batch(account, *, limit, client, deadline):
    """Up to `limit` pending hints, oldest first."""
    ids = list(StravaEvent.objects.filter(athlete_id=account.athlete_id, processed_at__isnull=True)
               .order_by("event_time", "id").values_list("pk", flat=True)[:limit])
    full = len(ids) == limit
    settled = 0
    for event_id in ids:
        if deadline is not None and deadline.passed():
            return _Batch(settled, cut=True)
        event = _claim(event_id)
        if event is None:
            continue
        try:
            settled += bool(_handle(account, event, client))
        except StravaError as error:
            if error.code == "not_found":
                settled += _settle(event.pk, "not_found")  # invisible or gone: nothing to store
            elif error.code == "deadline":
                return _Batch(settled, cut=True)  # out of time, not the hint's fault: it stays pending as it was
            elif error.code in STOP_CODES:
                _note(event.pk, error.code)
                return _Batch(settled, error.code)
            elif event.attempts >= MAX_ATTEMPTS:
                settled += _settle(event.pk, error.code)  # e.g. invalid_response: stop retrying it
            else:
                _note(event.pk, error.code)
        except (ValueError, ValidationError, IntegrityError):
            settled += _settle(event.pk, "invalid_response")  # an unusable activity: retrying cannot help
    return _Batch(settled, more=full and settled > 0)


def process_pending_events(athlete_id, *, limit=EVENT_BATCH, client=None, deadline=None, rounds=1, _token=None):
    """Confirm pending hints of one athlete through the API (one worker per athlete in this process).

    A full batch is followed by another round, as are hints that arrived during a
    round. When the last round still leaves work (garage-030 phase 3 review), a
    background worker (`_token`) hands it to a fresh worker, and a caller that
    took the token itself (sync_now) restarts one only for hints that arrived
    meanwhile: the rest beyond its limit is reported as pending for the next press.
    """
    account = StravaAccount.objects.filter(athlete_id=athlete_id, revoked_at__isnull=True).select_related("owner").first()
    if account is None or not account.owner.is_active:
        return EventsResult()
    token = _token or _enter(athlete_id)
    if token is None:
        return EventsResult(busy=True)
    client = client or StravaClient()
    settled, error, again, more, cut = 0, "", False, False, False
    try:
        for index in range(rounds):
            batch = _process_batch(account, limit=limit, client=client, deadline=deadline)
            settled, error, cut = settled + batch.settled, batch.error, batch.cut
            if error or cut:
                break
            if index + 1 == rounds:
                # Last round: never consume the «one more round» flag here, _release reads it below.
                more = batch.more
                break
            if not batch.more and not _again(athlete_id, token):
                break
    finally:
        again = _release(athlete_id, token)
    if (again or (more and _token is not None)) and not error:
        _start_worker(athlete_id)  # what is left (late hints or a full last batch) goes to a fresh worker
    return EventsResult(settled, error, cut=cut)
