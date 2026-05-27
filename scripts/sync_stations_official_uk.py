from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_PATH = ROOT / "station 里程.md"
STATIONS_UK_PATH = ROOT / "data" / "stations" / "stations_official(UK).json"
START_STATION_CODE = "3140"

KM_FRAGMENT = r"(?:\d+\s*)?K(?:\s*\d+)?\s*\+\s*\d+"
UK_VALUE_FRAGMENT = rf"(?P<uk>[^（。\n]*?{KM_FRAGMENT}(?:\s*~\s*{KM_FRAGMENT})?)"

SECTION_PATTERN = re.compile(r"^(?P<title>.+?)\s+\(StationCode:\s*(?P<code>\d+)\)", re.MULTILINE)
UK_PATTERNS = [
    re.compile(rf"中心里程(?:（[^）]+）)?：\s*{UK_VALUE_FRAGMENT}"),
    re.compile(rf"站房中心里程(?:則)?定錨於\s*{UK_VALUE_FRAGMENT}"),
    re.compile(rf"基地內部里程：\s*{UK_VALUE_FRAGMENT}"),
    re.compile(rf"主線貫通里程：\s*{UK_VALUE_FRAGMENT}"),
    re.compile(rf"法定終點里程：\s*{UK_VALUE_FRAGMENT}"),
    re.compile(rf"實體終點里程：\s*{UK_VALUE_FRAGMENT}"),
    re.compile(rf"工程里程原點：\s*{UK_VALUE_FRAGMENT}"),
    re.compile(rf"法定起算原點：\s*{UK_VALUE_FRAGMENT}"),
]


def _normalize_uk(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _extract_station_uk(section_text: str) -> str | None:
    for pattern in UK_PATTERNS:
        match = pattern.search(section_text)
        if match is not None:
            return _normalize_uk(match.group("uk"))
    return None


def extract_station_uk_lookup(markdown_text: str) -> dict[str, str]:
    matches = list(SECTION_PATTERN.finditer(markdown_text))
    lookup: dict[str, str] = {}

    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown_text)
        section_text = markdown_text[start:end]
        uk_value = _extract_station_uk(section_text)
        if uk_value is None:
            continue
        lookup[match.group("code")] = uk_value

    return lookup


def apply_station_uk_values(
    payload: dict[str, Any],
    uk_lookup: dict[str, str],
    *,
    start_station_code: str = START_STATION_CODE,
) -> tuple[dict[str, Any], list[str]]:
    stations = payload.get("stations", [])
    started = False
    missing_codes: list[str] = []
    updated_stations: list[dict[str, Any]] = []

    for raw_station in stations:
        station = dict(raw_station)
        station_code = str(station.get("stationCode") or "")
        if station_code == start_station_code:
            started = True

        if started:
            uk_value = uk_lookup.get(station_code)
            if uk_value is None:
                missing_codes.append(station_code)
            else:
                station["UK"] = uk_value

        updated_stations.append(station)

    if not started:
        raise ValueError(f"Start station code {start_station_code} not found in stations payload")

    updated_payload = {
        **payload,
        "metadata": {
            **payload.get("metadata", {}),
            "note": "Raw station reference dataset with UK engineering-mileage enrichment populated from station 里程.md where curated station notes are available.",
        },
        "stations": updated_stations,
    }
    return updated_payload, missing_codes


def main() -> None:
    markdown_text = MARKDOWN_PATH.read_text(encoding="utf-8")
    payload = json.loads(STATIONS_UK_PATH.read_text(encoding="utf-8"))

    uk_lookup = extract_station_uk_lookup(markdown_text)
    updated_payload, missing_codes = apply_station_uk_values(payload, uk_lookup)
    if missing_codes:
        preview = ", ".join(missing_codes[:10])
        raise RuntimeError(
            f"Missing UK values in station 里程.md for {len(missing_codes)} station codes from {START_STATION_CODE} onward: {preview}"
        )

    STATIONS_UK_PATH.write_text(json.dumps(updated_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "updated_station_count": len(updated_payload.get("stations", [])),
                "uk_lookup_count": len(uk_lookup),
                "start_station_code": START_STATION_CODE,
                "output_path": str(STATIONS_UK_PATH),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()