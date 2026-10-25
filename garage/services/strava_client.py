"""Garage's own Strava API v3 client in token mode (garage-030).

The access token comes only from strava_integration.utils.refresh_access_token()
(Stravagancia's refresh token, the same rotation risk the legacy app already
runs); Garage stores no token. Every request uses at most timeout=(5, 20) and decodes
numbers with parse_float=Decimal, never through a float. A 401 renews the token
once; a second 401 is `unauthorized`. A 429 stops the caller (`rate_limited`)
with Strava's X-RateLimit-Usage. Errors carry codes only: no token, body or
personal data is logged or stored.

Strava announced a new API domain from 2027-06-01; API_BASE is Garage's single
constant (the legacy copies in services.py and renaming.py are a separate task).
Known limit: the legacy refresh_access_token() itself has no timeout.

A client given a `deadline` (garage-030 phase 3) cuts each request's timeout to
the time it has left: connect and read together never exceed it (half each when
it is short). A request that cannot start, or that times out only because of
that cut, raises the internal code `deadline` (never stored) and the caller
leaves the rest for later. requests has no total timeout, so this is a cap on
the usual case, not a hard limit: DNS resolution is not bounded, a body that
keeps trickling restarts the read timeout on each chunk, and the token renewal
has none. A «Sincronizar ahora» press answers in about 30 s; gunicorn's 60 s
timeout remains the hard ceiling.
"""
import json
import logging
import re
from decimal import Decimal

import requests

from strava_integration.utils import refresh_access_token

logger = logging.getLogger(__name__)

API_BASE = "https://www.strava.com/api/v3"
TIMEOUT = (5, 20)
# 50 activities per page (Strava allows 200): one page and its checkpoint stay small
# enough for one web request on Render→Neon (garage-030 review).
PER_PAGE = 50


class StravaError(Exception):
    """A Strava call that did not produce usable data; `code` is safe to store."""

    def __init__(self, code, *, status=None, usage=""):
        self.code = code
        self.status = status
        self.usage = usage
        super().__init__(code)


def _usage(headers):
    value = (headers or {}).get("X-RateLimit-Usage", "")
    return value if isinstance(value, str) and re.fullmatch(r"[0-9, ]{1,40}", value) else ""


def _decode(text):
    try:
        return json.loads(text, parse_float=Decimal)
    except (ValueError, TypeError):
        raise StravaError("invalid_response") from None


class StravaClient:
    """One instance per sync, import step or event batch: it reuses its access token."""

    def __init__(self, *, deadline=None):
        self._token = None
        self.deadline = deadline  # anything with left() -> seconds; None: the plain TIMEOUT

    def _timeout(self):
        """(timeout, cut): TIMEOUT, or (connect, read) adding up to what is left of the deadline when that is shorter.

        requests waits up to connect + read (garage-030 phase 3 review): capping each
        at `left` let a call started near the end run to about 35 s instead of 30 s.
        """
        if self.deadline is None:
            return TIMEOUT, False
        left = self.deadline.left()
        if left <= 0:
            raise StravaError("deadline")
        connect = min(TIMEOUT[0], left / 2)
        timeout = (connect, min(TIMEOUT[1], left - connect))
        return timeout, timeout != TIMEOUT

    def _renew(self):
        try:
            token = refresh_access_token()
        except requests.HTTPError as error:
            status = getattr(getattr(error, "response", None), "status_code", None)
            logger.warning("Strava token renewal rejected (status %s).", status)
            raise StravaError("unauthorized" if status in (400, 401, 403) else "network", status=status) from None
        except requests.RequestException:
            logger.warning("Strava token renewal failed (network).")
            raise StravaError("network") from None
        except (KeyError, ValueError, TypeError):
            raise StravaError("invalid_response") from None
        if not isinstance(token, str) or not token:
            raise StravaError("invalid_response")
        return token

    def get(self, path, params=None):
        for attempt in range(2):
            if self._token is None:
                self._token = self._renew()
            timeout, cut = self._timeout()
            try:
                response = requests.get(API_BASE + path, headers={"Authorization": "Bearer " + self._token},
                                        params=params, timeout=timeout)
            except requests.Timeout:
                if cut:
                    raise StravaError("deadline") from None  # out of this request's time, not a network failure
                logger.warning("Strava request failed (network) for %s.", path.split("/")[1] if "/" in path else path)
                raise StravaError("network") from None
            except requests.RequestException:
                logger.warning("Strava request failed (network) for %s.", path.split("/")[1] if "/" in path else path)
                raise StravaError("network") from None
            status = response.status_code
            if status == 401 and attempt == 0:
                self._token = None
                continue
            if status in (401, 403):
                raise StravaError("unauthorized", status=status)
            if status == 429:
                usage = _usage(response.headers)
                logger.warning("Strava rate limit reached (usage %s).", usage or "unknown")
                raise StravaError("rate_limited", status=status, usage=usage)
            if status == 404:
                raise StravaError("not_found", status=status)
            if status >= 500:
                raise StravaError("network", status=status)
            if status >= 400 or status < 200:
                raise StravaError("invalid_response", status=status)
            return _decode(response.text)
        raise StravaError("unauthorized")  # pragma: no cover - the loop always returns or raises

    def athlete(self):
        data = self.get("/athlete")
        if not isinstance(data, dict):
            raise StravaError("invalid_response")
        return data

    def activities(self, *, after, page, per_page=None):
        """One page of the athlete's activities started after `after` (epoch seconds), oldest first."""
        per_page = PER_PAGE if per_page is None else per_page
        data = self.get("/athlete/activities", {"after": int(after), "page": int(page), "per_page": int(per_page)})
        if not isinstance(data, list):
            raise StravaError("invalid_response")
        return data

    def activity(self, activity_id):
        data = self.get(f"/activities/{int(activity_id)}")
        if not isinstance(data, dict):
            raise StravaError("invalid_response")
        return data
