from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "CrossRadar"
    app_env: str = Field(default="development", alias="APP_ENV")
    app_host: str = Field(default="127.0.0.1", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")

    tdx_client_id: str = Field(alias="TDX_CLIENT_ID")
    tdx_client_secret: str = Field(alias="TDX_CLIENT_SECRET")
    tdx_token_url: str = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
    tdx_basic_base_url: str = "https://tdx.transportdata.tw/api/basic"

    tra_crossings_url: str = "https://www.railway.gov.tw/tra-tip-web/adr/about-public-info-6"
    osm_overpass_url: str = "https://overpass-api.de/api/interpreter"

    request_timeout_seconds: float = 30.0
    tdx_token_refresh_skew_seconds: int = 300
    allow_insecure_ssl_fallback: bool = Field(default=True, alias="APP_ALLOW_INSECURE_SSL_FALLBACK")
    http_user_agent: str = Field(default="CrossRadar/0.1", alias="APP_HTTP_USER_AGENT")

    runtime_dir: Path = ROOT_DIR / ".runtime"
    data_dir: Path = ROOT_DIR / "data"
    frontend_dir: Path = ROOT_DIR / "frontend" / "static"

    crossings_runtime_dir: Path = ROOT_DIR / ".runtime" / "crossings"
    crossings_raw_html_dir: Path = ROOT_DIR / ".runtime" / "crossings" / "raw_html"
    osm_runtime_dir: Path = ROOT_DIR / ".runtime" / "osm"
    crossings_data_dir: Path = ROOT_DIR / "data" / "crossings"
    official_crossings_json_path: Path = ROOT_DIR / "data" / "crossings" / "crossings_official.json"
    curated_crossings_geojson_path: Path = ROOT_DIR / "data" / "crossings" / "crossings_curated.geojson"
    manual_mappings_json_path: Path = ROOT_DIR / "data" / "crossings" / "manual_osm_mappings.json"
    unmatched_analysis_json_path: Path = ROOT_DIR / "data" / "crossings" / "unmatched_crossings_analysis.json"
    osm_raw_json_path: Path = ROOT_DIR / ".runtime" / "osm" / "taiwan_crossings.overpass.json"
    osm_geojson_path: Path = ROOT_DIR / "data" / "crossings" / "osm_crossings.geojson"
    tdx_runtime_dir: Path = ROOT_DIR / ".runtime" / "tdx"
    station_cache_path: Path = ROOT_DIR / ".runtime" / "tdx" / "stations.json"
    timetable_cache_path: Path = ROOT_DIR / ".runtime" / "tdx" / "today_timetables.json"

    def ensure_directories(self) -> None:
        for path in (
            self.runtime_dir,
            self.data_dir,
            self.frontend_dir,
            self.crossings_runtime_dir,
            self.crossings_raw_html_dir,
            self.osm_runtime_dir,
            self.crossings_data_dir,
            self.tdx_runtime_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
