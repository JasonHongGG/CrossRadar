from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MARKDOWN_PATH = ROOT / "station 里程.md"
STATIONS_UK_PATH = ROOT / "data" / "stations" / "stations_official(UK).json"

KM_FRAGMENT = r"(?:UK|(?:\d+\s*)?K)\s*\d*\s*\+\s*\d+(?:\s*~\s*(?:UK|(?:\d+\s*)?K)\s*\d*\s*\+\s*\d+)?"

SECTION_PATTERN = re.compile(r"^(?P<title>.+?)\s+\(StationCode:\s*(?P<code>\d+)\)", re.MULTILINE)
STRUCTURED_SECTION_PATTERN = re.compile(r"^###\s+(?P<title>.+?)\s*$", re.MULTILINE)
STRUCTURED_LINE_PATTERN = re.compile(r"^1\.\s*所屬線別：(?P<line>.+)$", re.MULTILINE)
STRUCTURED_CENTER_PATTERN = re.compile(r"^2\.\s*中心里程\s*\(AK\)：(?P<center>.+)$", re.MULTILINE)
STRUCTURED_BRANCH_PATTERN = re.compile(r"^3\.\s*分支起點資訊：(?P<branch>.+)$", re.MULTILINE)
CANDIDATE_PATTERNS = [
    (0, re.compile(r"站房中心里程(?:則)?定錨於\s*(?P<raw>[^\n]+)")),
    (0, re.compile(r"(?P<label>[^：\n]*中心里程(?:（[^）]+）)?)[：]\s*(?P<raw>[^\n]+)")),
    (0, re.compile(r"(?P<label>[^：\n]*主線貫通里程)[：]\s*(?P<raw>[^\n]+)")),
    (0, re.compile(r"(?P<label>[^：\n]*基地內部里程)[：]\s*(?P<raw>[^\n]+)")),
    (0, re.compile(r"(?P<label>[^：\n]*工程里程)[：]\s*(?P<raw>[^\n]+)")),
    (
        1,
        re.compile(
            r"(?P<label>[^：\n]*(?:法定終點里程|實體終點里程|終點端點|終點里程|工程里程原點|法定起算原點|工程起算原點|起算原點|起點里程|獨立原點|銜接端點)(?:（[^）]+）)?)[：]\s*(?P<raw>[^\n]+)"
        ),
    ),
]
KM_VALUE_PATTERN = re.compile(KM_FRAGMENT)
LINE_NAME_PATTERN = re.compile(r"([A-Za-z\u4e00-\u9fff]+(?:線|支線|主線|專用線|鐵路))")
STRUCTURED_MARKER_PATTERN = re.compile(r"(?:^|\s)(?P<line>[A-Za-z\u4e00-\u9fff]+(?:線|支線|主線|專用線|鐵路))?\s*(?P<marker>K\s*\d+\s*\+\s*\d+(?:\s*~\s*K\s*\d+\s*\+\s*\d+)?)")
STRUCTURED_ANY_MARKER_PATTERN = re.compile(r"K\s*\d+\s*\+\s*\d+(?:\s*~\s*K\s*\d+\s*\+\s*\d+)?")
MARKER_COMPONENT_PATTERN = re.compile(r"K\s*(?P<km>\d+)\s*\+\s*(?P<meter>\d+)")

LINE_NAME_NORMALIZATIONS = {
    "內灣支線": "內灣線",
    "集集支線": "集集線",
    "平溪支線": "平溪線",
    "深澳支線": "深澳線",
    "海岸線": "海線",
    "臺中線": "山線",
    "台中線": "山線",
    "海岸線": "海線",
    "臺東線": "台東線",
    "台東線": "台東線",
    "臺中港線": "台中港線",
    "縱貫線北段": "縱貫線",
    "縱貫線南段": "縱貫線",
}

STRUCTURED_LINE_ALIASES = [
    (re.compile(r"縱貫線(?:北段|南段)?"), "縱貫線"),
    (re.compile(r"(?:臺|台)中線(?:（山線）)?|山線"), "山線"),
    (re.compile(r"海岸線(?:（海線）)?|海線"), "海線"),
    (re.compile(r"宜蘭線"), "宜蘭線"),
    (re.compile(r"北迴線"), "北迴線"),
    (re.compile(r"屏東線"), "屏東線"),
    (re.compile(r"南迴線"), "南迴線"),
    (re.compile(r"(?:臺|台)東線"), "台東線"),
    (re.compile(r"內灣線|內灣支線"), "內灣線"),
    (re.compile(r"六家線|六家支線"), "六家線"),
    (re.compile(r"集集線|集集支線"), "集集線"),
    (re.compile(r"平溪線|平溪支線"), "平溪線"),
    (re.compile(r"深澳線|深澳支線"), "深澳線"),
    (re.compile(r"成追線"), "成追線"),
    (re.compile(r"沙崙線"), "沙崙線"),
    (re.compile(r"林鐵主線"), "林鐵主線"),
    (re.compile(r"(?:臺|台)中港線"), "台中港線"),
    (re.compile(r"基地專用線"), "基地專用線"),
    (re.compile(r"機廠專用線"), "機廠專用線"),
]


def _normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _normalize_line_name(value: str) -> str:
    normalized = _normalize_spaces(value)
    normalized = re.sub(r"^(?:及|與)", "", normalized)
    return LINE_NAME_NORMALIZATIONS.get(normalized, normalized)


def _normalize_marker(value: str) -> str:
    normalized = _normalize_spaces(value)

    def repl(match: re.Match[str]) -> str:
        return f"K{int(match.group('km'))} + {int(match.group('meter')):03d}"

    return MARKER_COMPONENT_PATTERN.sub(repl, normalized)


def _extract_line_name(value: str) -> str | None:
    match = re.match(r"^(?P<line>.+?)\s+(?:UK|(?:\d+\s*)?K)", value)
    if match is None:
        return None
    return _normalize_line_name(match.group("line"))


def _extract_line_names(raw_prefix: str) -> list[str]:
    names: list[str] = []
    for match in LINE_NAME_PATTERN.finditer(raw_prefix):
        name = _normalize_line_name(match.group(1))
        if name not in names:
            names.append(name)
    return names


def _extract_values_from_raw(raw_text: str) -> list[str]:
    marker_match = KM_VALUE_PATTERN.search(raw_text)
    if marker_match is None:
        return []

    raw_prefix = _normalize_spaces(raw_text[: marker_match.start()])
    marker = _normalize_marker(marker_match.group(0))
    marker = re.sub(r"\bUK(?=\s*\d)", "K", marker)

    line_names = _extract_line_names(raw_prefix)
    if marker.startswith("K"):
        line_names = line_names or ["縱貫線"]

    values: list[str] = []
    if not line_names:
        values.append(marker)
        return values

    for line_name in line_names:
        value = f"{line_name} {marker}"
        if value not in values:
            values.append(value)
    return values


def _extract_station_uk_candidates(section_text: str) -> list[str]:
    candidates: list[dict[str, Any]] = []

    for priority, pattern in CANDIDATE_PATTERNS:
        for match in pattern.finditer(section_text):
            raw_text = match.group("raw")
            for value in _extract_values_from_raw(raw_text):
                candidates.append(
                    {
                        "value": value,
                        "line_name": _extract_line_name(value),
                        "priority": priority,
                        "start": match.start(),
                    }
                )

    best_by_line: dict[str, dict[str, Any]] = {}
    for candidate in sorted(candidates, key=lambda item: (item["priority"], item["start"], item["value"])):
        key = candidate["line_name"] or candidate["value"]
        if key not in best_by_line:
            best_by_line[key] = candidate

    return [
        candidate["value"]
        for candidate in sorted(best_by_line.values(), key=lambda item: (item["priority"], item["start"], item["value"]))
    ]


def _extract_legacy_station_uk_lookup(markdown_text: str) -> dict[str, list[str]]:
    matches = list(SECTION_PATTERN.finditer(markdown_text))
    lookup: dict[str, list[str]] = {}

    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown_text)
        section_text = markdown_text[start:end]
        uk_values = _extract_station_uk_candidates(section_text)
        if not uk_values:
            continue
        lookup[match.group("code")] = uk_values

    return lookup


def _extract_structured_line_names(text: str) -> list[str]:
    matches: list[tuple[int, str]] = []
    for pattern, canonical in STRUCTURED_LINE_ALIASES:
        for match in pattern.finditer(text):
            matches.append((match.start(), canonical))

    names: list[str] = []
    for _, name in sorted(matches, key=lambda item: item[0]):
        canonical = _normalize_line_name(name)
        if canonical not in names:
            names.append(canonical)
    return names


def _extract_structured_primary_line(raw_line: str) -> str | None:
    names = _extract_structured_line_names(raw_line)
    if not names:
        return None
    return names[0]


def _extract_structured_center_values(raw_line: str, center_text: str) -> list[str]:
    values: list[str] = []
    primary_line = _extract_structured_primary_line(raw_line)

    for raw_segment in re.split(r"\s*/\s*", center_text):
        segment = _normalize_spaces(raw_segment)
        if not segment:
            continue

        marker_match = STRUCTURED_MARKER_PATTERN.search(segment)
        if marker_match is None:
            marker_match = STRUCTURED_ANY_MARKER_PATTERN.search(segment)
            if marker_match is None:
                continue
            explicit_line = None
            marker = _normalize_marker(marker_match.group(0))
        else:
            explicit_line = marker_match.group("line")
            marker = _normalize_marker(marker_match.group("marker"))

        if explicit_line:
            line_names = _extract_structured_line_names(explicit_line)
        else:
            line_names = _extract_structured_line_names(segment)
            if not line_names and primary_line:
                line_names = [primary_line]

        if not line_names:
            if marker not in values:
                values.append(marker)
            continue

        for line_name in line_names:
            value = f"{line_name} {marker}"
            if value not in values:
                values.append(value)

    return values


def _extract_structured_branch_values(branch_text: str) -> list[str]:
    normalized_branch = _normalize_spaces(branch_text)
    if normalized_branch.startswith("無"):
        return []

    line_names = _extract_structured_line_names(normalized_branch)
    if not line_names:
        return []

    marker_match = STRUCTURED_ANY_MARKER_PATTERN.search(normalized_branch)
    marker = _normalize_marker(marker_match.group(0)) if marker_match is not None else "K0 + 000"
    return [f"{line_name} {marker}" for line_name in line_names]


def _extract_structured_station_uk_lookup(
    markdown_text: str,
    station_name_to_code: dict[str, str],
) -> dict[str, list[str]]:
    matches = list(STRUCTURED_SECTION_PATTERN.finditer(markdown_text))
    lookup: dict[str, list[str]] = {}

    for index, match in enumerate(matches):
        title = _normalize_spaces(match.group("title"))
        station_code = station_name_to_code.get(title)
        if station_code is None:
            continue

        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown_text)
        section_text = markdown_text[start:end]

        line_match = STRUCTURED_LINE_PATTERN.search(section_text)
        center_match = STRUCTURED_CENTER_PATTERN.search(section_text)
        branch_match = STRUCTURED_BRANCH_PATTERN.search(section_text)
        if line_match is None or center_match is None or branch_match is None:
            continue

        uk_values: list[str] = []
        for value in _extract_structured_center_values(line_match.group("line"), center_match.group("center")):
            if value not in uk_values:
                uk_values.append(value)
        for value in _extract_structured_branch_values(branch_match.group("branch")):
            if value not in uk_values:
                uk_values.append(value)

        if uk_values:
            lookup[station_code] = uk_values

    return lookup


def extract_station_uk_lookup(
    markdown_text: str,
    station_name_to_code: dict[str, str] | None = None,
) -> dict[str, list[str]]:
    lookup = _extract_legacy_station_uk_lookup(markdown_text)
    if station_name_to_code:
        lookup.update(_extract_structured_station_uk_lookup(markdown_text, station_name_to_code))
    return lookup


def build_station_name_to_code(payload: dict[str, Any]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for station in payload.get("stations", []):
        station_code = str(station.get("stationCode") or "")
        if not station_code:
            continue
        for key in ("stationName", "name"):
            station_name = _normalize_spaces(str(station.get(key) or ""))
            if station_name and station_name not in lookup:
                lookup[station_name] = station_code
    return lookup


def apply_station_uk_values(
    payload: dict[str, Any],
    uk_lookup: dict[str, list[str]],
    *,
    source_name: str = "station 里程.md",
) -> tuple[dict[str, Any], list[str]]:
    stations = payload.get("stations", [])
    missing_codes: list[str] = []
    updated_stations: list[dict[str, Any]] = []

    for raw_station in stations:
        station = dict(raw_station)
        station_code = str(station.get("stationCode") or "")

        uk_values = uk_lookup.get(station_code)
        if uk_values is None:
            missing_codes.append(station_code)
        else:
            station["UK"] = uk_values
            station["UK_primary"] = uk_values[0]

        updated_stations.append(station)

    updated_payload = {
        **payload,
        "metadata": {
            **payload.get("metadata", {}),
            "note": f"Raw station reference dataset with engineering-chainage enrichment populated from {source_name}. For compatibility, `UK` remains an ordered list of station chainage references and `UK_primary` repeats the preferred station-level reference for convenience.",
        },
        "stations": updated_stations,
    }
    return updated_payload, missing_codes


def main(argv: list[str] | None = None) -> None:
    args = argv if argv is not None else sys.argv[1:]
    markdown_path = Path(args[0]).resolve() if args else DEFAULT_MARKDOWN_PATH

    markdown_text = markdown_path.read_text(encoding="utf-8")
    payload = json.loads(STATIONS_UK_PATH.read_text(encoding="utf-8"))
    station_name_to_code = build_station_name_to_code(payload)

    uk_lookup = extract_station_uk_lookup(markdown_text, station_name_to_code)
    updated_payload, missing_codes = apply_station_uk_values(payload, uk_lookup, source_name=markdown_path.name)
    if missing_codes:
        preview = ", ".join(missing_codes[:10])
        raise RuntimeError(
            f"Missing chainage values in {markdown_path.name} for {len(missing_codes)} station codes: {preview}"
        )

    STATIONS_UK_PATH.write_text(json.dumps(updated_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "updated_station_count": len(updated_payload.get("stations", [])),
                "uk_lookup_count": len(uk_lookup),
                "markdown_path": str(markdown_path),
                "output_path": str(STATIONS_UK_PATH),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()