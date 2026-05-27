from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "sync_stations_official_uk.py"

spec = importlib.util.spec_from_file_location("sync_stations_official_uk", MODULE_PATH)
assert spec is not None
assert spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_extract_station_uk_lookup_reads_center_marker_variants() -> None:
    markdown_text = """
造橋火車站 (StationCode: 3140) 的軌道工程里程
山線正線中心里程： 山線 K128 + 800（承接竹南站 UK125 + 000 基準點往山線延伸）

豐富火車站 (StationCode: 3150) 的軌道工程里程
現行新站正線中心里程： 山線 K136 + 600（承接竹南站 UK125 + 000 基準點往山線延伸）

彰化火車站 (StationCode: 3360) 的軌道工程里程
縱貫線（正線基準）中心里程： 縱貫線 K210 + 500（由基隆站 0K + 000 起算）

枋野號誌站 (StationCode: 5170) 的軌道工程里程
南迴線正線中心里程： 南迴線 K22 + 000（由起算總樞紐枋寮車站 南迴線 0K + 000 軸線起算）

南方小站 (StationCode: 5998) 的軌道工程里程
南方小站基地內部里程： 基地專用線 K1 + 200（由正線分歧原點的廠門聯鎖號誌起算）

潮州基地 (StationCode: 5999) 的軌道工程里程
廠區實體工程里程原點： 機廠專用線 K2 + 200 ~ K3 + 800 之間（列車必須穿過潮州車輛基地）

吉安火車站 (StationCode: 6250) 的軌道工程里程
台東線（花東線）法定起算原點： 台東線 K0 + 000 基準軸線精準座落於本站北端外正線上。本站站房中心里程則定錨於 台東線 K3 + 300（由花蓮車站 0K + 000 軸線向南遞增計算）

花蓮火車站 (StationCode: 7000) 的軌道工程里程
北迴線正線法定終點里程： 北迴線 K79 + 200（由起算總樞紐蘇澳新站 0K + 000 軸線向南遞增計算）

蘇澳火車站 (StationCode: 7120) 的軌道工程里程
宜蘭線法定終點里程： 宜蘭線 K93 + 400 基準軸線精準定錨在本站月台末端的終端止衝擋。本站站房中心里程則定錨於 宜蘭線 K93 + 300（由八堵起算原點向南遞增計算）

蘇澳新火車站 (StationCode: 7130) 的軌道工程里程
宜蘭線主線貫通里程： 宜蘭線 K89 + 900（由起算總樞紐八堵車站 0K + 000 軸線向南遞增計算）

新馬火車站 (StationCode: 7140) 的軌道工程里程
宜蘭線主線中心里程（現行新線）： 宜蘭線 K88 + 800（由起算總樞紐八堵車站 0K + 000 軸線向南遞增計算）
"""

    lookup = module.extract_station_uk_lookup(markdown_text)

    assert lookup == {
        "3140": "山線 K128 + 800",
        "3150": "山線 K136 + 600",
        "3360": "縱貫線 K210 + 500",
        "5170": "南迴線 K22 + 000",
        "5998": "基地專用線 K1 + 200",
        "5999": "機廠專用線 K2 + 200 ~ K3 + 800",
        "6250": "台東線 K3 + 300",
        "7000": "北迴線 K79 + 200",
        "7120": "宜蘭線 K93 + 300",
        "7130": "宜蘭線 K89 + 900",
        "7140": "宜蘭線 K88 + 800",
    }


def test_apply_station_uk_values_updates_only_from_start_station_code() -> None:
    payload = {
        "metadata": {"note": "old"},
        "stations": [
            {"stationCode": "1250", "stationName": "竹南", "UK": "UK125 + 000"},
            {"stationCode": "3140", "stationName": "造橋"},
            {"stationCode": "3150", "stationName": "豐富"},
        ],
    }

    updated_payload, missing_codes = module.apply_station_uk_values(
        payload,
        {
            "3140": "山線 K128 + 800",
            "3150": "山線 K136 + 600",
        },
    )

    stations = updated_payload["stations"]
    assert stations[0]["UK"] == "UK125 + 000"
    assert stations[1]["UK"] == "山線 K128 + 800"
    assert stations[2]["UK"] == "山線 K136 + 600"
    assert missing_codes == []
    assert "UK engineering-mileage enrichment" in updated_payload["metadata"]["note"]


def test_apply_station_uk_values_reports_missing_codes_after_start() -> None:
    payload = {
        "metadata": {},
        "stations": [
            {"stationCode": "3140", "stationName": "造橋"},
            {"stationCode": "3150", "stationName": "豐富"},
            {"stationCode": "3160", "stationName": "苗栗"},
        ],
    }

    _, missing_codes = module.apply_station_uk_values(
        payload,
        {
            "3140": "山線 K128 + 800",
            "3160": "山線 K140 + 700",
        },
    )

    assert missing_codes == ["3150"]