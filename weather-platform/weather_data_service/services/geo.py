import math

from config import RB_LAT_MAX, RB_LAT_MIN, RB_LON_MAX, RB_LON_MIN


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def in_rb_bbox(lat: float, lon: float) -> bool:
    return RB_LAT_MIN <= lat <= RB_LAT_MAX and RB_LON_MIN <= lon <= RB_LON_MAX
