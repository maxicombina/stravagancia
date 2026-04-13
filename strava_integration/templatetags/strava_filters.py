from django import template

register = template.Library()


@register.filter
def duration(seconds):
    """Format a duration in seconds as '1h 23m' or '45m'."""
    if seconds is None:
        return '—'
    seconds = int(seconds)
    h, remainder = divmod(seconds, 3600)
    m = remainder // 60
    if h:
        return f'{h}h {m:02d}m'
    return f'{m}m'


@register.filter
def speed_kmh(speed_ms):
    """Convert m/s to km/h string."""
    if not speed_ms:
        return '—'
    return f"{speed_ms * 3.6:.1f}"
