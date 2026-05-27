from __future__ import annotations

import json

from backend.app.config import Settings
from backend.app.services.rail_path import RailPathService


def test_snap_point_candidates_sort_component_segments_by_distance(tmp_path) -> None:
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
                            {"lon": 120.0, "lat": 23.01},
                            {"lon": 120.0, "lat": 23.02},
                            {"lon": 120.0, "lat": 23.03},
                        ],
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    service = RailPathService(settings)
    graph = service._graph
    assert graph is not None

    component_id = graph.segment_components[0]
    candidates = service._snap_point_candidates(
        120.0001,
        23.0295,
        required_component=component_id,
        max_snap_distance_meters=2_500.0,
        max_candidates=1,
    )

    assert len(candidates) == 1
    assert candidates[0].segment_id == 2