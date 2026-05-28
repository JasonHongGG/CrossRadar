from __future__ import annotations

import asyncio
import json
from pathlib import Path

from backend.app.config import Settings
from backend.app.services.rail_path import RailPathRatio, RailPathService
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
            {
                "StationID": "9999",
                "StationName": {"Zh_tw": "無座標站"},
                "StationPosition": {},
            },
            {
                "StationID": "7360",
                "StationName": {"Zh_tw": "猴硐"},
                "StationPosition": {"PositionLon": 121.82728, "PositionLat": 25.08617},
            },
            {
                "StationID": "1208",
                "StationName": {"Zh_tw": "內灣"},
                "StationPosition": {"PositionLon": 121.18297, "PositionLat": 24.70559},
            },
            {
                "StationID": "3433",
                "StationName": {"Zh_tw": "車埕"},
                "StationPosition": {"PositionLon": 120.86581, "PositionLat": 23.83247},
            },
            {
                "StationID": "6100",
                "StationName": {"Zh_tw": "東里"},
                "StationPosition": {"PositionLon": 121.30418, "PositionLat": 23.27234},
            },
            {
                "StationID": "1020",
                "StationName": {"Zh_tw": "鳳鳴"},
                "StationPosition": {"PositionLon": 121.34972, "PositionLat": 24.97014},
            },
        ]


class _CountingTdxClient(_StubTdxClient):
    def __init__(self) -> None:
        self.calls = 0

    async def get_stations(self) -> list[dict]:
        self.calls += 1
        return await super().get_stations()


class _CountingRailPathService:
    def __init__(self) -> None:
        self.calls = 0

    def compute_segment_ratio(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls += 1
        return RailPathRatio(
            ratio=0.4,
            distance_from_station_a_meters=400.0,
            distance_to_station_b_meters=600.0,
            crossing_snap_distance_meters=0.0,
            station_a_snap_distance_meters=10.0,
            station_b_snap_distance_meters=10.0,
        )


class _WarmableRailPathService:
    def __init__(self) -> None:
        self.graph_access_count = 0

    @property
    def _graph(self):  # noqa: N802
        self.graph_access_count += 1
        return object()


def _build_settings() -> Settings:
    settings = Settings(TDX_CLIENT_ID="id", TDX_CLIENT_SECRET="secret")
    settings.supplemental_stations_json_path = Path("__missing_supplemental_stations__.json")
    settings.stations_official_uk_json_path = Path("__missing_stations_official_uk__.json")
    return settings


def test_resolve_station_supports_alias_and_suffix_fallback() -> None:
    service = StationGraphService(_StubTdxClient(), settings=_build_settings())

    station_a = asyncio.run(service.resolve_station("蘇澳新站"))
    station_b = asyncio.run(service.resolve_station("中州"))
    station_c = asyncio.run(service.resolve_station("侯硐"))
    station_d = asyncio.run(service.resolve_station("內彎"))
    station_e = asyncio.run(service.resolve_station("車程"))
    station_f = asyncio.run(service.resolve_station("安通"))
    station_g = asyncio.run(service.resolve_station("鳳鳴火車站"))

    assert station_a is not None
    assert station_a["StationName"]["Zh_tw"] == "蘇澳新"
    assert station_b is not None
    assert station_b["StationName"]["Zh_tw"] == "中洲"
    assert station_c is not None
    assert station_c["StationName"]["Zh_tw"] == "猴硐"
    assert station_d is not None
    assert station_d["StationName"]["Zh_tw"] == "內灣"
    assert station_e is not None
    assert station_e["StationName"]["Zh_tw"] == "車埕"
    assert station_f is not None
    assert station_f["StationName"]["Zh_tw"] == "東里"
    assert station_g is not None
    assert station_g["StationName"]["Zh_tw"] == "鳳鳴"


def test_list_station_summaries_returns_only_stations_with_positions() -> None:
    service = StationGraphService(_StubTdxClient(), settings=_build_settings())

    stations = asyncio.run(service.list_station_summaries())

    assert {station["name"] for station in stations} == {"大橋", "永康", "中洲", "蘇澳新", "猴硐", "內灣", "車埕", "東里", "鳳鳴"}
    assert all(station["position"]["PositionLat"] is not None for station in stations)
    assert all(station["position"]["PositionLon"] is not None for station in stations)


def test_resolve_station_and_list_summaries_include_supplemental_stations(tmp_path) -> None:
    settings = Settings(TDX_CLIENT_ID="id", TDX_CLIENT_SECRET="secret")
    settings.supplemental_stations_json_path = tmp_path / "stations_supplemental.json"
    settings.stations_official_uk_json_path = tmp_path / "stations_official(UK).json"
    settings.supplemental_stations_json_path.write_text(
        json.dumps(
            {
                "metadata": {"updated_at": "2026-05-27T00:00:00+00:00", "count": 1},
                "stations": [
                    {
                        "station_id": "SUPP-TEST-GANG",
                        "name": "港站",
                        "position": {"PositionLat": 24.2918773, "PositionLon": 120.5437636},
                        "note": "test supplemental station",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    settings.stations_official_uk_json_path.write_text(
        json.dumps({"stations": []}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    service = StationGraphService(_StubTdxClient(), settings=settings)

    station = asyncio.run(service.resolve_station("港站"))
    summaries = asyncio.run(service.list_station_summaries())

    assert station is not None
    assert station["StationID"] == "SUPP-TEST-GANG"
    assert station["StationPosition"] == {"PositionLat": 24.2918773, "PositionLon": 120.5437636}
    assert any(summary["station_id"] == "SUPP-TEST-GANG" and summary["name"] == "港站" for summary in summaries)


def test_station_summaries_and_crossing_detail_include_station_uk_reference(tmp_path) -> None:
    settings = Settings(TDX_CLIENT_ID="id", TDX_CLIENT_SECRET="secret")
    settings.supplemental_stations_json_path = tmp_path / "stations_supplemental.json"
    settings.stations_official_uk_json_path = tmp_path / "stations_official(UK).json"
    settings.stations_official_uk_json_path.write_text(
        json.dumps(
            {
                "stations": [
                    {
                        "stationCode": "4200",
                        "stationName": "永康",
                        "UK": ["縱貫線 K355 + 300"],
                        "UK_primary": "縱貫線 K355 + 300",
                    },
                    {
                        "stationCode": "4210",
                        "stationName": "大橋",
                        "UK": ["縱貫線 K357 + 800"],
                        "UK_primary": "縱貫線 K357 + 800",
                    },
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    service = StationGraphService(_StubTdxClient(), settings=settings)

    summaries = asyncio.run(service.list_station_summaries())
    enriched = asyncio.run(
        service.enrich_crossing_properties(
            {
                "station_a_name": "永康",
                "station_b_name": "大橋",
            }
        )
    )

    summary_by_id = {station["station_id"]: station for station in summaries}
    assert summary_by_id["4200"]["uk_primary"] == "縱貫線 K355 + 300"
    assert summary_by_id["4210"]["uk_primary"] == "縱貫線 K357 + 800"
    assert enriched["station_a_uk_primary"] == "縱貫線 K355 + 300"
    assert enriched["station_b_uk_primary"] == "縱貫線 K357 + 800"
    assert enriched["station_uk_reference_note"] == "車站 UK 為推估參考值，非精準量測。"


def test_enrich_crossing_keeps_official_ratio_diagnostics_only_without_osm_path() -> None:
    service = StationGraphService(_StubTdxClient(), settings=_build_settings())

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

    assert enriched["ratio_source"] == "unavailable"
    assert enriched["segment_confidence"] == "low"
    assert enriched["segment_ratio"] is None
    assert round(enriched["official_segment_ratio"], 2) == 0.12
    assert "accepted connected OSM rail path" in enriched["segment_confidence_reason"]


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


def test_resolve_runtime_ratio_for_station_pair_memoizes_by_crossing_and_stop_pair() -> None:
    rail_path_service = _CountingRailPathService()
    service = StationGraphService(_StubTdxClient(), rail_path_service=rail_path_service, settings=_build_settings())
    station_lookup_by_id = asyncio.run(service.get_station_lookup_by_id())
    crossing = {
        "crossing_id": "memo-demo",
        "geometry": {"lon": 120.005, "lat": 23.0},
        "osm_rail_way_ids": [1001],
    }

    first = service.resolve_runtime_ratio_for_station_pair(
        crossing,
        upstream_station_id="4200",
        downstream_station_id="4210",
        station_lookup_by_id=station_lookup_by_id,
    )
    second = service.resolve_runtime_ratio_for_station_pair(
        crossing,
        upstream_station_id="4200",
        downstream_station_id="4210",
        station_lookup_by_id=station_lookup_by_id,
    )

    assert first == second
    assert rail_path_service.calls == 1


def test_warm_runtime_caches_primes_station_lookup_and_graph() -> None:
    tdx_client = _CountingTdxClient()
    rail_path_service = _WarmableRailPathService()
    service = StationGraphService(tdx_client, rail_path_service=rail_path_service, settings=_build_settings())

    asyncio.run(service.warm_runtime_caches())

    assert tdx_client.calls == 1
    assert service._station_lookup_by_id is not None
    assert rail_path_service.graph_access_count == 1


def test_explain_crossing_properties_returns_osm_path_payloads(tmp_path) -> None:
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

    service = StationGraphService(_StubTdxClient(), RailPathService(settings), settings)
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
    assert set(explanation["ratios"].keys()) == {"selected", "osm_path"}


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

    service = StationGraphService(_StubTdxClient(), RailPathService(settings), settings)
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

    assert enriched["ratio_source"] == "unavailable"
    assert enriched["segment_ratio"] is None
    assert explanation["ratios"]["selected"]["source"] == "unavailable"
    assert explanation["ratios"]["osm_path"]["available"] is True
    assert explanation["ratios"]["osm_path"]["plausible"] is False
    assert explanation["ratios"]["osm_path"]["selected_eligible"] is False
    assert explanation["ratios"]["osm_path"]["reason"] == "path_exceeds_station_span"
    assert "rejected the osm path" in explanation["ratios"]["selected"]["note"].lower()
    assert "accepted connected osm rail path" not in explanation["ratios"]["selected"]["note"].lower()