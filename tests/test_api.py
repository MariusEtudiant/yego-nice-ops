"""Tests de l'API sur les tables versionnees de data/bi."""

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_health_lists_star_schema_tables():
    r = client.get("/api/health")
    assert r.status_code == 200
    tables = set(r.json()["tables"])
    assert {"dim_city", "dim_zone", "dim_hour", "fct_fleet_hourly", "fct_zone_hourly", "fct_battery_swaps"} <= tables


def test_cities_have_consistent_rates():
    r = client.get("/api/cities")
    assert r.status_code == 200
    cities = {c["city"]: c for c in r.json()}
    assert set(cities) == {"nice", "barcelona"}
    for c in cities.values():
        assert 0 < c["availability_rate"] <= 1
        assert c["avg_available"] <= c["avg_listed"]


def test_fleet_is_hourly_and_ordered():
    hours = client.get("/api/cities/nice/fleet").json()
    assert len(hours) > 0
    stamps = [h["hour_local"] for h in hours]
    assert stamps == sorted(stamps)
    assert len(stamps) == len(set(stamps))


def test_zones_status_follows_thresholds():
    zones = client.get("/api/cities/nice/zones", params={"hour": 19}).json()
    assert len(zones) > 0
    for z in zones:
        if z["status"] == "shortage":
            assert z["avg_available"] < 1 and z["departures_per_day"] >= 1


def test_swaps_cover_every_hour():
    hours = client.get("/api/cities/barcelona/swaps").json()
    assert [h["local_hour"] for h in hours] == list(range(24))
    assert all(h["confirmed_swaps"] <= h["swaps"] for h in hours)


def test_invalid_inputs():
    assert client.get("/api/cities/paris/fleet").status_code == 404
    assert client.get("/api/cities/nice/zones", params={"hour": 24}).status_code == 422
