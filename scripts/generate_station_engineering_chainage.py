from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STATIONS_PATH = ROOT / "車站基本資料集.json"
CROSSINGS_PATH = ROOT / "data" / "crossings" / "crossings_curated.geojson"
OUTPUT_PATH = ROOT / "data" / "stations" / "station_engineering_chainage.json"

TRA_CROSSING_SOURCE = "https://www.railway.gov.tw/tra-tip-web/adr/about-public-info-6"
TAINAN_PROJECT_SOURCE = "https://www.rb.gov.tw/zh-TW/SREO/SREO_94/SREO_95/20251017_154907/"

DIRECT_STATION_CHAINAGES = {
    ("western_south", "臺南"): {
        "line": "縱貫線",
        "route_name": "縱貫線南段",
        "meters": 357_800,
        "km_marker": "K357+800",
        "method": "official_project_station_chainage",
        "confidence": "verified",
        "estimated_error_meters": 0,
        "sources": [
            {
                "title": "交通部鐵道局臺南市區鐵路地下化計畫頁面",
                "url": TAINAN_PROJECT_SOURCE,
                "quote": "臺南站(K357+800)",
            }
        ],
        "notes": ["Official Railway Bureau project page gives the station chainage directly."],
    }
}


COUNTY_NAMES = [
    "基隆市",
    "臺北市",
    "新北市",
    "桃園市",
    "新竹縣",
    "新竹市",
    "苗栗縣",
    "臺中市",
    "彰化縣",
    "南投縣",
    "雲林縣",
    "嘉義縣",
    "嘉義市",
    "臺南市",
    "高雄市",
    "屏東縣",
    "宜蘭縣",
    "花蓮縣",
    "臺東縣",
]


@dataclass(frozen=True)
class StationPoint:
    code: str
    name: str
    english_name: str
    address: str
    lat: float
    lon: float
    x: float
    y: float


@dataclass(frozen=True)
class RouteStation:
    station: StationPoint
    s_m: float


@dataclass(frozen=True)
class RouteDefinition:
    key: str
    route_name: str
    lines: tuple[str, ...]
    stations: tuple[str, ...]
    max_anchor_perp_m: float = 3_000.0
    max_extrapolate_m: float = 20_000.0
    one_anchor_extrapolate_m: float = 8_000.0


@dataclass(frozen=True)
class CrossingAnchor:
    crossing_id: str
    name: str
    line: str
    km_marker: str
    km_value_meters: float
    county: str
    lat: float
    lon: float
    match_score: float
    match_method: str | None
    geolocation_confidence: str | None
    manual_mapping_applied: bool
    station_pair_text: str | None
    source_page: int | None
    source_row_index: int | None


@dataclass(frozen=True)
class ProjectedAnchor:
    anchor: CrossingAnchor
    s_m: float
    perp_m: float


def parse_gps(raw: str | None) -> tuple[float, float] | None:
    if not raw or not raw.strip():
        return None
    parts = raw.split()
    if len(parts) != 2:
        return None
    return float(parts[0]), float(parts[1])


def to_xy(lat: float, lon: float) -> tuple[float, float]:
    earth_radius_m = 6_371_000.0
    lat0 = math.radians(23.7)
    return (
        math.radians(lon) * earth_radius_m * math.cos(lat0),
        math.radians(lat) * earth_radius_m,
    )


def meters_to_marker(meters: float) -> str:
    rounded = int(round(meters))
    sign = "-" if rounded < 0 else ""
    rounded = abs(rounded)
    return f"{sign}K{rounded // 1000:03d}+{rounded % 1000:03d}"


def normalize_county(value: str | None) -> str | None:
    if not value:
        return None
    compact = "".join(value.split())
    return compact.replace("台", "臺")


def address_county(address: str) -> str | None:
    compact = "".join(address.split()).replace("台", "臺")
    for county in COUNTY_NAMES:
        if compact.startswith(county):
            return county
    return None


def build_county_bounds(stations: list[StationPoint]) -> dict[str, tuple[float, float, float, float]]:
    grouped: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for station in stations:
        county = address_county(station.address)
        if county:
            grouped[county].append((station.lat, station.lon))

    bounds: dict[str, tuple[float, float, float, float]] = {}
    for county, points in grouped.items():
        lats = [point[0] for point in points]
        lons = [point[1] for point in points]
        bounds[county] = (
            min(lats) - 0.35,
            max(lats) + 0.35,
            min(lons) - 0.35,
            max(lons) + 0.35,
        )
    return bounds


def county_matches_coordinate(anchor: CrossingAnchor, bounds: dict[str, tuple[float, float, float, float]]) -> bool:
    county = normalize_county(anchor.county)
    if not county:
        return False
    county_bounds = bounds.get(county)
    if not county_bounds:
        return True
    min_lat, max_lat, min_lon, max_lon = county_bounds
    return min_lat <= anchor.lat <= max_lat and min_lon <= anchor.lon <= max_lon


def load_stations() -> list[StationPoint]:
    raw_stations = json.loads(STATIONS_PATH.read_text(encoding="utf-8"))
    stations: list[StationPoint] = []
    for raw in raw_stations:
        gps = parse_gps(raw.get("gps"))
        if gps is None:
            continue
        lat, lon = gps
        x, y = to_xy(lat, lon)
        stations.append(
            StationPoint(
                code=raw["stationCode"],
                name=raw["stationName"],
                english_name=raw.get("stationEName") or raw.get("ename") or "",
                address=raw.get("stationAddrTw") or "",
                lat=lat,
                lon=lon,
                x=x,
                y=y,
            )
        )
    return stations


def load_crossing_anchors(county_bounds: dict[str, tuple[float, float, float, float]]) -> tuple[list[CrossingAnchor], Counter[str]]:
    geojson = json.loads(CROSSINGS_PATH.read_text(encoding="utf-8"))
    anchors: list[CrossingAnchor] = []
    rejected: Counter[str] = Counter()

    for feature in geojson["features"]:
        properties = feature["properties"]
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates")
        if not coordinates or properties.get("km_value_meters") is None:
            rejected["missing_geometry_or_k"] += 1
            continue

        match_score = float(properties.get("match_score") or 0.0)
        manual_mapping_applied = bool(properties.get("manual_mapping_applied"))
        is_named_node_match = properties.get("match_method") == "node_name" and match_score >= 60.0
        if not manual_mapping_applied and match_score < 90.0 and not is_named_node_match:
            rejected["weak_osm_match"] += 1
            continue
        if not properties.get("osm_rail_names"):
            rejected["missing_osm_rail_name"] += 1
            continue

        anchor = CrossingAnchor(
            crossing_id=properties.get("crossing_id") or f"{properties.get('name')}-{properties.get('line')}-{properties.get('km_marker')}",
            name=properties.get("name") or "",
            line=properties.get("line") or "",
            km_marker=properties.get("km_marker") or meters_to_marker(float(properties["km_value_meters"])),
            km_value_meters=float(properties["km_value_meters"]),
            county=normalize_county(properties.get("county")) or "",
            lat=float(coordinates[1]),
            lon=float(coordinates[0]),
            match_score=match_score,
            match_method=properties.get("match_method"),
            geolocation_confidence=properties.get("geolocation_confidence"),
            manual_mapping_applied=manual_mapping_applied,
            station_pair_text=properties.get("station_pair_text"),
            source_page=properties.get("source_page"),
            source_row_index=properties.get("source_row_index"),
        )
        if not county_matches_coordinate(anchor, county_bounds):
            rejected["county_coordinate_mismatch"] += 1
            continue
        anchors.append(anchor)

    return anchors, rejected


def route_definitions() -> list[RouteDefinition]:
    return [
        RouteDefinition(
            key="western_north",
            route_name="縱貫線北段",
            lines=("縱貫線", "縱貫線北段"),
            stations=(
                "基隆",
                "三坑",
                "八堵",
                "七堵",
                "百福",
                "五堵",
                "汐止",
                "汐科",
                "南港",
                "松山",
                "臺北",
                "萬華",
                "板橋",
                "浮洲",
                "樹林",
                "南樹林",
                "山佳",
                "鶯歌",
                "鳳鳴",
                "桃園",
                "內壢",
                "中壢",
                "埔心",
                "楊梅",
                "富岡",
                "新富",
                "北湖",
                "湖口",
                "新豐",
                "竹北",
                "北新竹",
                "新竹",
                "三姓橋",
                "香山",
                "崎頂",
                "竹南",
            ),
        ),
        RouteDefinition(
            key="western_coast",
            route_name="縱貫線海線",
            lines=("縱貫線", "縱貫線北段"),
            stations=(
                "竹南",
                "談文",
                "大山",
                "後龍",
                "龍港",
                "白沙屯",
                "新埔",
                "通霄",
                "苑裡",
                "日南",
                "大甲",
                "臺中港",
                "清水",
                "沙鹿",
                "龍井",
                "大肚",
                "追分",
                "彰化",
            ),
        ),
        RouteDefinition(
            key="western_mountain",
            route_name="臺中線 / 縱貫線山線",
            lines=("台中線", "縱貫線", "縱貫線北段"),
            stations=(
                "竹南",
                "造橋",
                "豐富",
                "苗栗",
                "南勢",
                "銅鑼",
                "三義",
                "泰安",
                "后里",
                "豐原",
                "栗林",
                "潭子",
                "頭家厝",
                "松竹",
                "太原",
                "精武",
                "臺中",
                "五權",
                "大慶",
                "烏日",
                "新烏日",
                "成功",
                "彰化",
            ),
            max_anchor_perp_m=4_000.0,
            max_extrapolate_m=25_000.0,
        ),
        RouteDefinition(
            key="western_south",
            route_name="縱貫線南段",
            lines=("縱貫線", "縱貫線北段"),
            stations=(
                "彰化",
                "花壇",
                "大村",
                "員林",
                "永靖",
                "社頭",
                "田中",
                "二水",
                "林內",
                "石榴",
                "斗六",
                "斗南",
                "石龜",
                "大林",
                "民雄",
                "嘉北",
                "嘉義",
                "水上",
                "南靖",
                "後壁",
                "新營",
                "柳營",
                "林鳳營",
                "隆田",
                "拔林",
                "善化",
                "南科",
                "新市",
                "永康",
                "大橋",
                "臺南",
                "保安",
                "仁德",
                "中洲",
                "大湖",
                "路竹",
                "岡山",
                "橋頭",
                "楠梓",
                "新左營",
                "左營",
                "內惟",
                "美術館",
                "鼓山",
                "三塊厝",
                "高雄",
            ),
        ),
        RouteDefinition(
            key="neiwan",
            route_name="內灣線",
            lines=("內灣線",),
            stations=(
                "新竹",
                "北新竹",
                "千甲",
                "新莊",
                "竹中",
                "上員",
                "榮華",
                "竹東",
                "橫山",
                "九讚頭",
                "合興",
                "富貴",
                "內灣",
            ),
            max_extrapolate_m=12_000.0,
        ),
        RouteDefinition(
            key="liujia",
            route_name="六家線",
            lines=("六家線",),
            stations=("竹中", "六家"),
            max_extrapolate_m=0.0,
            one_anchor_extrapolate_m=0.0,
        ),
        RouteDefinition(
            key="jiji",
            route_name="集集線",
            lines=("集集線",),
            stations=("二水", "源泉", "濁水", "龍泉", "集集", "水里", "車埕"),
            max_extrapolate_m=10_000.0,
        ),
        RouteDefinition(
            key="shalun",
            route_name="沙崙線",
            lines=("沙崙線",),
            stations=("中洲", "長榮大學", "沙崙"),
            max_extrapolate_m=0.0,
            one_anchor_extrapolate_m=0.0,
        ),
        RouteDefinition(
            key="pingtung",
            route_name="屏東線",
            lines=("屏東線",),
            stations=(
                "高雄",
                "民族",
                "科工館",
                "正義",
                "鳳山",
                "後庄",
                "九曲堂",
                "六塊厝",
                "屏東",
                "歸來",
                "麟洛",
                "西勢",
                "竹田",
                "潮州",
                "崁頂",
                "南州",
                "鎮安",
                "林邊",
                "佳冬",
                "東海",
                "枋寮",
            ),
            max_anchor_perp_m=4_000.0,
            max_extrapolate_m=30_000.0,
        ),
        RouteDefinition(
            key="south_link",
            route_name="南迴線",
            lines=("南迴線",),
            stations=(
                "枋寮",
                "加祿",
                "內獅",
                "枋山",
                "枋野",
                "大武",
                "瀧溪",
                "金崙",
                "太麻里",
                "知本",
                "康樂",
                "臺東",
            ),
            max_anchor_perp_m=8_000.0,
            max_extrapolate_m=35_000.0,
        ),
        RouteDefinition(
            key="taitung",
            route_name="臺東線",
            lines=("台東線",),
            stations=(
                "花蓮",
                "吉安",
                "志學",
                "平和",
                "壽豐",
                "豐田",
                "林榮新光",
                "南平",
                "鳳林",
                "萬榮",
                "光復",
                "大富",
                "富源",
                "瑞穗",
                "三民",
                "玉里",
                "東里",
                "東竹",
                "富里",
                "池上",
                "海端",
                "關山",
                "瑞和",
                "瑞源",
                "鹿野",
                "山里",
                "臺東",
            ),
            max_anchor_perp_m=5_000.0,
            max_extrapolate_m=20_000.0,
        ),
        RouteDefinition(
            key="north_link",
            route_name="北迴線",
            lines=("北迴線",),
            stations=(
                "蘇澳新",
                "東澳",
                "南澳",
                "武塔",
                "漢本",
                "和平",
                "和仁",
                "崇德",
                "新城",
                "景美",
                "北埔",
                "花蓮",
            ),
            max_anchor_perp_m=6_000.0,
            max_extrapolate_m=0.0,
            one_anchor_extrapolate_m=90_000.0,
        ),
        RouteDefinition(
            key="yilan",
            route_name="宜蘭線",
            lines=("宜蘭線",),
            stations=(
                "八堵",
                "暖暖",
                "四腳亭",
                "瑞芳",
                "猴硐",
                "三貂嶺",
                "牡丹",
                "雙溪",
                "貢寮",
                "福隆",
                "石城",
                "大里",
                "大溪",
                "龜山",
                "外澳",
                "頭城",
                "頂埔",
                "礁溪",
                "四城",
                "宜蘭",
                "二結",
                "中里",
                "羅東",
                "冬山",
                "新馬",
                "蘇澳新",
                "永樂",
                "蘇澳",
            ),
            max_anchor_perp_m=4_000.0,
            max_extrapolate_m=12_000.0,
        ),
        RouteDefinition(
            key="pingxi",
            route_name="平溪線",
            lines=("平溪線",),
            stations=("三貂嶺", "大華", "十分", "望古", "嶺腳", "平溪", "菁桐"),
            max_anchor_perp_m=6_000.0,
            max_extrapolate_m=0.0,
            one_anchor_extrapolate_m=12_000.0,
        ),
        RouteDefinition(
            key="shenao",
            route_name="深澳線",
            lines=("深澳線",),
            stations=("瑞芳", "海科館", "八斗子"),
            max_anchor_perp_m=6_000.0,
            max_extrapolate_m=8_000.0,
        ),
    ]


def build_route_stations(route: RouteDefinition, station_by_name: dict[str, StationPoint]) -> list[RouteStation]:
    route_stations: list[RouteStation] = []
    total = 0.0
    previous: StationPoint | None = None
    for station_name in route.stations:
        station = station_by_name.get(station_name)
        if station is None:
            continue
        if previous is not None:
            total += math.hypot(station.x - previous.x, station.y - previous.y)
        route_stations.append(RouteStation(station=station, s_m=total))
        previous = station
    return route_stations


def project_to_route(lat: float, lon: float, route_stations: list[RouteStation]) -> tuple[float, float] | None:
    if len(route_stations) < 2:
        return None
    px, py = to_xy(lat, lon)
    best: tuple[float, float] | None = None
    for left, right in zip(route_stations, route_stations[1:]):
        ax, ay = left.station.x, left.station.y
        bx, by = right.station.x, right.station.y
        vx, vy = bx - ax, by - ay
        segment_len = math.hypot(vx, vy)
        if segment_len == 0.0:
            continue
        t = ((px - ax) * vx + (py - ay) * vy) / (segment_len * segment_len)
        clamped_t = max(0.0, min(1.0, t))
        qx = ax + clamped_t * vx
        qy = ay + clamped_t * vy
        perp = math.hypot(px - qx, py - qy)
        route_s = left.s_m + clamped_t * segment_len
        if best is None or perp < best[1]:
            best = route_s, perp
    return best


def build_route_anchors(
    route: RouteDefinition,
    route_stations: list[RouteStation],
    anchors: list[CrossingAnchor],
) -> list[ProjectedAnchor]:
    projected: list[ProjectedAnchor] = []
    allowed_lines = set(route.lines)
    for anchor in anchors:
        if anchor.line not in allowed_lines:
            continue
        projection = project_to_route(anchor.lat, anchor.lon, route_stations)
        if projection is None:
            continue
        route_s, perp = projection
        if perp > route.max_anchor_perp_m:
            continue
        projected.append(ProjectedAnchor(anchor=anchor, s_m=route_s, perp_m=perp))

    projected.sort(key=lambda item: (item.s_m, item.anchor.km_value_meters, item.anchor.crossing_id))
    deduped: list[ProjectedAnchor] = []
    seen: set[tuple[str, str, int]] = set()
    for item in projected:
        key = (item.anchor.name, item.anchor.km_marker, round(item.s_m))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return keep_monotonic_anchors(deduped)


def keep_monotonic_anchors(anchors: list[ProjectedAnchor]) -> list[ProjectedAnchor]:
    if len(anchors) < 3:
        return anchors
    kept: list[ProjectedAnchor] = []
    previous_km = -math.inf
    for index, anchor in enumerate(anchors):
        km = anchor.anchor.km_value_meters
        if km + 1_000 < previous_km:
            continue
        if index + 1 < len(anchors):
            next_km = anchors[index + 1].anchor.km_value_meters
            if next_km + 20_000 < km and index > 0:
                continue
        kept.append(anchor)
        previous_km = max(previous_km, km)
    return kept


def chainage_at_station(
    route: RouteDefinition,
    route_station: RouteStation,
    route_anchors: list[ProjectedAnchor],
) -> dict[str, Any] | None:
    direct = DIRECT_STATION_CHAINAGES.get((route.key, route_station.station.name))
    if direct:
        return {
            "route_key": route.key,
            "route_name": direct["route_name"],
            "line": direct["line"],
            "km_marker": direct["km_marker"],
            "meters": direct["meters"],
            "method": direct["method"],
            "confidence": direct["confidence"],
            "estimated_error_meters": direct["estimated_error_meters"],
            "sources": direct["sources"],
            "anchor_crossings": [],
            "notes": direct["notes"],
        }

    if not route_anchors:
        return None

    station_s = route_station.s_m
    left: ProjectedAnchor | None = None
    right: ProjectedAnchor | None = None
    for anchor in route_anchors:
        if anchor.s_m <= station_s:
            left = anchor
        if anchor.s_m >= station_s:
            right = anchor
            break

    if left is not None and right is not None and left is not right:
        gap = right.s_m - left.s_m
        if gap <= 0.0:
            return None
        ratio = (station_s - left.s_m) / gap
        meters = left.anchor.km_value_meters + ratio * (right.anchor.km_value_meters - left.anchor.km_value_meters)
        nearest_anchor_distance = min(station_s - left.s_m, right.s_m - station_s)
        estimated_error = estimate_error(gap, nearest_anchor_distance, (left.perp_m + right.perp_m) / 2.0, interpolated=True)
        confidence = confidence_for_interpolation(gap, nearest_anchor_distance, estimated_error)
        return chainage_result(
            route=route,
            meters=meters,
            method="interpolated_between_official_crossing_k_anchors",
            confidence=confidence,
            estimated_error_meters=estimated_error,
            anchors=[left, right],
            notes=["Interpolated along a station-polyline route between two official TRA crossing K markers."],
        )

    if len(route_anchors) >= 2:
        if right is None:
            nearest = route_anchors[-1]
            neighbor = next((anchor for anchor in reversed(route_anchors[:-1]) if abs(anchor.s_m - nearest.s_m) > 1.0), None)
        else:
            nearest = route_anchors[0]
            neighbor = next((anchor for anchor in route_anchors[1:] if abs(anchor.s_m - nearest.s_m) > 1.0), None)
        if neighbor is None:
            return None
        extrapolate_distance = abs(station_s - nearest.s_m)
        if extrapolate_distance > route.max_extrapolate_m:
            return None
        slope = (nearest.anchor.km_value_meters - neighbor.anchor.km_value_meters) / (nearest.s_m - neighbor.s_m)
        if not 0.35 <= slope <= 2.5:
            if extrapolate_distance > 1_000 or not 0.1 <= slope <= 3.0:
                return None
        meters = nearest.anchor.km_value_meters + (station_s - nearest.s_m) * slope
        estimated_error = estimate_error(abs(nearest.s_m - neighbor.s_m), extrapolate_distance, nearest.perp_m, interpolated=False)
        confidence = "medium" if extrapolate_distance <= 5_000 and estimated_error <= 1_000 else "low"
        return chainage_result(
            route=route,
            meters=meters,
            method="extrapolated_from_official_crossing_k_anchors",
            confidence=confidence,
            estimated_error_meters=estimated_error,
            anchors=[nearest, neighbor],
            notes=["Extrapolated from the nearest official TRA crossing K markers on the same route."],
        )

    only_anchor = route_anchors[0]
    extrapolate_distance = abs(station_s - only_anchor.s_m)
    if extrapolate_distance > route.one_anchor_extrapolate_m:
        return None
    meters = only_anchor.anchor.km_value_meters + (station_s - only_anchor.s_m)
    estimated_error = int(round(max(1_500.0, extrapolate_distance * 0.3 + only_anchor.perp_m)))
    return chainage_result(
        route=route,
        meters=meters,
        method="single_anchor_route_distance_extrapolation",
        confidence="low",
        estimated_error_meters=estimated_error,
        anchors=[only_anchor],
        notes=["Only one official crossing K marker is available on this route; value is a route-distance extrapolation."],
    )


def estimate_error(gap_m: float, nearest_anchor_distance_m: float, avg_anchor_perp_m: float, *, interpolated: bool) -> int:
    base = 150.0 if interpolated else 500.0
    value = base + gap_m * (0.025 if interpolated else 0.08) + nearest_anchor_distance_m * (0.04 if interpolated else 0.15)
    value += avg_anchor_perp_m * 0.35
    return int(round(max(base, value)))


def confidence_for_interpolation(gap_m: float, nearest_anchor_distance_m: float, estimated_error_meters: int) -> str:
    if gap_m <= 12_000 and nearest_anchor_distance_m <= 5_000 and estimated_error_meters <= 700:
        return "high"
    if gap_m <= 35_000 and nearest_anchor_distance_m <= 15_000 and estimated_error_meters <= 1_800:
        return "medium"
    return "low"


def chainage_result(
    route: RouteDefinition,
    meters: float,
    method: str,
    confidence: str,
    estimated_error_meters: int,
    anchors: list[ProjectedAnchor],
    notes: list[str],
) -> dict[str, Any]:
    rounded_meters = int(round(meters))
    result_notes = list(notes)
    if -250 <= rounded_meters < 0:
        rounded_meters = 0
        result_notes.append("Estimated value falls within 250 m before the route origin; rounded to K000+000 instead of emitting a negative K marker.")
    return {
        "route_key": route.key,
        "route_name": route.route_name,
        "line": route.lines[0],
        "km_marker": meters_to_marker(rounded_meters),
        "meters": rounded_meters,
        "method": method,
        "confidence": confidence,
        "estimated_error_meters": estimated_error_meters,
        "sources": [
            {
                "title": "臺鐵局平交道一覽表",
                "url": TRA_CROSSING_SOURCE,
                "note": "Official crossing K markers are used as engineering-chainage anchors; OSM coordinates are used only to place those anchors on the route geometry.",
            }
        ],
        "anchor_crossings": [anchor_to_json(anchor) for anchor in anchors],
        "notes": result_notes,
    }


def anchor_to_json(projected: ProjectedAnchor) -> dict[str, Any]:
    anchor = projected.anchor
    return {
        "crossing_id": anchor.crossing_id,
        "name": anchor.name,
        "line": anchor.line,
        "km_marker": anchor.km_marker,
        "meters": int(round(anchor.km_value_meters)),
        "county": anchor.county,
        "station_pair_text": anchor.station_pair_text,
        "coordinates": {"lat": anchor.lat, "lon": anchor.lon},
        "route_projection_distance_meters": int(round(projected.perp_m)),
        "source_page": anchor.source_page,
        "source_row_index": anchor.source_row_index,
        "match_score": anchor.match_score,
        "match_method": anchor.match_method,
        "geolocation_confidence": anchor.geolocation_confidence,
        "manual_mapping_applied": anchor.manual_mapping_applied,
    }


def select_primary(chainages: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not chainages:
        return None
    confidence_rank = {"verified": 0, "high": 1, "medium": 2, "low": 3}
    method_rank = {
        "official_project_station_chainage": 0,
        "interpolated_between_official_crossing_k_anchors": 1,
        "extrapolated_from_official_crossing_k_anchors": 2,
        "single_anchor_route_distance_extrapolation": 3,
    }
    return sorted(
        chainages,
        key=lambda item: (
            confidence_rank.get(item["confidence"], 9),
            method_rank.get(item["method"], 9),
            item["estimated_error_meters"],
        ),
    )[0]


def build_dataset() -> dict[str, Any]:
    raw_station_rows = json.loads(STATIONS_PATH.read_text(encoding="utf-8"))
    stations = load_stations()
    station_by_name = {station.name: station for station in stations}
    county_bounds = build_county_bounds(stations)
    anchors, rejected_anchor_counts = load_crossing_anchors(county_bounds)

    routes = route_definitions()
    route_stations_by_key: dict[str, list[RouteStation]] = {}
    route_anchors_by_key: dict[str, list[ProjectedAnchor]] = {}
    route_lookup = {route.key: route for route in routes}

    for route in routes:
        route_stations = build_route_stations(route, station_by_name)
        route_stations_by_key[route.key] = route_stations
        route_anchors_by_key[route.key] = build_route_anchors(route, route_stations, anchors)

    chainages_by_station: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for route_key, route_stations in route_stations_by_key.items():
        route = route_lookup[route_key]
        route_anchors = route_anchors_by_key[route_key]
        for route_station in route_stations:
            result = chainage_at_station(route, route_station, route_anchors)
            if result:
                chainages_by_station[route_station.station.name].append(result)

    station_records = []
    for raw_station in raw_station_rows:
        station_name = raw_station["stationName"]
        station = station_by_name.get(station_name)
        chainages = sorted(
            chainages_by_station.get(station_name, []),
            key=lambda item: (item["route_key"], item["meters"]),
        )
        primary = select_primary(chainages)
        gps = None if station is None else {"lat": station.lat, "lon": station.lon}
        unresolved_notes = ["No reliable official crossing K anchors or direct official station chainage were available for this station route."]
        if station is None:
            unresolved_notes = ["Station has no usable GPS coordinate in the source station list, so route projection was not attempted."]
        station_records.append(
            {
                "station_code": raw_station["stationCode"],
                "station_name_zh": station_name,
                "station_name_en": raw_station.get("stationEName") or raw_station.get("ename") or "",
                "gps": gps,
                "primary_engineering_chainage": primary,
                "engineering_chainages": chainages,
                "status": "resolved" if primary else "unresolved",
                "notes": []
                if primary
                else unresolved_notes,
            }
        )

    method_counts: Counter[str] = Counter()
    confidence_counts: Counter[str] = Counter()
    unresolved = 0
    for record in station_records:
        primary = record["primary_engineering_chainage"]
        if primary is None:
            unresolved += 1
            continue
        method_counts[primary["method"]] += 1
        confidence_counts[primary["confidence"]] += 1

    route_anchor_counts = {
        route.key: {
            "route_name": route.route_name,
            "station_count": len(route_stations_by_key[route.key]),
            "accepted_anchor_count": len(route_anchors_by_key[route.key]),
        }
        for route in routes
    }

    return {
        "metadata": {
            "generated_at": datetime.now(UTC).isoformat(),
            "schema_version": 1,
            "station_source": str(STATIONS_PATH.relative_to(ROOT)).replace("\\", "/"),
            "crossing_anchor_source": str(CROSSINGS_PATH.relative_to(ROOT)).replace("\\", "/"),
            "source_policy": [
                "Do not use TRA operating mileage / 營業里程 in this dataset.",
                "Use direct official station engineering chainage where found.",
                "Otherwise infer from official TRA crossing K markers after coordinate-quality filtering.",
                "OSM data is used only to locate official crossing anchors and never as an authoritative chainage source.",
            ],
            "sources": [
                {
                    "title": "臺鐵局平交道一覽表",
                    "url": TRA_CROSSING_SOURCE,
                    "used_for": "official engineering K marker anchors for crossings",
                },
                {
                    "title": "交通部鐵道局臺南市區鐵路地下化計畫頁面",
                    "url": TAINAN_PROJECT_SOURCE,
                    "used_for": "direct official station/project K anchors including 臺南站 K357+800",
                },
            ],
            "limitations": [
                "Most station values are inferred, not directly published station chainages.",
                "Inferred values use station coordinates and a station-to-station route polyline, so curved tunnel, yard, and junction geometry can exceed the estimated error.",
                "Routes with sparse crossing anchors are marked low confidence or unresolved rather than filled with operating mileage.",
                "Junction stations can have multiple line-specific chainages; see engineering_chainages instead of only the primary value.",
            ],
            "counts": {
                "stations_total": len(station_records),
                "stations_resolved_primary": len(station_records) - unresolved,
                "stations_unresolved": unresolved,
                "primary_methods": dict(sorted(method_counts.items())),
                "primary_confidences": dict(sorted(confidence_counts.items())),
                "crossing_anchors_loaded": len(anchors),
                "crossing_anchors_rejected": dict(sorted(rejected_anchor_counts.items())),
                "route_anchor_counts": route_anchor_counts,
            },
        },
        "stations": station_records,
    }


def main() -> None:
    dataset = build_dataset()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(dataset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    counts = dataset["metadata"]["counts"]
    print(f"Wrote {OUTPUT_PATH.relative_to(ROOT)}")
    print(
        f"Resolved {counts['stations_resolved_primary']} / {counts['stations_total']} stations; "
        f"unresolved {counts['stations_unresolved']}"
    )
    print(f"Primary methods: {counts['primary_methods']}")
    print(f"Primary confidences: {counts['primary_confidences']}")


if __name__ == "__main__":
    main()