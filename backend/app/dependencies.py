from __future__ import annotations

from functools import lru_cache

from backend.app.clients.tdx_auth import TdxTokenManager
from backend.app.clients.tdx_tra import TdxTraClient
from backend.app.config import get_settings
from backend.app.services.crossing_catalog import CrossingCatalogService
from backend.app.services.manual_mapping import ManualOsmMappingService
from backend.app.services.crossing_scraper import TraOfficialCrossingScraper
from backend.app.services.osm_enricher import OsmEnricher
from backend.app.services.predictor import PredictorService
from backend.app.services.rail_path import RailPathService
from backend.app.services.station_graph import StationGraphService


@lru_cache(maxsize=1)
def get_token_manager() -> TdxTokenManager:
    return TdxTokenManager(get_settings())


@lru_cache(maxsize=1)
def get_tdx_client() -> TdxTraClient:
    return TdxTraClient(get_token_manager(), get_settings())


@lru_cache(maxsize=1)
def get_crossing_scraper() -> TraOfficialCrossingScraper:
    return TraOfficialCrossingScraper(get_settings())


@lru_cache(maxsize=1)
def get_osm_enricher() -> OsmEnricher:
    return OsmEnricher(get_settings())


@lru_cache(maxsize=1)
def get_crossing_catalog_service() -> CrossingCatalogService:
    return CrossingCatalogService(
        get_crossing_scraper(),
        get_osm_enricher(),
        get_settings(),
        station_graph_service=get_station_graph_service(),
    )


@lru_cache(maxsize=1)
def get_rail_path_service() -> RailPathService:
    return RailPathService(get_settings())


@lru_cache(maxsize=1)
def get_manual_mapping_service() -> ManualOsmMappingService:
    return ManualOsmMappingService(
        get_crossing_catalog_service(),
        get_osm_enricher(),
        get_settings(),
        get_station_graph_service(),
    )


@lru_cache(maxsize=1)
def get_station_graph_service() -> StationGraphService:
    return StationGraphService(get_tdx_client(), get_rail_path_service())


@lru_cache(maxsize=1)
def get_predictor_service() -> PredictorService:
    return PredictorService(get_tdx_client(), get_crossing_catalog_service(), get_station_graph_service())
