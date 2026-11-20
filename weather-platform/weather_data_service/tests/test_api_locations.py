"""/location/*: список, пагинация, ближайшая точка, создание, правка, удаление."""
import uuid
from datetime import datetime

from models.weather import Location, WeatherObservation


# ---------- список ----------
def test_list_filters_by_kind_and_sorts_by_name(client, add_location):
    add_location("Бирск", "city", 55.4, 55.5)
    add_location("Агидель", "city", 55.9, 53.9)
    add_location("Узел", "grid", 54.0, 56.0)
    names = [x["name"] for x in client.get("/location/", params={"kind": "city"}).json()]
    assert names == ["Агидель", "Бирск"]
    assert len(client.get("/location/").json()) == 3


def test_list_pagination(client, add_location):
    for i, name in enumerate(["А", "Б", "В"]):
        add_location(name, "city", 54.0 + i, 56.0)
    page = client.get("/location/", params={"limit": 2, "offset": 1}).json()
    assert [x["name"] for x in page] == ["Б", "В"]


def test_list_rejects_bad_paging(client):
    for params in ({"limit": 0}, {"limit": 5001}, {"offset": -1}):
        assert client.get("/location/", params=params).status_code == 422


# ---------- ближайшая ----------
def test_nearest_respects_kind_filter(client, add_location):
    add_location("Уфа", "city", 54.74, 55.97)
    add_location("Узел", "grid", 54.0, 56.0)
    anywhere = client.get("/location/nearest", params={"lat": 54.0, "lon": 56.0}).json()
    assert anywhere["name"] == "Узел" and anywhere["distance_km"] == 0
    only_city = client.get("/location/nearest", params={"lat": 54.0, "lon": 56.0, "kind": "city"}).json()
    assert only_city["name"] == "Уфа" and only_city["distance_km"] > 50


def test_nearest_without_locations_is_404(client):
    assert client.get("/location/nearest", params={"lat": 54.0, "lon": 56.0}).status_code == 404


def test_nearest_validates_coordinates(client):
    assert client.get("/location/nearest", params={"lat": 91, "lon": 56}).status_code == 422
    assert client.get("/location/nearest", params={"lat": 54}).status_code == 422


# ---------- одна локация ----------
def test_get_one_location(client, add_location):
    loc_id = add_location("Уфа")
    body = client.get(f"/location/{loc_id}").json()
    assert body["name"] == "Уфа" and body["id"] == str(loc_id)


def test_get_unknown_location_is_404_and_bad_uuid_is_422(client):
    assert client.get(f"/location/{uuid.uuid4()}").status_code == 404
    assert client.get("/location/not-a-uuid").status_code == 422


# ---------- создание ----------
def test_create_applies_defaults(client):
    resp = client.post("/location/new", json={"name": "Тест", "latitude": 54.0, "longitude": 56.0})
    assert resp.status_code == 200
    created = client.get(f"/location/{resp.json()['id']}").json()
    assert (created["kind"], created["country"], created["region"]) == ("city", "RU", "Республика Башкортостан")


def test_create_validates_body(client):
    bad_bodies = [
        {"name": "", "latitude": 54.0, "longitude": 56.0},        # пустое имя
        {"name": "X", "latitude": 95.0, "longitude": 56.0},       # широта вне диапазона
        {"name": "X", "latitude": 54.0},                          # нет долготы
    ]
    for body in bad_bodies:
        assert client.post("/location/new", json=body).status_code == 422


def test_create_bbox_edges(client):
    assert client.post("/location/new", json={"name": "угол", "latitude": 51.3, "longitude": 52.8}).status_code == 200
    assert client.post("/location/new", json={"name": "мимо", "latitude": 51.29, "longitude": 52.8}).status_code == 400


def test_same_coordinates_allowed_for_different_kind(client):
    base = {"name": "A", "latitude": 54.0, "longitude": 56.0}
    assert client.post("/location/new", json={**base, "kind": "city"}).status_code == 200
    assert client.post("/location/new", json={**base, "kind": "grid"}).status_code == 200


# ---------- правка ----------
def test_update_is_partial(client, add_location):
    loc_id = add_location("Старое", "city", 54.0, 56.0)
    client.put(f"/location/edit/{loc_id}", json={"district": "Уфимский"})
    body = client.put(f"/location/edit/{loc_id}", json={"name": "Новое"}).json()
    assert body["name"] == "Новое" and body["district"] == "Уфимский"      # прошлая правка не затёрлась
    assert (body["latitude"], body["longitude"]) == (54.0, 56.0)


def test_update_errors(client, add_location):
    first = add_location("A", "city", 54.0, 56.0)
    second = add_location("B", "city", 55.0, 56.0)
    assert client.put(f"/location/edit/{uuid.uuid4()}", json={"name": "x"}).status_code == 404
    assert client.put(f"/location/edit/{first}", json={"latitude": 10.0}).status_code == 400     # вне РБ
    assert client.put(f"/location/edit/{first}", json={"latitude": 95.0}).status_code == 422
    assert client.put(f"/location/edit/{second}", json={"latitude": 54.0}).status_code == 409    # занято


# ---------- удаление ----------
def test_delete_removes_only_its_observations(client, add_location, add_observation, count_rows):
    gone = add_location("Уйдёт", "city", 54.0, 56.0)
    stays = add_location("Останется", "city", 55.0, 56.0)
    add_observation(gone, datetime(2026, 11, 6, 0), temperature=1.0)
    add_observation(gone, datetime(2026, 11, 6, 1), temperature=2.0)
    add_observation(stays, datetime(2026, 11, 6, 0), temperature=3.0)

    assert client.delete(f"/location/delete/{gone}").status_code == 200
    assert count_rows(Location) == 1
    assert count_rows(WeatherObservation) == 1


def test_delete_unknown_is_404(client):
    assert client.delete(f"/location/delete/{uuid.uuid4()}").status_code == 404
