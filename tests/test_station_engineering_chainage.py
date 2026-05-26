from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = ROOT / "data" / "stations" / "station_engineering_chainage.json"
STATIONS_PATH = ROOT / "車站基本資料集.json"


def load_dataset() -> dict:
    return json.loads(DATASET_PATH.read_text(encoding="utf-8"))


def station(dataset: dict, name: str) -> dict:
    return next(item for item in dataset["stations"] if item["station_name_zh"] == name)


def test_station_count_matches_source_file() -> None:
    dataset = load_dataset()
    source_stations = json.loads(STATIONS_PATH.read_text(encoding="utf-8"))

    assert dataset["metadata"]["counts"]["stations_total"] == len(source_stations) == 245
    assert len(dataset["stations"]) == len(source_stations)


def test_tainan_uses_verified_official_project_chainage() -> None:
    dataset = load_dataset()
    tainan = station(dataset, "臺南")["primary_engineering_chainage"]

    assert tainan["meters"] == 357_800
    assert tainan["km_marker"] == "K357+800"
    assert tainan["method"] == "official_project_station_chainage"
    assert tainan["confidence"] == "verified"
    assert any("rb.gov.tw" in source["url"] for source in tainan["sources"])
    assert tainan["meters"] > 357_184


def test_xinying_inference_excludes_mislocated_taoyuan_anchors() -> None:
    dataset = load_dataset()
    xinying = station(dataset, "新營")["primary_engineering_chainage"]

    anchor_names = {anchor["name"] for anchor in xinying["anchor_crossings"]}
    anchor_counties = {anchor["county"] for anchor in xinying["anchor_crossings"]}

    assert xinying["method"] == "interpolated_between_official_crossing_k_anchors"
    assert 319_066 <= xinying["meters"] <= 319_922
    assert anchor_names == {"東山路", "新營南方"}
    assert anchor_counties == {"臺南市"}


def test_dataset_does_not_reference_operating_mileage_artifacts() -> None:
    dataset_text = DATASET_PATH.read_text(encoding="utf-8")

    assert "mile.pdf" not in dataset_text
    assert "營業里程表" not in dataset_text
    assert "Operating Kilometers" not in dataset_text