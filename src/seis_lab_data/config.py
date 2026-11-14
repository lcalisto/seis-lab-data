import logging
import logging.config
import warnings
from pathlib import Path
from typing import (
    Annotated,
    Optional,
)

import jinja2
import sqlmodel
import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
)
from pydantic.networks import (
    PostgresDsn,
    RedisDsn,
)
from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)
from redis import asyncio as aioredis
from rich.console import Console
from rich.logging import RichHandler
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio.session import async_sessionmaker
from sqlalchemy.ext.asyncio.engine import (
    AsyncEngine,
    create_async_engine,
)
from sqlmodel.ext.asyncio.session import AsyncSession

from . import dispatch

warnings.filterwarnings(
    "ignore", r".*directory.*does not exist.*", UserWarning, module="pydantic_settings"
)


class SeisLabDataIconSettings(BaseModel):
    asset_discovery_configuration: str = "insert_drive_file"
    data_format: str = "insert_drive_file"
    dataset_category: str = "category"
    delete_item: str = "delete"
    discover_contents: str = "travel_explore"
    docs: str = "menu_book"
    download: str = "download"
    edit_item: str = "edit"
    home: str = "home"
    layout_compact: str = "view_headline"
    layout_regular: str = "view_agenda"
    new_item: str = "add_circle_outline"
    open_link: str = "open_in_new"
    projects: str = "view_kanban"
    search: str = "search"
    settings: str = "settings"
    expand_less: str = "expand_less"
    expand_more: str = "expand_more"
    export_item: str = "cloud_upload"
    source_code: str = "code"
    status_draft: str = "design_services"
    status_published: str = "visibility"
    survey_missions: str = "directions_boat"
    survey_related_records: str = "source"
    user: str = "person"
    view_details: str = "info"
    validation_valid: str = "check_circle"
    validation_invalid: str = "dangerous"
    workflow_stage: str = "stairs"


class TargetGeoNodeSettings(BaseModel):
    url: str
    public_url: str | None = None
    username: str
    password: str
    client_id: str
    client_secret: str


class SeisLabDataSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SEIS_LAB_DATA__",
        env_nested_delimiter="__",
        secrets_dir="/run/secrets",
    )

    auth_application_slug: str = "seis-lab-data"
    auth_client_id: str = "someid"
    auth_client_secret: str = "somesecret"
    auth_admin_token: str = "sometoken"
    auth_token_introspection_cache_seconds: int = 60
    csrf_secret: str = "somesecret"
    session_secret_key: str = "somesecretkey"
    auth_external_base_url: str = "http://localhost:9000"
    auth_internal_base_url: str = "http://localhost:9000"
    bind_host: str = "127.0.0.1"
    bind_port: int = 5001
    database_dsn: PostgresDsn = PostgresDsn(
        "postgresql+psycopg://sld:sldpass@localhost/seis_lab_data"
    )
    test_database_dsn: PostgresDsn = PostgresDsn(
        "postgresql+psycopg://sld:sldpass@localhost/seis_lab_data_test"
    )
    # connections each process keeps open to the database, plus those it may open
    # temporarily beyond them; a request for a connection fails after waiting
    # `db_pool_timeout` seconds for one to be free
    db_pool_size: PositiveInt = 5
    db_max_overflow: NonNegativeInt = 5
    db_pool_timeout: PositiveFloat = 30.0
    debug: bool = False
    log_config_file: Path | None = None
    num_web_worker_processes: int = 8
    public_url: str = "http://localhost:5001"
    docs_url: str = "http://localhost:8000"
    source_code_repository_url: str = "https://github.com/naturalgis/seis-lab-data"
    static_dir: Optional[Path] = Path(__file__).parent / "webapp/static"
    templates_dir: Optional[Path] = Path(__file__).parent / "webapp/templates"
    message_broker_dsn: Optional[RedisDsn] = RedisDsn("redis://localhost:6379")
    message_broker_channels: list[str] = ["demo-channel"]
    locales: list[str] = ["pt", "en"]
    translations_dir: Optional[Path] = Path(__file__).parent / "translations"
    pagination_page_size: int = 20
    webmap_base_tile_layer_url: str = (
        "https://localhost:8888/tiles/world-bathymetry/{z}/{x}/{y}.png"
    )
    # deepest zoom level served by the base tile layer, beyond it maps overscale
    # last available tiles instead of showing a blank background,
    webmap_base_tile_layer_max_zoom: int = 6
    # base tiles as the workers reach them, for thumbnails; any default would be a guess
    thumbnail_base_tile_layer_url: str | None = None
    webmap_default_center_lon: float = 0.0
    webmap_default_center_lat: float = 0.0
    webmap_default_zoom_level: int = 3
    webmap_default_polygon_fill_color: str = "#c27d0e"
    webmap_default_polygon_fill_opacity: float = 0.3
    webmap_default_polygon_outline_color: str = "#c27d0e"
    webmap_default_polygon_outline_opacity: float = 1.0
    webmap_default_polygon_outline_width: int = 4
    # the below WKT Polygon corresponds to the bbox of Portugal's Exclusive Economic Zone, as gotten
    # by postprocessing the dataset of the world EEZs, available
    # for download at https://www.marineregions.org/downloads.php#eez
    webmap_default_bbox_wkt: str = (
        "Polygon (("
        "-35.58558 29.24784, "
        "-7.25694 29.24784, "
        "-7.25694 43.06482, "
        "-35.58558 43.06482, "
        "-35.58558 29.24784"
        "))"
    )
    default_temporal_extent_begin: str = ""
    default_temporal_extent_end: str = ""
    readonly_archive_root_directory: Path = "/mnt/data"
    # concurrency of a discovery run's metadata extractions, i.e. how many files are
    # read at once; concurrent extractions overlap their waits on storage and, in
    # worker processes, use as many CPU cores
    discovery_extraction_concurrency: PositiveInt = 4
    # a discovery run looks up matched paths and writes records in batches of up to
    # this many files, each batch held for at most `discovery_batch_max_seconds`
    discovery_batch_size: PositiveInt = 500
    discovery_batch_max_seconds: PositiveFloat = 5.0
    # a discovery run stops after this long, keeping the records it created; at most
    # 7 days
    discovery_time_limit_hours: Annotated[PositiveFloat, Field(le=7 * 24)] = 24.0
    editable_archive_root_directory: Path = "/mnt/sld"
    icons: SeisLabDataIconSettings = SeisLabDataIconSettings()
    target_geonode: TargetGeoNodeSettings | None = None
    _db_engine: AsyncEngine | None = None
    _sync_db_engine: Engine | None = None
    _db_session_maker: async_sessionmaker | None = None
    _event_dispatcher: dispatch.EventDispatcherProtocol | None = None

    def get_db_engine(self) -> AsyncEngine:
        if self._db_engine is None:
            self._db_engine = create_async_engine(
                self.database_dsn.unicode_string(),
                pool_size=self.db_pool_size,
                max_overflow=self.db_max_overflow,
                pool_timeout=self.db_pool_timeout,
            )
        return self._db_engine

    def get_sync_db_engine(self) -> Engine:
        if self._sync_db_engine is None:
            self._sync_db_engine = sqlmodel.create_engine(
                self.database_dsn.unicode_string()
            )
        return self._sync_db_engine

    def get_db_session_maker(self) -> async_sessionmaker:
        if self._db_session_maker is None:
            self._db_session_maker = async_sessionmaker(
                autocommit=False,
                autoflush=False,
                bind=self.get_db_engine(),
                expire_on_commit=False,
                class_=AsyncSession,
            )
        return self._db_session_maker

    def get_event_dispatcher(self) -> dispatch.EventDispatcherProtocol:
        if self._event_dispatcher is None:
            self._event_dispatcher = dispatch.RedisEventDispatcher(
                redis_client=aioredis.from_url(self.message_broker_dsn.unicode_string())
            )
        return self._event_dispatcher


class SeisLabDataCliContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    jinja_environment: jinja2.Environment = jinja2.Environment()
    status_console: Console
    settings: SeisLabDataSettings
    redis_client: aioredis.Redis


def get_settings() -> SeisLabDataSettings:
    return SeisLabDataSettings()


def get_cli_context() -> SeisLabDataCliContext:
    settings = get_settings()
    return SeisLabDataCliContext(
        jinja_environment=_get_jinja_environment(settings),
        settings=settings,
        status_console=Console(stderr=True),
        redis_client=aioredis.from_url(settings.message_broker_dsn.unicode_string()),
    )


def configure_logging(
    cli_context: SeisLabDataCliContext,
) -> None:
    if cli_context.settings.log_config_file:
        logging_dict_conf = (
            yaml.safe_load(cli_context.settings.log_config_file.read_text())
            if cli_context.settings.log_config_file
            else {}
        )
        logging.config.dictConfig(logging_dict_conf)
    else:
        logging.basicConfig(
            level=logging.DEBUG if cli_context.settings.debug else logging.WARNING,
            handlers=[
                RichHandler(console=cli_context.status_console, rich_tracebacks=True)
            ],
        )


def _get_jinja_environment(settings: SeisLabDataSettings) -> jinja2.Environment:
    env = jinja2.Environment()
    return env
