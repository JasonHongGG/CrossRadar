from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.app.config import get_settings


TAINAN = "臺南市"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _normalize_text(value: str | None) -> str:
    return "".join(str(value or "").replace("台", "臺").split())


def _station_is_in_tainan(station: dict[str, Any]) -> bool:
    return _normalize_text(station.get("stationAddrTw")).startswith(TAINAN)


def export_station_datasets() -> dict[str, int]:
    settings = get_settings()
    stations = _read_json(settings.station_source_json_path)
    tainan_stations = [station for station in stations if _station_is_in_tainan(station)]

    stations_payload = {
        "metadata": {
            "source": str(settings.station_source_json_path),
            "count": len(stations),
            "note": "Raw station reference dataset with no engineering-mileage enrichment applied.",
        },
        "stations": stations,
    }
    tainan_payload = {
        "metadata": {
            "source": str(settings.station_source_json_path),
            "scope_county": TAINAN,
            "count": len(tainan_stations),
            "note": "Subset of raw station reference rows whose Taiwanese address starts with 臺南市.",
        },
        "stations": tainan_stations,
    }

    _write_json(settings.stations_official_json_path, stations_payload)
    _write_json(settings.tainan_stations_json_path, tainan_payload)
    return {
        "stations": len(stations),
        "tainan_stations": len(tainan_stations),
    }


def export_crossing_subsets() -> dict[str, int]:
    settings = get_settings()
    counts: dict[str, int] = {}

    if settings.official_crossings_json_path.exists():
        official = _read_json(settings.official_crossings_json_path)
        official_tainan = [
            crossing
            for crossing in official.get("crossings", [])
            if _normalize_text(crossing.get("county")) == TAINAN
        ]
        _write_json(
            settings.official_tainan_crossings_json_path,
            {
                "metadata": {
                    "source": str(settings.official_crossings_json_path),
                    "scope_county": TAINAN,
                    "count": len(official_tainan),
                    "full_count": len(official.get("crossings", [])),
                },
                "crossings": official_tainan,
            },
        )
        counts["official_tainan_crossings"] = len(official_tainan)

    if settings.curated_crossings_geojson_path.exists():
        curated = _read_json(settings.curated_crossings_geojson_path)
        curated_tainan = [
            feature
            for feature in curated.get("features", [])
            if _normalize_text(feature.get("properties", {}).get("county")) == TAINAN
        ]
        _write_json(
            settings.curated_tainan_crossings_geojson_path,
            {
                "type": "FeatureCollection",
                "metadata": {
                    **curated.get("metadata", {}),
                    "scope_county": TAINAN,
                    "feature_count": len(curated_tainan),
                    "source_feature_count": len(curated.get("features", [])),
                },
                "features": curated_tainan,
            },
        )
        counts["active_tainan_crossings"] = len(curated_tainan)

    return counts


def main() -> None:
    counts = {}
    counts.update(export_station_datasets())
    counts.update(export_crossing_subsets())
    for key, value in sorted(counts.items()):
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()