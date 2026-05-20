from __future__ import annotations

from typing import Any

from backend.app.clients.tdx_tra import TdxTraClient
from backend.app.models.crossing import GeoPoint
from backend.app.utils import normalize_text, point_ratio_between_stations


STATION_NAME_ALIASES = {
    "中州": "中洲",
    "蘇澳新站": "蘇澳新",
}


class StationGraphService:
    def __init__(self, tdx_client: TdxTraClient) -> None:
        self.tdx_client = tdx_client
        self._station_lookup: dict[str, dict[str, Any]] | None = None

    async def get_station_lookup(self) -> dict[str, dict[str, Any]]:
        if self._station_lookup is not None:
            return self._station_lookup

        stations = await self.tdx_client.get_stations()
        lookup: dict[str, dict[str, Any]] = {}
        for station in stations:
            name = station.get("StationName", {}).get("Zh_tw")
            key = normalize_text(name)
            if key and key not in lookup:
                lookup[key] = station
        self._station_lookup = lookup
        return lookup

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
            enriched["segment_confidence"] = "medium"
            geometry = properties.get("geometry")
            if geometry and isinstance(geometry, dict):
                point = GeoPoint.model_validate(geometry)
                pos_a = station_a.get("StationPosition", {})
                pos_b = station_b.get("StationPosition", {})
                enriched["segment_ratio"] = point_ratio_between_stations(
                    pos_a.get("PositionLon"),
                    pos_a.get("PositionLat"),
                    pos_b.get("PositionLon"),
                    pos_b.get("PositionLat"),
                    point.lon,
                    point.lat,
                )
                enriched["segment_confidence"] = "high"
            else:
                enriched.setdefault("segment_ratio", 0.5)

        return enriched
