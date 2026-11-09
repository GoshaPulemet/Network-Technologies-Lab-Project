"""Управление данными без запуска сервера.

    python cli.py fetch-boundary          скачать границу РБ (OSM Nominatim)
    python cli.py seed [--step 0.25]      создать города и узлы сетки
    python cli.py seed --rebuild-grid     пересоздать сетку (удалит старые узлы и их данные)
    python cli.py sync                    загрузить прогноз из Open-Meteo
    python cli.py backfill --from 2025-01-01 --to 2025-12-31   загрузить архив
    python cli.py status                  что сейчас в БД
"""
import argparse
import json
import sys
from datetime import date

from config import DATA_DIR, settings


def cmd_fetch_boundary(_args) -> int:
    import httpx
    from services.grid import polygons_from_geojson

    resp = httpx.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": "Республика Башкортостан", "format": "geojson",
                "polygon_geojson": 1, "polygon_threshold": 0.01, "limit": 5},
        headers={"User-Agent": "weather-platform-student-project"},
        timeout=60,
    )
    resp.raise_for_status()
    features = [f for f in resp.json().get("features", [])
                if (f.get("geometry") or {}).get("type") in ("Polygon", "MultiPolygon")]
    if not features:
        print("Nominatim не вернул полигон. Скачайте границу вручную (GADM/geoBoundaries) "
              f"и сохраните в {settings.boundary_file}")
        return 1
    feature = features[0]
    polygons = polygons_from_geojson(feature)
    points = sum(len(r) for poly in polygons for r in poly)
    out = DATA_DIR / "rb_boundary.geojson"
    out.write_text(json.dumps({"type": "FeatureCollection", "features": [feature]},
                              ensure_ascii=False), encoding="utf-8")
    name = (feature.get("properties") or {}).get("display_name", "?")
    print(f"Сохранено: {out}\n  объект: {name}\n  полигонов: {len(polygons)}, вершин: {points}")
    print("Проверьте, что это именно Республика Башкортостан. "
          "Затем: python cli.py seed --rebuild-grid")
    return 0


def cmd_seed(args) -> int:
    from sqlmodel import Session
    from database.connections import conn, engine_url
    from services.seed import delete_locations_by_kind, seed_locations

    conn()
    with Session(engine_url) as session:
        if args.rebuild_grid:
            print(f"Удалено старых узлов сетки: {delete_locations_by_kind(session, 'grid')}")
        print(seed_locations(session, args.step or settings.grid_step))
    return 0


def cmd_sync(_args) -> int:
    from database.connections import conn
    from services.jobs import run_forecast_job

    conn()
    batch_id = run_forecast_job()
    print(f"Готово. Запись журнала: {batch_id}. Подробности: python cli.py status")
    return 0


def cmd_backfill(args) -> int:
    from database.connections import conn
    from services.jobs import run_archive_job

    conn()
    start, end = date.fromisoformat(args.date_from), date.fromisoformat(args.date_to)
    batch_id = run_archive_job(start, end)
    if batch_id is None:
        print("Загрузка не запущена (неверный период или другая загрузка уже идёт).")
        return 1
    print(f"Готово. Запись журнала: {batch_id}. Подробности: python cli.py status")
    return 0


def cmd_status(_args) -> int:
    from sqlalchemy import func
    from sqlmodel import Session, col, select
    from database.connections import conn, engine_url
    from models.weather import ImportBatch, Location, WeatherObservation

    conn()
    with Session(engine_url) as session:
        kinds = session.exec(select(Location.kind, func.count()).group_by(Location.kind)).all()
        print("Локации:", {k: n for k, n in kinds} or "нет")
        total = session.exec(select(func.count()).select_from(WeatherObservation)).one()
        first, last = session.exec(select(func.min(WeatherObservation.observed_at),
                                          func.max(WeatherObservation.observed_at))).one()
        print(f"Наблюдений: {total}; период: {first} .. {last} (UTC)")
        batches = session.exec(select(ImportBatch)
                               .order_by(col(ImportBatch.started_at).desc()).limit(5)).all()
        for b in batches:
            print(f"  [{b.status:7}] {b.kind:8} {b.started_at:%Y-%m-%d %H:%M} "
                  f"точек={b.locations_total} строк={b.rows_upserted}"
                  + (f"\n      ошибка: {b.error}" if b.error else ""))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("fetch-boundary").set_defaults(func=cmd_fetch_boundary)

    p_seed = sub.add_parser("seed")
    p_seed.add_argument("--step", type=float, default=None, help="шаг сетки в градусах")
    p_seed.add_argument("--rebuild-grid", action="store_true")
    p_seed.set_defaults(func=cmd_seed)

    sub.add_parser("sync").set_defaults(func=cmd_sync)

    p_back = sub.add_parser("backfill")
    p_back.add_argument("--from", dest="date_from", required=True)
    p_back.add_argument("--to", dest="date_to", required=True)
    p_back.set_defaults(func=cmd_backfill)

    sub.add_parser("status").set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
