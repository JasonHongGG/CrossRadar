from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter

from backend.app.config import get_settings
from backend.app.dependencies import get_crossing_catalog_service


router = APIRouter(prefix="/system", tags=["system"])


def _file_meta(path: Path) -> dict:
    if not path.exists():
        return {
            "path": str(path),
            "exists": False,
            "updated_at": None,
            "size_bytes": 0,
        }

    stat = path.stat()
    return {
        "path": str(path),
        "exists": True,
        "updated_at": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
        "size_bytes": stat.st_size,
    }


@router.get("/overview")
async def get_overview() -> dict:
    settings = get_settings()
    catalog = get_crossing_catalog_service()
    dataset = await catalog.load()
    full_dataset = await catalog.load_full()
    features = dataset.get("features", [])
    full_features = full_dataset.get("features", [])

    confidence_counts = {"high": 0, "medium": 0, "low": 0}
    mapped_count = 0
    counties: set[str] = set()
    for feature in features:
        properties = feature.get("properties", {})
        confidence = properties.get("geolocation_confidence")
        if confidence in confidence_counts:
            confidence_counts[confidence] += 1
        if feature.get("geometry") is not None:
            mapped_count += 1
        county = properties.get("county")
        if county:
            counties.add(county)

    return {
        "app": {
            "name": settings.app_name,
            "env": settings.app_env,
        },
        "dataset": {
            **dataset.get("metadata", {}),
            "feature_count": len(features),
            "mapped_feature_count": mapped_count,
            "full_feature_count": len(full_features),
            "county_count": len(counties),
            "confidence_counts": confidence_counts,
            "curated_file": _file_meta(settings.curated_crossings_geojson_path),
            "full_file": _file_meta(settings.full_crossings_geojson_path),
            "tainan_curated_file": _file_meta(settings.curated_tainan_crossings_geojson_path),
            "tainan_official_file": _file_meta(settings.official_tainan_crossings_json_path),
        },
        "cache": {
            "official_crossings": _file_meta(settings.official_crossings_json_path),
            "osm_raw": _file_meta(settings.osm_raw_json_path),
            "osm_geojson": _file_meta(settings.osm_geojson_path),
            "stations": _file_meta(settings.station_cache_path),
            "timetables": _file_meta(settings.timetable_cache_path),
        },
    }
