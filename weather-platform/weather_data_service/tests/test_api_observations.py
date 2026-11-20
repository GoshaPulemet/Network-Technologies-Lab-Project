"""/observation/*: список, срез, ряд, диапазон, последнее значение, ручной ввод."""
import uuid
from datetime import datetime, timedelta

from models.weather import utc_now

DAY = datetime(2026, 11, 6)


def fill(add_observation, loc_id, temps):
    """По наблюдению на каждый час суток DAY: temps[i] - температура в i-й час."""
    for h, t in enumerate(temps):
        add_observation(loc_id, DAY + timedelta(hours=h), temperature=t)


# ---------- список ----------
def test_list_filters_by_location(client, add_location, add_observation):
    a, b = add_location("A", "city", 54.0, 56.0), add_location("B", "city", 55.0, 56.0)
    fill(add_observation, a, [1, 2])
    fill(add_observation, b, [9])
    got = client.get("/observation/", params={"location_id": str(a)}).json()
    assert [o["temperature"] for o in got] == [1, 2]
    assert len(client.get("/observation/").json()) == 3


def test_list_date_range_is_inclusive(client, add_location, add_observation):
    loc = add_location()
    fill(add_observation, loc, [0, 1, 2, 3, 4])
    got = client.get("/observation/", params={
        "date_from": "2026-11-06T01:00:00", "date_to": "2026-11-06T03:00:00"}).json()
    assert [o["temperature"] for o in got] == [1, 2, 3]


def test_list_converts_timezone_filters_to_utc(client, add_location, add_observation):
    loc = add_location()
    fill(add_observation, loc, [0, 1, 2, 3, 4])
    got = client.get("/observation/", params={"date_from": "2026-11-06T07:00:00+05:00"}).json()   # = 02:00 UTC
    assert [o["temperature"] for o in got] == [2, 3, 4]


def test_list_limit_returns_latest_in_ascending_order(client, add_location, add_observation):
    loc = add_location()
    fill(add_observation, loc, [0, 1, 2, 3, 4])
    got = client.get("/observation/", params={"limit": 2}).json()
    assert [o["temperature"] for o in got] == [3, 4]


def test_list_rejects_bad_limit(client):
    assert client.get("/observation/", params={"limit": 0}).status_code == 422
    assert client.get("/observation/", params={"limit": 5001}).status_code == 422


# ---------- срез ----------
def test_snapshot_skips_null_values(client, add_location, add_observation):
    a, b = add_location("A", "grid", 54.0, 56.0), add_location("B", "grid", 55.0, 56.0)
    add_observation(a, DAY, temperature=1.0, humidity=50.0)
    add_observation(b, DAY, temperature=None, humidity=60.0)
    temp = client.get("/observation/snapshot", params={"parameter": "temperature", "at": "2026-11-06T00:00:00Z"}).json()
    hum = client.get("/observation/snapshot", params={"parameter": "humidity", "at": "2026-11-06T00:00:00Z"}).json()
    assert temp["count"] == 1 and temp["points"][0]["name"] == "A"
    assert hum["count"] == 2 and hum["unit"] == "%"


def test_snapshot_kind_filter(client, add_location, add_observation):
    add_observation(add_location("Город", "city", 54.0, 56.0), DAY, temperature=1.0)
    add_observation(add_location("Узел", "grid", 55.0, 56.0), DAY, temperature=2.0)
    base = {"parameter": "temperature", "at": "2026-11-06T00:00:00Z"}
    assert client.get("/observation/snapshot", params=base).json()["points"][0]["name"] == "Узел"   # по умолчанию grid
    assert client.get("/observation/snapshot", params={**base, "kind": "city"}).json()["points"][0]["name"] == "Город"
    assert client.get("/observation/snapshot", params={**base, "kind": "all"}).json()["count"] == 2


def test_snapshot_without_at_uses_current_hour(client, add_location, add_observation):
    hour = utc_now().replace(minute=0, second=0, microsecond=0)
    add_observation(add_location("Узел", "grid", 55.0, 56.0), hour, temperature=2.0)
    snap = client.get("/observation/snapshot", params={"parameter": "temperature"}).json()
    assert snap["count"] == 1 and snap["at"] == hour.isoformat() + "Z"


def test_snapshot_rejects_unknown_parameters(client):
    resp = client.get("/observation/snapshot", params={"parameter": "id"})     # колонка есть, но параметром не является
    assert resp.status_code == 400 and "temperature" in resp.json()["detail"]
    assert client.get("/observation/snapshot").status_code == 422


# ---------- ряд ----------
def test_series_is_sorted_and_keeps_gaps(client, add_location, add_observation):
    loc = add_location()
    add_observation(loc, DAY + timedelta(hours=2), temperature=3.0)
    add_observation(loc, DAY, temperature=1.0)
    add_observation(loc, DAY + timedelta(hours=1), temperature=None, humidity=70.0)
    series = client.get("/observation/series", params={"location_id": str(loc), "parameter": "temperature"}).json()
    assert [p["value"] for p in series["points"]] == [1.0, None, 3.0]
    assert series["unit"] == "°C" and series["points"][1]["t"] == "2026-11-06T01:00:00Z"


def test_series_date_filters(client, add_location, add_observation):
    loc = add_location()
    fill(add_observation, loc, [0, 1, 2, 3])
    series = client.get("/observation/series", params={
        "location_id": str(loc), "parameter": "temperature",
        "date_from": "2026-11-06T01:00:00", "date_to": "2026-11-06T02:00:00"}).json()
    assert [p["value"] for p in series["points"]] == [1, 2]


def test_series_errors(client, add_location):
    loc = add_location()
    assert client.get("/observation/series", params={"location_id": str(uuid.uuid4()), "parameter": "temperature"}).status_code == 404
    assert client.get("/observation/series", params={"location_id": str(loc), "parameter": "nope"}).status_code == 400
    assert client.get("/observation/series", params={"parameter": "temperature"}).status_code == 422


# ---------- диапазон ----------
def test_range_on_empty_database(client):
    assert client.get("/observation/range").json() == {"first": None, "last": None, "updated_at": None}


def test_range_reports_first_last_and_update_time(client, add_location, add_observation):
    loc = add_location()
    add_observation(loc, DAY + timedelta(hours=5), temperature=1.0, fetched_at=datetime(2026, 11, 6, 9, 30))
    add_observation(loc, DAY, temperature=1.0, fetched_at=datetime(2026, 11, 6, 8, 0))
    assert client.get("/observation/range").json() == {
        "first": "2026-11-06T00:00:00Z", "last": "2026-11-06T05:00:00Z", "updated_at": "2026-11-06T09:30:00Z"}


# ---------- последнее ----------
def test_latest_ignores_the_future(client, add_location, add_observation):
    loc = add_location()
    now = utc_now().replace(minute=0, second=0, microsecond=0)
    add_observation(loc, now - timedelta(hours=2), temperature=1.0)
    add_observation(loc, now - timedelta(hours=1), temperature=2.0)
    add_observation(loc, now + timedelta(hours=5), temperature=99.0)
    assert client.get(f"/observation/latest/{loc}").json()["temperature"] == 2.0


def test_latest_404_when_only_future_or_unknown(client, add_location, add_observation):
    loc = add_location()
    add_observation(loc, utc_now() + timedelta(days=1), temperature=1.0)
    assert client.get(f"/observation/latest/{loc}").status_code == 404
    assert client.get(f"/observation/latest/{uuid.uuid4()}").status_code == 404


# ---------- ручной ввод ----------
def test_create_derives_condition_from_code(client, add_location):
    loc = add_location()
    client.post("/observation/new", json={"location_id": str(loc), "observed_at": "2026-11-06T12:00:00", "weather_code": 71})
    obs = client.get("/observation/", params={"location_id": str(loc)}).json()[0]
    assert obs["weather_condition"] == "snow_light" and obs["is_forecast"] is False and obs["fetched_at"]


def test_create_keeps_explicit_condition_and_allows_missing_code(client, add_location):
    loc = add_location()
    client.post("/observation/new", json={
        "location_id": str(loc), "observed_at": "2026-11-06T12:00:00", "weather_code": 71, "weather_condition": "моя"})
    client.post("/observation/new", json={"location_id": str(loc), "observed_at": "2026-11-06T13:00:00"})
    first, second = client.get("/observation/", params={"location_id": str(loc)}).json()
    assert first["weather_condition"] == "моя" and second["weather_condition"] is None


def test_create_converts_timezone_to_utc(client, add_location):
    loc = add_location()
    client.post("/observation/new", json={
        "location_id": str(loc), "observed_at": "2026-11-06T17:00:00+05:00", "temperature": 1.0})
    obs = client.get("/observation/", params={"location_id": str(loc)}).json()[0]
    assert obs["observed_at"] == "2026-11-06T12:00:00"


def test_create_errors(client, add_location):
    loc = add_location()
    assert client.post("/observation/new", json={
        "location_id": str(uuid.uuid4()), "observed_at": "2026-11-06T12:00:00"}).status_code == 404
    assert client.post("/observation/new", json={"location_id": str(loc)}).status_code == 422
    assert client.post("/observation/new", json={
        "location_id": "не-uuid", "observed_at": "2026-11-06T12:00:00"}).status_code == 422
