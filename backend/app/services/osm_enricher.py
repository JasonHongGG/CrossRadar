from __future__ import annotations

import json
from typing import Any

from backend.app.config import Settings, get_settings
from backend.app.http import request_json
from backend.app.utils import normalize_text, safe_int


TAIWAN_BBOX = (21.8, 119.9, 25.4, 122.2)


class OsmEnricher:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def fetch_raw_dataset(self, *, force_refresh: bool = False) -> dict[str, Any]:
        if not force_refresh and self.settings.osm_raw_json_path.exists():
            return json.loads(self.settings.osm_raw_json_path.read_text(encoding="utf-8"))

        south, west, north, east = TAIWAN_BBOX
        query = f"""
[out:json][timeout:300];
(
  node[\"railway\"=\"level_crossing\"]({south},{west},{north},{east})->.crossings;
  .crossings;
  way(bn.crossings)[\"railway\"];
  way(bn.crossings)[\"highway\"];
);
out body geom;
""".strip()
        payload = await request_json(
            "POST",
            self.settings.osm_overpass_url,
            settings=self.settings,
            data={"data": query},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=180.0,
        )
        self.settings.osm_raw_json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    async def build_geojson(self, *, force_refresh: bool = False) -> dict[str, Any]:
        if not force_refresh and self.settings.osm_geojson_path.exists():
            return json.loads(self.settings.osm_geojson_path.read_text(encoding="utf-8"))

        raw = await self.fetch_raw_dataset(force_refresh=force_refresh)
        elements = raw.get("elements", [])
        nodes = [element for element in elements if element.get("type") == "node" and element.get("tags", {}).get("railway") == "level_crossing"]
        ways = [element for element in elements if element.get("type") == "way"]

        ways_by_crossing: dict[int, dict[str, list[dict[str, Any]]]] = {}
        for node in nodes:
            ways_by_crossing[node["id"]] = {"road": [], "rail": []}
        for way in ways:
            node_ids = set(way.get("nodes", []))
            category = self._way_category(way.get("tags", {}))
            if category is None:
                continue
            for node in nodes:
                if node["id"] in node_ids:
                    ways_by_crossing[node["id"]][category].append(way)

        features: list[dict[str, Any]] = []
        for node in nodes:
            connected = ways_by_crossing.get(node["id"], {"road": [], "rail": []})
            road_names = self._collect_way_names(connected["road"])
            rail_names = self._collect_way_names(connected["rail"])
            tags = node.get("tags", {})
            feature = {
                "type": "Feature",
                "id": f"osm-node-{node['id']}",
                "geometry": {
                    "type": "Point",
                    "coordinates": [node["lon"], node["lat"]],
                },
                "properties": {
                    "osm_id": node["id"],
                    "name": tags.get("name"),
                    "normalized_name": normalize_text(tags.get("name") or ""),
                    "railway_position": tags.get("railway:position"),
                    "railway_position_meters": self._parse_railway_position(tags.get("railway:position")),
                    "road_names": road_names,
                    "road_names_normalized": [normalize_text(name) for name in road_names],
                    "rail_names": rail_names,
                    "rail_names_normalized": [normalize_text(name) for name in rail_names],
                    "road_way_ids": [way["id"] for way in connected["road"]],
                    "rail_way_ids": [way["id"] for way in connected["rail"]],
                    "tags": tags,
                },
            }
            features.append(feature)

        payload = {
            "type": "FeatureCollection",
            "metadata": {
                "source": self.settings.osm_overpass_url,
                "count": len(features),
                "raw_path": str(self.settings.osm_raw_json_path),
            },
            "features": features,
        }
        self.settings.osm_geojson_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    def _way_category(self, tags: dict[str, Any]) -> str | None:
        if "highway" in tags:
            return "road"
        if tags.get("railway"):
            return "rail"
        return None

    def _collect_way_names(self, ways: list[dict[str, Any]]) -> list[str]:
        names: list[str] = []
        for way in ways:
            tags = way.get("tags", {})
            for key in ("name", "ref", "official_name", "old_name", "alt_name"):
                value = tags.get(key)
                if value and value not in names:
                    names.append(str(value))
        return names

    def _parse_railway_position(self, value: str | None) -> int | None:
        if not value:
            return None
        if str(value).startswith("mi:"):
            return None
        try:
            return int(float(value) * 1000)
        except (TypeError, ValueError):
            return safe_int(value, default=0) or None
