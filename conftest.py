import django
import pytest
from django.utils import timezone


@pytest.fixture
def athlete(db):
    """Create and return a test Athlete instance."""
    from strava_integration.models import Athlete

    return Athlete.objects.create(
        strava_id=12345678,
        first_name="John",
        last_name="Doe",
        username="johndoe",
        city="Buenos Aires",
        country="Argentina",
        profile="https://example.com/profile.jpg",
    )


@pytest.fixture
def activity(db, athlete):
    """Create and return a test Activity instance."""
    from strava_integration.models import Activity

    return Activity.objects.create(
        athlete=athlete,
        strava_id=9999001,
        name="Morning Ride",
        distance=35000.0,
        moving_time=4500,
        elapsed_time=4800,
        total_elevation_gain=250.0,
        activity_type="Ride",
        sport_type="Ride",
        start_date=timezone.now(),
        start_date_local=timezone.now(),
        average_speed=7.78,
        max_speed=12.5,
        calories=800.0,
        average_heartrate=145.0,
        max_heartrate=172.0,
    )


@pytest.fixture
def strava_activity_payload(athlete):
    """Return a dict mimicking a Strava API activity response."""
    return {
        "id": 8888001,
        "athlete": {"id": athlete.strava_id},
        "name": "Evening Ride",
        "distance": 42000.0,
        "moving_time": 5400,
        "elapsed_time": 5600,
        "total_elevation_gain": 320.0,
        "type": "Ride",
        "sport_type": "Ride",
        "start_date": "2026-03-01T18:00:00Z",
        "start_date_local": "2026-03-01T15:00:00Z",
        "utc_offset": -10800.0,
        "average_speed": 7.78,
        "max_speed": 13.2,
        "calories": 950.0,
        "average_heartrate": 148.0,
        "max_heartrate": 175.0,
    }
