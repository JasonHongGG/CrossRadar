from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.app.config import Settings, get_settings
from backend.app.services.crossing_catalog import CrossingCatalogService
from backend.app.services.osm_enricher import OsmEnricher
from backend.app.services.station_graph import StationGraphService


def _file_meta(path: Path) -> dict[str, Any]:
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


class ManualOsmMappingService:
    def __init__(
        self,
        catalog: CrossingCatalogService,
        osm_enricher: OsmEnricher,
        settings: Settings | None = None,
        station_graph: StationGraphService | None = None,
    ) -> None:
        self.catalog = catalog
        self.osm_enricher = osm_enricher
        self.settings = settings or get_settings()
        self.station_graph = station_graph

    async def list_review_entries(self, *, include_resolved: bool = True) -> dict[str, Any]:
        analysis = self._load_unmatched_analysis()
        mapping_lookup = self._mapping_lookup()
        osm_lookup = await self._osm_lookup()
        raw_entries = [
            entry
            for entry in analysis.get("entries", [])
            if entry.get("analysis", {}).get("reviewable", True)
        ]

        entries: list[dict[str, Any]] = []
        resolved_count = 0
        for raw_entry in raw_entries:
            entry = await self._enrich_review_entry(raw_entry)
            crossing_id = entry.get("crossing_id")
            manual_mapping = mapping_lookup.get(str(crossing_id))
            resolved = manual_mapping is not None
            if resolved:
                resolved_count += 1
            if not include_resolved and resolved:
                continue

            mapped_osm_feature = None
            if manual_mapping is not None:
                mapped_osm_feature = self._summarize_osm_feature(osm_lookup.get(str(manual_mapping.get("osm_id"))))

            entries.append(
                {
                    **entry,
                    "resolved": resolved,
                    "manual_mapping": manual_mapping,
                    "mapped_osm_feature": mapped_osm_feature,
                }
            )

        total_unmatched = len(raw_entries)
        return {
            "metadata": {
                **analysis.get("metadata", {}),
                "pending_count": max(total_unmatched - resolved_count, 0),
                "resolved_count": resolved_count,
                "reviewable_count": total_unmatched,
                "manual_mapping_file": _file_meta(self.settings.manual_mappings_json_path),
            },
            "summary": analysis.get("summary", {}),
            "entries": entries,
        }

    async def _enrich_review_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        enriched = dict(entry)
        if self.station_graph is None:
            return enriched

        try:
            return await self.station_graph.enrich_crossing_properties(enriched)
        except Exception:
            return enriched

    async def save_mapping(self, crossing_id: str, osm_id: int, note: str | None = None) -> dict[str, Any]:
        review_entry = self._find_review_entry(crossing_id)
        osm_lookup = await self._osm_lookup()
        osm_feature = osm_lookup.get(str(osm_id))
        if osm_feature is None:
            raise LookupError(f"OSM ID {osm_id} not found")

        conflict = await self._find_existing_conflict(crossing_id, osm_id)
        if conflict is not None:
            conflict_name = conflict.get("properties", {}).get("name") or conflict.get("id")
            raise RuntimeError(f"OSM ID {osm_id} is already mapped to {conflict_name}")

        payload = self._load_mapping_payload()
        mappings = payload.get("mappings", [])
        updated_at = datetime.now(UTC).isoformat()
        entry = {
            "crossing_id": crossing_id,
            "osm_id": osm_id,
            "note": note,
            "updated_at": updated_at,
        }

        replaced = False
        for index, item in enumerate(mappings):
            if item.get("crossing_id") == crossing_id:
                mappings[index] = entry
                replaced = True
                break
        if not replaced:
            mappings.append(entry)

        payload["metadata"] = {
            "updated_at": updated_at,
            "count": len(mappings),
        }
        payload["mappings"] = mappings
        self._write_mapping_payload(payload)

        await self.catalog.refresh(force_refresh=False)
        updated_crossing = await self.catalog.get_crossing(crossing_id)
        return {
            "review_entry": review_entry,
            "mapping": entry,
            "mapped_osm_feature": self._summarize_osm_feature(osm_feature),
            "crossing": updated_crossing,
        }

    async def delete_mapping(self, crossing_id: str) -> dict[str, Any]:
        payload = self._load_mapping_payload()
        mappings = payload.get("mappings", [])
        updated = [item for item in mappings if item.get("crossing_id") != crossing_id]
        removed = len(updated) != len(mappings)
        payload["metadata"] = {
            "updated_at": datetime.now(UTC).isoformat(),
            "count": len(updated),
        }
        payload["mappings"] = updated
        self._write_mapping_payload(payload)

        if removed:
            await self.catalog.refresh(force_refresh=False)

        return {
            "crossing_id": crossing_id,
            "removed": removed,
        }

    def _load_unmatched_analysis(self) -> dict[str, Any]:
        if not self.settings.unmatched_analysis_json_path.exists():
            return {
                "metadata": {
                    "official_count": 0,
                    "mapped_count": 0,
                    "unmatched_count": 0,
                    "osm_feature_count": 0,
                },
                "summary": {},
                "entries": [],
            }
        return json.loads(self.settings.unmatched_analysis_json_path.read_text(encoding="utf-8"))

    def _load_mapping_payload(self) -> dict[str, Any]:
        if not self.settings.manual_mappings_json_path.exists():
            return {
                "metadata": {
                    "updated_at": None,
                    "count": 0,
                },
                "mappings": [],
            }
        return json.loads(self.settings.manual_mappings_json_path.read_text(encoding="utf-8"))

    def _mapping_lookup(self) -> dict[str, dict[str, Any]]:
        return {
            str(item.get("crossing_id")): item
            for item in self._load_mapping_payload().get("mappings", [])
            if item.get("crossing_id")
        }

    def _write_mapping_payload(self, payload: dict[str, Any]) -> None:
        self.settings.manual_mappings_json_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings.manual_mappings_json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _find_review_entry(self, crossing_id: str) -> dict[str, Any]:
        analysis = self._load_unmatched_analysis()
        for entry in analysis.get("entries", []):
            if entry.get("crossing_id") == crossing_id:
                if entry.get("analysis", {}).get("reviewable", True) is False:
                    raise LookupError(f"Crossing {crossing_id} is excluded from manual review")
                return entry
        raise LookupError(f"Crossing {crossing_id} not found in unmatched analysis")

    async def _osm_lookup(self) -> dict[str, dict[str, Any]]:
        dataset = await self.osm_enricher.build_geojson(force_refresh=False)
        lookup: dict[str, dict[str, Any]] = {}
        for feature in dataset.get("features", []):
            osm_id = feature.get("properties", {}).get("osm_id")
            if osm_id is not None:
                lookup[str(osm_id)] = feature
        return lookup

    async def _find_existing_conflict(self, crossing_id: str, osm_id: int) -> dict[str, Any] | None:
        load_full = getattr(self.catalog, "load_full", None)
        if callable(load_full):
            dataset = await load_full()
        else:
            dataset = await self.catalog.load()
        for feature in dataset.get("features", []):
            properties = feature.get("properties", {})
            if properties.get("crossing_id") == crossing_id:
                continue
            if properties.get("matched_osm_id") == osm_id:
                return feature
        return None

    def _summarize_osm_feature(self, feature: dict[str, Any] | None) -> dict[str, Any] | None:
        if feature is None:
            return None
        properties = feature.get("properties", {})
        geometry = feature.get("geometry", {})
        return {
            "id": feature.get("id"),
            "osm_id": properties.get("osm_id"),
            "name": properties.get("name"),
            "road_names": properties.get("road_names", []),
            "rail_names": properties.get("rail_names", []),
            "railway_position": properties.get("railway_position"),
            "coordinates": geometry.get("coordinates"),
        }