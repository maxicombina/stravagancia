"""The viewer's IANA time zone for local presentation (dates, monthly buckets).

garage.js stores the browser zone in the garage_tz cookie; it is only used
after it resolves to a real zone. Storage and domain instants stay UTC.
"""
from urllib.parse import unquote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings

COOKIE = "garage_tz"
DEFAULT_ZONE = ZoneInfo(getattr(settings, "GARAGE_DEFAULT_TIME_ZONE", "Europe/Madrid"))


def parse_zone(value):
    if not isinstance(value, str) or not 0 < len(value) <= 64 or value.startswith(("/", ".")) or ".." in value:
        return None
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None


def user_time_zone(request):
    value = request.COOKIES.get(COOKIE)
    # Older clients percent-encoded the "/" of IANA names.
    return parse_zone(value) or parse_zone(unquote(value) if isinstance(value, str) else value) or DEFAULT_ZONE
