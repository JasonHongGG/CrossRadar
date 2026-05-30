from __future__ import annotations

import json
from collections import defaultdict

import pytest

from backend.app.config import Settings
from backend.app.services.rail_path import RailPathService
from backend.app.services.station_graph import StationGraphService
from scripts.export_mobile_bundle import _path_segment_station_projection_ids, _station_snap_candidates


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
