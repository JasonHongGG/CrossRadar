from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import anyio

from backend.app.config import get_settings
from backend.app.dependencies import get_crossing_catalog_service, get_station_graph_service


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare active crossing ratios against the geometry baseline.")
    parser.add_argument("--county", default="臺南市", help="County filter. Defaults to 臺南市.")
    parser.add_argument("--line", default="縱貫線", help="Line filter. Defaults to 縱貫線.")
    parser.add_argument(
        "--output",
        default="tainan_ratio_comparison.json",
        help="Output filename written under .runtime/crossings/.",
    )
    return parser


async def async_main(args: argparse.Namespace) -> None:
    settings = get_settings()
    catalog = get_crossing_catalog_service()
    station_graph = get_station_graph_service()

    dataset = await catalog.load()
    entries: list[dict[str, Any]] = []
    ratio_sources: Counter[str] = Counter()
    pair_sources: Counter[str] = Counter()

    for feature in dataset.get("features", []):
        properties = dict(feature.get("properties", {}))
        if properties.get("county") != args.county:
            continue
        if args.line and properties.get("line") != args.line:
            continue

        geometry = feature.get("geometry")
        if geometry is not None:
            coordinates = geometry.get("coordinates") or [None, None]
            if coordinates[0] is not None and coordinates[1] is not None:
                properties["geometry"] = {"lon": coordinates[0], "lat": coordinates[1]}

        enriched = await station_graph.enrich_crossing_properties(properties)
        ratio_source = str(enriched.get("ratio_source") or "unknown")
        pair_source = str(enriched.get("station_pair_source") or "unknown")
        ratio_sources[ratio_source] += 1
        pair_sources[pair_source] += 1

        geometry_ratio = enriched.get("geometry_segment_ratio")
        active_ratio = enriched.get("segment_ratio")
        delta_from_geometry = None
        if isinstance(active_ratio, (int, float)) and isinstance(geometry_ratio, (int, float)):
            delta_from_geometry = round(float(active_ratio) - float(geometry_ratio), 6)

        entries.append(
            {
                "crossing_id": enriched.get("crossing_id"),
                "name": enriched.get("name"),
                "km_marker": enriched.get("km_marker"),
                "station_pair_text": enriched.get("station_pair_text"),
                "query_station_pair_text": enriched.get("query_station_pair_text"),
                "station_pair_source": pair_source,
                "ratio_source": ratio_source,
                "segment_ratio": active_ratio,
                "official_segment_ratio": enriched.get("official_segment_ratio"),
                "path_segment_ratio": enriched.get("path_segment_ratio"),
                "geometry_segment_ratio": geometry_ratio,
                "delta_from_geometry": delta_from_geometry,
                "segment_confidence": enriched.get("segment_confidence"),
                "segment_confidence_reason": enriched.get("segment_confidence_reason"),
            }
        )

    entries.sort(key=lambda item: (item.get("km_marker") or "", item.get("name") or ""))
    payload = {
        "metadata": {
            "county": args.county,
            "line": args.line,
            "count": len(entries),
            "ratio_sources": dict(ratio_sources),
            "pair_sources": dict(pair_sources),
            "curated_path": str(settings.curated_crossings_geojson_path),
        },
        "entries": entries,
    }

    output_path = Path(settings.crossings_runtime_dir) / args.output
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(entries)} entries to {output_path}")
    print(f"Ratio sources: {dict(ratio_sources)}")
    print(f"Pair sources: {dict(pair_sources)}")


def main() -> None:
    args = build_parser().parse_args()
    anyio.run(async_main, args)


if __name__ == "__main__":
    main()