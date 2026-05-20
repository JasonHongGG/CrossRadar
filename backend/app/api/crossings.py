from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.app.dependencies import get_crossing_catalog_service, get_station_graph_service


router = APIRouter(prefix="/crossings", tags=["crossings"])


@router.get("")
async def list_crossings(
    county: str | None = Query(default=None),
    confidence: str | None = Query(default=None),
    mapped_only: bool = Query(default=True),
    limit: int = Query(default=500, ge=1, le=5000),
) -> dict:
    catalog = get_crossing_catalog_service()
    dataset = await catalog.load()
    features = await catalog.list_crossings(
        county=county,
        confidence=confidence,
        mapped_only=mapped_only,
        limit=limit,
    )
    counties = sorted(
        {
            feature.get("properties", {}).get("county")
            for feature in dataset.get("features", [])
            if feature.get("properties", {}).get("county")
        }
    )
    return {
        "metadata": dataset.get("metadata", {}),
        "counties": counties,
        "features": features,
    }


@router.get("/{crossing_id}")
async def get_crossing(crossing_id: str) -> dict:
    catalog = get_crossing_catalog_service()
    station_graph = get_station_graph_service()
    feature = await catalog.get_crossing(crossing_id)
    if feature is None:
        raise HTTPException(status_code=404, detail="Crossing not found")

    properties = dict(feature.get("properties", {}))
    if feature.get("geometry") is not None:
        coordinates = feature["geometry"]["coordinates"]
        properties["geometry"] = {"lon": coordinates[0], "lat": coordinates[1]}
    enriched = await station_graph.enrich_crossing_properties(properties)
    feature["properties"] = enriched
    return feature
