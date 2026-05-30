from __future__ import annotations

import json
from collections import defaultdict

import pytest

from backend.app.config import Settings
from backend.app.services.rail_path import RailPathService
from backend.app.services.station_graph import StationGraphService
from scripts.export_mobile_bundle import (
    _bounded_station_projection_candidate_ids,
    _build_prediction_contract_metadata,
    _path_segment_station_projection_ids,
    _station_snap_candidates,
)


def test_prediction_contract_metadata_declares_mobile_runtime_requirements() -> None:
    contract = _build_prediction_contract_metadata(
        calibration={
            "rules": [{"id": "demo"}],
            "observations": [{"id": "obs"}],
            "readiness": {"family_ready_count": 1, "segment_ready_count": 0},
        },
        timetable_snapshot={"available": True, "cached_at": "2026-05-28T00:00:00+00:00"},
        runtime_ratio_count=10,
        runtime_ratio_rejection_count=2,
        station_pair_projection_count=5,
        station_pair_projection_rejection_count=1,
        runtime_unavailable_count=0,
    )

    assert contract["railway_time_zone"] == "Asia/Taipei"
    assert contract["snapshot_required_sources"] == ["liveboards", "timetables", "train_info"]
    assert contract["snapshot_incomplete_behavior"] == "prediction_unavailable"
    assert contract["runtime_ratio_source"] == "osm_path_only"
    assert contract["calibration_rule_count"] == 1
    assert contract["calibration_family_ready_count"] == 1
    assert "eta" in contract["trace_required_fields"]


def test_bounded_station_projection_candidates_preserve_pinned_sources() -> None:
    candidates = _bounded_station_projection_candidate_ids(
        path_station_ids=[f"P{i:02}" for i in range(80)],
        corridor_station_ids=["C01", "C02"],
        timetable_station_ids={"T02", "T01"},
        calibration_station_ids=["K01"],
    )

    assert candidates[:3] == ["T01", "T02", "K01"]
    assert len(candidates) == 16
    assert "P12" in candidates
    assert "P13" not in candidates


class _LocalStationsClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def get_stations(self) -> list[dict]:
        payload = json.loads(self.settings.station_cache_path.read_text(encoding="utf-8"))
        return list(payload.get("data") or [])


@pytest.mark.asyncio
async def test_path_segment_projection_candidates_cover_known_long_pairs() -> None:
    settings = Settings(TDX_CLIENT_ID="id", TDX_CLIENT_SECRET="secret")
    rail_path_service = RailPathService(settings)
    station_graph = StationGraphService(_LocalStationsClient(settings), rail_path_service, settings)  # type: ignore[arg-type]
    station_lookup_by_id = await station_graph.get_station_lookup_by_id()

    rail_graph = rail_path_service._graph
    assert rail_graph is not None

    path_segments_by_nodes: dict[frozenset[int], set[int]] = defaultdict(set)
    for segment in rail_graph.segments:
        path_segments_by_nodes[frozenset((segment.start_node, segment.end_node))].add(segment.segment_id)

    station_snap_candidates_by_id = {
        str(station_id): _station_snap_candidates(rail_path_service=rail_path_service, station=station)
        for station_id, station in station_lookup_by_id.items()
    }
    pair_path_spec_cache: dict[tuple[str, str], dict[str, object] | None] = {}

    candidates_7000_0990 = _path_segment_station_projection_ids(
        upstream_station_id="7000",
        downstream_station_id="0990",
        rail_path_service=rail_path_service,
        rail_graph=rail_graph,
        segments_by_nodes=path_segments_by_nodes,
        pair_path_spec_cache=pair_path_spec_cache,
        station_snap_candidates_by_id=station_snap_candidates_by_id,
    )
    candidates_3300_1080 = _path_segment_station_projection_ids(
        upstream_station_id="3300",
        downstream_station_id="1080",
        rail_path_service=rail_path_service,
        rail_graph=rail_graph,
        segments_by_nodes=path_segments_by_nodes,
        pair_path_spec_cache=pair_path_spec_cache,
        station_snap_candidates_by_id=station_snap_candidates_by_id,
    )

    assert len(candidates_7000_0990) == 39
    assert len(candidates_3300_1080) == 31
