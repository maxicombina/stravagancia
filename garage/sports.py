"""Garage modality keys, the cycling family and Strava's cycling sport types.

Ride.sport_type and UsageProfile.sport_type hold lowercase keys. A profile with
the generic `cycling` key covers every cycling key; a specific key (gravel_ride,
virtual_ride…) covers only itself and a blank profile covers every modality.
"""

GENERIC_CYCLING = "cycling"

# Spanish labels; every key here belongs to the cycling family.
SPORT_LABELS = {
    "cycling": "ciclismo", "road_biking": "ruta", "road": "ruta", "gravel_ride": "gravel", "gravel_cycling": "gravel",
    "mountain_biking": "MTB", "mountain_bike_ride": "MTB", "virtual_ride": "rodillo", "indoor_cycling": "rodillo",
    "e_bike_ride": "e-bike", "e_mountain_bike_ride": "e-MTB", "commuting": "ciudad", "velomobile": "velomóvil",
    "handcycle": "handbike",
}
CYCLING_KEYS = frozenset(SPORT_LABELS)

# Strava `sport_type` (or legacy `type`) → Garage key. Anything else is not cycling.
STRAVA_CYCLING = {
    "Ride": "cycling", "GravelRide": "gravel_ride", "MountainBikeRide": "mountain_bike_ride", "EBikeRide": "e_bike_ride",
    "EMountainBikeRide": "e_mountain_bike_ride", "VirtualRide": "virtual_ride", "Velomobile": "velomobile",
    "Handcycle": "handcycle",
}


def sport_label(key):
    """Spanish label of a modality key; other keys as stored (profiles accept any lowercase key)."""
    return SPORT_LABELS.get(key, key) if isinstance(key, str) else key


def is_cycling(key):
    return isinstance(key, str) and key.strip().lower() in CYCLING_KEYS


def strava_sport(value):
    """Canonical Garage key for a Strava cycling sport, or None for other sports."""
    return STRAVA_CYCLING.get(value) if isinstance(value, str) else None


def profile_covers(profile_sport, ride_sport):
    """Family matching between a usage profile modality and a ride modality."""
    modality = (ride_sport or "").strip().lower()
    return profile_sport == "" or profile_sport == modality or (profile_sport == GENERIC_CYCLING and modality in CYCLING_KEYS)


def is_specific_cycling(key):
    return is_cycling(key) and key != GENERIC_CYCLING
