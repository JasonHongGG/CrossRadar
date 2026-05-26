from __future__ import annotations

import asyncio
import json

from backend.app.config import Settings
from backend.app.services.rail_path import RailPathService
from backend.app.services.station_graph import StationGraphService


class _StubTdxClient:
    async def get_stations(self) -> list[dict]:
        return [
            {
                "StationID": "7130",
                "StationName": {"Zh_tw": "蘇澳新"},
                "StationPosition": {"PositionLon": 121.84289, "PositionLat": 24.60856},
            },
            {
                "StationID": "1240",
                "StationName": {"Zh_tw": "中洲"},
                "StationPosition": {"PositionLon": 120.51656, "PositionLat": 22.52742},
            },
            {
                "StationID": "4200",
                "StationName": {"Zh_tw": "永康"},
                "StationPosition": {"PositionLon": 120.0, "PositionLat": 23.0},
            },
            {
                "StationID": "4210",
                "StationName": {"Zh_tw": "大橋"},
                "StationPosition": {"PositionLon": 120.01, "PositionLat": 23.0},
            },
        ]


def test_resolve_station_supports_alias_and_suffix_fallback() -> None:
    service = StationGraphService(_StubTdxClient())

    station_a = asyncio.run(service.resolve_station("蘇澳新站"))
    station_b = asyncio.run(service.resolve_station("中州"))

    assert station_a is not None
    assert station_a["StationName"]["Zh_tw"] == "蘇澳新"
    assert station_b is not None
    assert station_b["StationName"]["Zh_tw"] == "中洲"


def test_enrich_crossing_prefers_official_ratio_when_available() -> None:
    service = StationGraphService(_StubTdxClient())

    enriched = asyncio.run(
        service.enrich_crossing_properties(
            {
                "station_a_name": "永康",
                "station_b_name": "大橋",
                "km_value_meters": 355600,
                "station_a_route_km_meters": 355300,
                "station_b_route_km_meters": 357800,
                "station_route_reference_note": "official anchor",
                "geometry": {"lon": 120.003, "lat": 23.0},
            }
        )
    )

    assert enriched["ratio_source"] == "official_route_mileage"
    assert enriched["segment_confidence"] == "high"
    assert round(enriched["segment_ratio"], 2) == 0.12
    assert enriched["official_segment_ratio"] == enriched["segment_ratio"]


def test_enrich_crossing_uses_osm_path_before_geometry(tmp_path) -> None:
    settings = Settings(TDX_CLIENT_ID="id", TDX_CLIENT_SECRET="secret")
    settings.osm_raw_json_path = tmp_path / "raw_osm.json"
    settings.osm_raw_json_path.write_text(
        json.dumps(
            {
                "elements": [
                    {
                        "type": "way",
                        "id": 1001,
                        "tags": {"railway": "rail", "name": "測試線"},
                        "geometry": [
                            {"lon": 120.0, "lat": 23.0},
                            {"lon": 120.01, "lat": 23.0},
                        ],
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    service = StationGraphService(_StubTdxClient(), RailPathService(settings))
    enriched = asyncio.run(
        service.enrich_crossing_properties(
            {
                "station_a_name": "永康",
                "station_b_name": "大橋",
                "geometry": {"lon": 120.0025, "lat": 23.0},
                "osm_rail_way_ids": [1001],
            }
        )
    )

    assert enriched["ratio_source"] == "osm_path"
    assert enriched["segment_confidence"] == "high"
    assert 0.23 < enriched["segment_ratio"] < 0.27
    assert enriched["path_segment_ratio"] == enriched["segment_ratio"]
    assert "geometry_segment_ratio" in enriched


def test_explain_crossing_properties_returns_geometry_and_path_payloads(tmp_path) -> None:
    settings = Settings(TDX_CLIENT_ID="id", TDX_CLIENT_SECRET="secret")
    settings.osm_raw_json_path = tmp_path / "raw_osm.json"
    settings.osm_raw_json_path.write_text(
        json.dumps(
            {
                "elements": [
                    {
                        "type": "way",
                        "id": 1001,
                        "tags": {"railway": "rail", "name": "測試線"},
                        "geometry": [
                            {"lon": 120.0, "lat": 23.0},
                            {"lon": 120.01, "lat": 23.0},
                        ],
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    service = StationGraphService(_StubTdxClient(), RailPathService(settings))
    explanation = asyncio.run(
        service.explain_crossing_properties(
            {
                "crossing_id": "demo",
                "name": "測試平交道",
                "line": "測試線",
                "station_a_name": "永康",
                "station_b_name": "大橋",
                "geometry": {"lon": 120.0025, "lat": 23.0},
                "osm_rail_way_ids": [1001],
            }
        )
    )

    assert explanation["ratios"]["selected"]["source"] == "osm_path"
    assert explanation["ratios"]["osm_path"]["available"] is True
    assert explanation["ratios"]["osm_path"]["reason"] == "ok"
    assert explanation["ratios"]["osm_path"]["plausible"] is True
    assert explanation["ratios"]["osm_path"]["selected_eligible"] is True
    assert explanation["ratios"]["osm_path"]["station_a_path"]["coordinates"][0] == [120.0, 23.0]
    assert explanation["ratios"]["osm_path"]["station_b_path"]["coordinates"][-1] == [120.01, 23.0]
    assert explanation["ratios"]["geometry_projection"]["available"] is True
    assert explanation["ratios"]["geometry_projection"]["projected_point"] == {"lon": 120.0025, "lat": 23.0}


def test_enrich_crossing_rejects_implausible_osm_path(tmp_path) -> None:
    settings = Settings(TDX_CLIENT_ID="id", TDX_CLIENT_SECRET="secret")
    settings.osm_raw_json_path = tmp_path / "raw_osm.json"
    settings.osm_raw_json_path.write_text(
        json.dumps(
            {
                "elements": [
                    {
                        "type": "way",
                        "id": 2001,
                        "tags": {"railway": "rail", "name": "繞遠測試線"},
                        "geometry": [
                            {"lon": 120.0, "lat": 23.0},
                            {"lon": 120.0, "lat": 23.1},
                            {"lon": 120.01, "lat": 23.1},
                            {"lon": 120.01, "lat": 23.0},
                        ],
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    service = StationGraphService(_StubTdxClient(), RailPathService(settings))
    enriched = asyncio.run(
        service.enrich_crossing_properties(
            {
                "station_a_name": "永康",
                "station_b_name": "大橋",
                "geometry": {"lon": 120.005, "lat": 23.1},
                "osm_rail_way_ids": [2001],
            }
        )
    )
    explanation = asyncio.run(
        service.explain_crossing_properties(
            {
                "crossing_id": "looped-demo",
                "name": "繞遠平交道",
                "line": "測試線",
                "station_a_name": "永康",
                "station_b_name": "大橋",
                "geometry": {"lon": 120.005, "lat": 23.1},
                "osm_rail_way_ids": [2001],
            }
        )
    )

    assert enriched["ratio_source"] == "geometry_projection"
    assert explanation["ratios"]["selected"]["source"] == "geometry_projection"
    assert explanation["ratios"]["osm_path"]["available"] is True
    assert explanation["ratios"]["osm_path"]["plausible"] is False
    assert explanation["ratios"]["osm_path"]["selected_eligible"] is False
    assert explanation["ratios"]["osm_path"]["reason"] == "path_exceeds_station_span"
    assert "rejecting the osm path" in explanation["ratios"]["selected"]["note"].lower()