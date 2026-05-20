from __future__ import annotations

import re
from datetime import UTC, date, datetime
from math import atan2, cos, radians, sin, sqrt
from zoneinfo import ZoneInfo

from shapely.geometry import LineString, Point


TAIPEI_TZ = ZoneInfo("Asia/Taipei")
KM_MARKER_PATTERN = re.compile(r"^(?P<prefix>[A-Z]*?)K(?P<km>\d+)\+(?P<meter>\d+)$")


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = value.strip()
    normalized = normalized.replace("臺", "台")
    normalized = re.sub(r"\s+", "", normalized)
    normalized = normalized.replace("（", "(").replace("）", ")")
    normalized = re.sub(r"\([^)]*\)", "", normalized)
    normalized = re.sub(r"[^\w\u4e00-\u9fff]+", "", normalized)
    return normalized.casefold()


def parse_km_marker(raw_value: str | None) -> dict[str, int | str | None]:
    if not raw_value:
        return {"km_prefix": None, "km_value_meters": None}
    match = KM_MARKER_PATTERN.match(raw_value.strip())
    if not match:
        return {"km_prefix": None, "km_value_meters": None}
    km_prefix = match.group("prefix") or ""
    km_value_meters = int(match.group("km")) * 1000 + int(match.group("meter"))
    return {"km_prefix": km_prefix, "km_value_meters": km_value_meters}


def split_station_pair(value: str | None) -> tuple[str | None, str | None]:
    if not value:
        return (None, None)
    for separator in ("-", "－", "–", "—", "~", "～"):
        if separator in value:
            parts = [part.strip() for part in value.split(separator, maxsplit=1)]
            if len(parts) == 2:
                return (parts[0] or None, parts[1] or None)
    return (None, None)


def slugify_crossing(name: str, line: str, km_marker: str) -> str:
    parts = [normalize_text(name), normalize_text(line), normalize_text(km_marker)]
    return "-".join(part for part in parts if part)[:128]


def parse_time_on_date(train_date: date, time_text: str | None) -> datetime | None:
    if not time_text:
        return None
    clock = None
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            clock = datetime.strptime(time_text, fmt).time()
            break
        except ValueError:
            continue
    if clock is None:
        return None
    return datetime.combine(train_date, clock, tzinfo=TAIPEI_TZ)


def now_taipei() -> datetime:
    return datetime.now(TAIPEI_TZ)


def to_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI_TZ)
    return dt.astimezone(UTC)


def point_ratio_between_stations(
    start_lon: float,
    start_lat: float,
    end_lon: float,
    end_lat: float,
    point_lon: float,
    point_lat: float,
) -> float:
    line = LineString([(start_lon, start_lat), (end_lon, end_lat)])
    if line.length == 0:
        return 0.5
    ratio = line.project(Point(point_lon, point_lat), normalized=True)
    return float(max(0.0, min(1.0, ratio)))


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_m = 6_371_000.0
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    a = sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return radius_m * c


def safe_int(value: object, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default
