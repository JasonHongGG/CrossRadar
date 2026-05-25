from __future__ import annotations

from typing import Any

from backend.app.clients.tdx_tra import TdxTraClient
from backend.app.models.crossing import GeoPoint
from backend.app.services.rail_path import RailPathService
from backend.app.utils import normalize_text, point_ratio_between_stations


STATION_NAME_ALIASES = {
    "中州": "中洲",
    "蘇澳新站": "蘇澳新",
}


class StationGraphService:
    def __init__(self, tdx_client: TdxTraClient, rail_path_service: RailPathService | None = None) -> None:
        self.tdx_client = tdx_client
        self.rail_path_service = rail_path_service
        self._station_lookup: dict[str, dict[str, Any]] | None = None
        self._station_lookup_by_id: dict[str, dict[str, Any]] | None = None

    async def get_station_lookup(self) -> dict[str, dict[str, Any]]:
        if self._station_lookup is not None:
            return self._station_lookup

        stations = await self.tdx_client.get_stations()
        lookup: dict[str, dict[str, Any]] = {}
        lookup_by_id: dict[str, dict[str, Any]] = {}
        for station in stations:
            name = station.get("StationName", {}).get("Zh_tw")
            key = normalize_text(name)
            if key and key not in lookup:
                lookup[key] = station
            station_id = station.get("StationID")
            if station_id:
                lookup_by_id[str(station_id)] = station
        self._station_lookup = lookup
        self._station_lookup_by_id = lookup_by_id
        return lookup

    async def get_station_lookup_by_id(self) -> dict[str, dict[str, Any]]:
        if self._station_lookup_by_id is not None:
            return self._station_lookup_by_id

        await self.get_station_lookup()
        return self._station_lookup_by_id or {}

    async def resolve_station(self, station_name: str | None) -> dict[str, Any] | None:
        if not station_name:
            return None
        lookup = await self.get_station_lookup()
        for candidate in self._candidate_station_keys(station_name):
            station = lookup.get(candidate)
            if station is not None:
                return station
        return None

    def _candidate_station_keys(self, station_name: str) -> list[str]:
        normalized = normalize_text(station_name)
        if not normalized:
            return []

        candidates = [normalized]
        alias = STATION_NAME_ALIASES.get(normalized)
        if alias:
            candidates.append(normalize_text(alias))
        if normalized.endswith("站"):
            candidates.append(normalized[:-1])

        deduped: list[str] = []
        for candidate in candidates:
            if candidate and candidate not in deduped:
                deduped.append(candidate)
        return deduped

    async def enrich_crossing_properties(self, properties: dict[str, Any]) -> dict[str, Any]:
        station_a = await self.resolve_station(properties.get("station_a_name"))
        station_b = await self.resolve_station(properties.get("station_b_name"))

        enriched = dict(properties)
        if station_a:
            enriched["station_a_id"] = station_a.get("StationID")
            enriched["station_a_position"] = station_a.get("StationPosition")
        if station_b:
            enriched["station_b_id"] = station_b.get("StationID")
            enriched["station_b_position"] = station_b.get("StationPosition")

        if station_a and station_b:
            geometry = properties.get("geometry")
            point = GeoPoint.model_validate(geometry) if geometry and isinstance(geometry, dict) else None
            pos_a = station_a.get("StationPosition", {})
            pos_b = station_b.get("StationPosition", {})

            official_ratio = self._official_segment_ratio(properties)
            if official_ratio is not None:
                enriched["official_segment_ratio"] = official_ratio

            path_ratio = None
            if point is not None and self.rail_path_service is not None:
                path_result = self.rail_path_service.compute_segment_ratio(
                    station_a_position=pos_a,
                    station_b_position=pos_b,
                    crossing_point=point,
                    crossing_way_ids=properties.get("osm_rail_way_ids") or None,
                )
                if path_result is not None:
                    path_ratio = path_result.ratio
                    enriched["path_segment_ratio"] = path_result.ratio

            geometry_ratio = None
            if point is not None:
                geometry_ratio = point_ratio_between_stations(
                    pos_a.get("PositionLon"),
                    pos_a.get("PositionLat"),
                    pos_b.get("PositionLon"),
                    pos_b.get("PositionLat"),
                    point.lon,
                    point.lat,
                )
                enriched["geometry_segment_ratio"] = geometry_ratio

            ratio, ratio_source, confidence, confidence_reason = self._select_segment_ratio(
                official_ratio=official_ratio,
                path_ratio=path_ratio,
                geometry_ratio=geometry_ratio,
                properties=properties,
            )
            enriched["segment_ratio"] = ratio
            enriched["ratio_source"] = ratio_source
            enriched["segment_confidence"] = confidence
            enriched["segment_confidence_reason"] = confidence_reason

        return enriched

    def _official_segment_ratio(self, properties: dict[str, Any]) -> float | None:
        crossing_km = properties.get("km_value_meters")
        station_a_km = properties.get("station_a_route_km_meters")
        station_b_km = properties.get("station_b_route_km_meters")
        if crossing_km is None or station_a_km is None or station_b_km is None:
            return None
        span = float(station_b_km) - float(station_a_km)
        if span <= 0:
            return None
        ratio = (float(crossing_km) - float(station_a_km)) / span
        return max(0.0, min(1.0, ratio))

    def _select_segment_ratio(
        self,
        *,
        official_ratio: float | None,
        path_ratio: float | None,
        geometry_ratio: float | None,
        properties: dict[str, Any],
    ) -> tuple[float, str, str, str]:
        ratio_override = properties.get("segment_ratio_override")
        if ratio_override is not None:
            override_source = properties.get("segment_ratio_override_source") or "geometry_projection"
            override_confidence = properties.get("segment_ratio_override_confidence") or "medium"
            override_note = properties.get("segment_ratio_override_note") or "Used an explicit ratio override for this crossing."
            return (
                float(ratio_override),
                str(override_source),
                str(override_confidence),
                str(override_note),
            )
        if official_ratio is not None:
            note = properties.get("station_route_reference_note") or properties.get("station_pair_reference_note") or "Official route reference"
            return (
                official_ratio,
                "official_route_mileage",
                "high",
                f"Used authoritative route-mileage anchors. {note}",
            )
        if path_ratio is not None:
            return (
                path_ratio,
                "osm_path",
                "high",
                "Used OSM rail-way geometry to measure along-track distance from station A to the crossing and from the crossing to station B.",
            )
        if geometry_ratio is not None:
            return (
                geometry_ratio,
                "geometry_projection",
                "medium",
                "Fell back to straight-line projection between station coordinates because no authoritative route-mileage anchor or usable rail path was available.",
            )
        return (0.5, "midpoint", "low", "No crossing geometry was available, so the segment ratio fell back to the midpoint.")
