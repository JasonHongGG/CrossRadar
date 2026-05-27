from __future__ import annotations

from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, Query

from backend.app.dependencies import (
    get_crossing_catalog_service,
    get_manual_mapping_service,
    get_osm_enricher,
    get_station_graph_service,
)


router = APIRouter(prefix="/crossings", tags=["crossings"])


class ManualMappingPayload(BaseModel):
    osm_id: int = Field(ge=1)
    note: str | None = None


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


@router.get("/osm")
async def list_osm_crossings(
    limit: int = Query(default=5000, ge=1, le=10000),
) -> dict:
    osm_enricher = get_osm_enricher()
    dataset = await osm_enricher.build_geojson(force_refresh=False)
    return {
        "type": dataset.get("type", "FeatureCollection"),
        "metadata": dataset.get("metadata", {}),
        "features": dataset.get("features", [])[:limit],
    }


@router.get("/manual-review")
async def list_manual_review_entries(include_resolved: bool = Query(default=True)) -> dict:
    service = get_manual_mapping_service()
    return await service.list_review_entries(include_resolved=include_resolved)


@router.get("/stations")
async def list_stations(
    limit: int = Query(default=5000, ge=1, le=10000),
) -> dict:
    station_graph = get_station_graph_service()
    stations = await station_graph.list_station_summaries(limit=limit)
    return {
        "count": len(stations),
        "features": stations,
    }


@router.put("/manual-mappings/{crossing_id}")
async def save_manual_mapping(crossing_id: str, payload: ManualMappingPayload) -> dict:
    service = get_manual_mapping_service()
    try:
        return await service.save_mapping(crossing_id, payload.osm_id, note=payload.note)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/manual-mappings/{crossing_id}")
async def delete_manual_mapping(crossing_id: str) -> dict:
    service = get_manual_mapping_service()
    return await service.delete_mapping(crossing_id)


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


@router.get("/{crossing_id}/ratio-explanation")
async def get_crossing_ratio_explanation(crossing_id: str) -> dict:
    catalog = get_crossing_catalog_service()
    station_graph = get_station_graph_service()
    feature = await catalog.get_crossing(crossing_id)
    if feature is None:
        raise HTTPException(status_code=404, detail="Crossing not found")

    properties = dict(feature.get("properties", {}))
    if feature.get("geometry") is not None:
        coordinates = feature["geometry"]["coordinates"]
        properties["geometry"] = {"lon": coordinates[0], "lat": coordinates[1]}

    return await station_graph.explain_crossing_properties(properties)
