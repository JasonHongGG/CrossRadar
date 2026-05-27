from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "data" / "stations" / "stations_official_uk_change_report.json"
STATION_CHAINAGE_PATH = ROOT / "data" / "stations" / "station_engineering_chainage.json"
CROSSINGS_PATH = ROOT / "data" / "crossings" / "crossings_curated.geojson"
CHAINAGE_SCRIPT_PATH = ROOT / "scripts" / "generate_station_engineering_chainage.py"

LINE_ALIASES = {
    "台中線": "山線",
    "臺中線": "山線",
    "海岸線": "海線",
    "縱貫線北段": "縱貫線",
    "縱貫線南段": "縱貫線",
    "臺東線": "台東線",
}

STATION_ALIASES = {
    "中州": "中洲",
    "侯硐": "猴硐",
    "車程": "車埕",
    "安通": "東里",
    "鳳鳴火車站": "鳳鳴",
}

UK_PATTERN = re.compile(r"K\s*(\d+)\s*\+\s*(\d+)")


def normalize_line(name: str | None) -> str | None:
    if not name:
        return None
    return LINE_ALIASES.get(name, name)


def load_route_definitions():
    spec = importlib.util.spec_from_file_location(
        "generate_station_engineering_chainage", CHAINAGE_SCRIPT_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {CHAINAGE_SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.route_definitions()


def canonicalize_station(name: str | None, known_names: set[str]) -> str | None:
    if not name:
        return None
    if name in STATION_ALIASES:
        return STATION_ALIASES[name]
    if name in known_names:
        return name
    alt = name.replace("台", "臺")
    if alt in known_names:
        return alt
    alt = name.replace("臺", "台")
    if alt in known_names:
        return alt
    return STATION_ALIASES.get(name, name)


def parse_uk_value(raw: str) -> int:
    match = UK_PATTERN.search(raw)
    if not match:
        raise ValueError(f"Unable to parse UK value: {raw}")
    km, meters = match.groups()
    return int(km) * 1000 + int(meters)


def crossing_payload(feature: dict) -> dict:
    props = feature["properties"]
    return {
        "name": props["name"],
        "station_pair": props["station_pair_text"],
        "uk_value": props["km_marker"].replace("K", "K").replace("+", " + "),
        "km_value_meters": props["km_value_meters"],
    }


def build_route_index():
    route_definitions = load_route_definitions()
    known_names = {
        station_name.replace("台", "臺")
        for route in route_definitions
        for station_name in route.stations
    }
    routes_by_line: dict[str, list[dict]] = {}
    for route in route_definitions:
        normalized_lines = {normalize_line(line) for line in route.lines}
        normalized_stations = [canonicalize_station(name, known_names) for name in route.stations]
        route_info = {
            "key": route.key,
            "route_name": route.route_name,
            "stations": normalized_stations,
        }
        for line in normalized_lines:
            routes_by_line.setdefault(line, []).append(route_info)
    return routes_by_line, known_names


def build_crossing_index(known_names: set[str]):
    features = json.loads(CROSSINGS_PATH.read_text(encoding="utf-8"))["features"]
    crossings_by_line: dict[str, list[dict]] = {}
    for feature in features:
        props = feature["properties"]
        normalized_line = normalize_line(props.get("line"))
        km_value_meters = props.get("km_value_meters")
        if not normalized_line:
            continue
        if km_value_meters is None:
            continue
        entry = {
            "feature": feature,
            "km_value_meters": km_value_meters,
            "station_a": canonicalize_station(props.get("station_a_name"), known_names),
            "station_b": canonicalize_station(props.get("station_b_name"), known_names),
        }
        crossings_by_line.setdefault(normalized_line, []).append(entry)
    for items in crossings_by_line.values():
        items.sort(key=lambda item: item["km_value_meters"])
    return crossings_by_line


def select_route(routes_by_line: dict[str, list[dict]], line: str, station_name: str) -> dict | None:
    for route in routes_by_line.get(line, []):
        if station_name in route["stations"]:
            return route
    return None


def pair_match(crossing: dict, station_a: str | None, station_b: str | None) -> bool:
    if not station_a or not station_b:
        return False
    pair = {crossing["station_a"], crossing["station_b"]}
    return pair == {station_a, station_b}


def nearest_crossings(
    crossings_for_line: list[dict],
    station_name: str,
    target_meters: int,
    route: dict | None,
) -> tuple[dict | None, dict | None]:
    previous_station = None
    next_station = None
    if route is not None:
        station_index = route["stations"].index(station_name)
        if station_index > 0:
            previous_station = route["stations"][station_index - 1]
        if station_index + 1 < len(route["stations"]):
            next_station = route["stations"][station_index + 1]

    previous_segment = [
        crossing
        for crossing in crossings_for_line
        if crossing["km_value_meters"] < target_meters
        and pair_match(crossing, previous_station, station_name)
    ]
    next_segment = [
        crossing
        for crossing in crossings_for_line
        if crossing["km_value_meters"] > target_meters
        and pair_match(crossing, station_name, next_station)
    ]

    previous_crossing = previous_segment[-1] if previous_segment else None
    next_crossing = next_segment[0] if next_segment else None

    if previous_crossing is None:
        for crossing in reversed(crossings_for_line):
            if crossing["km_value_meters"] < target_meters:
                previous_crossing = crossing
                break

    if next_crossing is None:
        for crossing in crossings_for_line:
            if crossing["km_value_meters"] > target_meters:
                next_crossing = crossing
                break

    return previous_crossing, next_crossing


def update_entry(
    entry: dict,
    target_field: str,
    routes_by_line: dict[str, list[dict]],
    crossings_by_line: dict[str, list[dict]],
    known_names: set[str],
) -> bool:
    line = normalize_line(entry["line"])
    station_name = canonicalize_station(entry["stationName"], known_names)
    target_meters = parse_uk_value(entry[target_field])
    route = select_route(routes_by_line, line, station_name)
    crossings_for_line = crossings_by_line.get(line, [])
    previous_crossing, next_crossing = nearest_crossings(
        crossings_for_line=crossings_for_line,
        station_name=station_name,
        target_meters=target_meters,
        route=route,
    )

    new_previous = crossing_payload(previous_crossing["feature"]) if previous_crossing else None
    new_next = crossing_payload(next_crossing["feature"]) if next_crossing else None

    changed = entry.get("previous_crossing") != new_previous or entry.get("next_crossing") != new_next
    entry["previous_crossing"] = new_previous
    entry["next_crossing"] = new_next
    return changed


def main() -> None:
    routes_by_line, known_names = build_route_index()
    crossings_by_line = build_crossing_index(known_names)
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    changed_entries: list[str] = []
    for entry in report["changes"]:
        if update_entry(entry, "new_value", routes_by_line, crossings_by_line, known_names):
            changed_entries.append(f"change:{entry['stationCode']}:{entry['stationName']}")

    for entry in report["remaining_invalid"]:
        if update_entry(entry, "current_value", routes_by_line, crossings_by_line, known_names):
            changed_entries.append(f"invalid:{entry['stationCode']}:{entry['stationName']}")

    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "updated_entries": len(changed_entries),
                "entries": changed_entries,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()