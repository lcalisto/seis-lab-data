import asyncio
import contextlib
import dataclasses
import datetime as dt
import heapq
import json
import logging
import math
import pathlib
import posixpath
import re
import time
import uuid

import pydantic
import shapely
from anyio import (
    Path,
    to_process,
    to_thread,
)
from geoalchemy2 import WKBElement
from osgeo import osr
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from .. import (
    config,
    constants,
    dispatch,
    errors,
    pathpatterns,
)
from ..db import models
from ..db.queries import (
    discovery as discovery_queries,
    surveymissions as mission_queries,
    surveyrelatedrecords as record_queries,
    recordassets as asset_queries,
)
from ..db.commands import (
    discovery as discovery_commands,
    surveymissions as mission_commands,
    surveyrelatedrecords as record_commands,
)
from ..db.commands.common import get_bbox_4326_for_db
from ..permissions import (
    discovery as discovery_permissions,
    surveymissions as mission_permissions,
    surveyrelatedrecords as record_permissions,
)
from ..schemas import (
    events as event_schemas,
    discovery as discovery_schemas,
    identifiers,
    surveyrelatedrecords as record_schemas,
    user as user_schemas,
    validation as validation_schemas,
)
from ..tasks import previews as preview_tasks
from ..tasks.extractors import (
    common as extractor_common,
    dispatch as extractor_dispatch,
    schemas as extractor_schemas,
)

from . import (
    surveymissions as mission_ops,
    surveyrelatedrecords as record_ops,
)

logger = logging.getLogger(__name__)

# Buffer applied to every extracted bbox (~10 m in degrees): noise on multi-km
# footprints, but keeps point/line extents visible on the map and avoids the
# degenerate zero-area polygons that shapely marks invalid.
_BBOX_BUFFER = 1e-4


async def create_asset_discovery_configuration(
    *,
    request_id: identifiers.RequestId,
    to_create: discovery_schemas.AssetDiscoveryConfigurationCreate,
    initiator: user_schemas.User,
    session: AsyncSession,
    event_dispatcher: dispatch.EventDispatcherProtocol,
) -> models.AssetDiscoveryConfiguration | None:
    try:
        if not discovery_permissions.can_create_asset_discovery_configuration(
            initiator
        ):
            raise errors.SeisLabDataError(
                "User is not allowed to create an asset discovery configuration."
            )
        asset_discovery_configuration = (
            await discovery_commands.create_asset_discovery_configuration(
                session, to_create
            )
        )
    except errors.SeisLabDataError as err:
        await event_dispatcher(
            event_schemas.ResourceModificationEvent(
                initiator=initiator.id,
                request_id=request_id,
                resource_type=constants.ResourceType.ASSET_DISCOVERY_CONFIG,
                resource_id=None,
                resource_name=to_create.name,
                modification=constants.ResourceModification.CREATED,
                succeeded=False,
                details=str(err),
            )
        )
        return None

    await event_dispatcher(
        event_schemas.ResourceModificationEvent(
            initiator=initiator.id,
            request_id=request_id,
            resource_type=constants.ResourceType.ASSET_DISCOVERY_CONFIG,
            resource_id=str(asset_discovery_configuration.id),
            resource_name=asset_discovery_configuration.name,
            modification=constants.ResourceModification.CREATED,
            succeeded=True,
        )
    )
    return asset_discovery_configuration


async def update_asset_discovery_configuration(
    request_id: identifiers.RequestId,
    asset_discovery_configuration_id: identifiers.AssetDiscoveryConfId,
    to_update: discovery_schemas.AssetDiscoveryConfigurationUpdate,
    initiator: user_schemas.User,
    session: AsyncSession,
    event_dispatcher: dispatch.EventDispatcherProtocol,
) -> models.AssetDiscoveryConfiguration | None:
    resource_name = None
    try:
        if (
            asset_discovery_conf
            := await discovery_queries.get_asset_discovery_configuration(
                session, asset_discovery_configuration_id
            )
        ) is None:
            raise errors.SeisLabDataError(
                f"asset discovery configuration with id {asset_discovery_configuration_id} does not exist."
            )
        resource_name = asset_discovery_conf.name
        if not discovery_permissions.can_update_asset_discovery_configuration(
            initiator
        ):
            raise errors.SeisLabDataError(
                "User is not allowed to update asset discovery configuration."
            )
        updated_asset_discovery_conf = (
            await discovery_commands.update_asset_discovery_configuration(
                session, asset_discovery_conf, to_update
            )
        )
    except errors.SeisLabDataError as err:
        await event_dispatcher(
            event_schemas.ResourceModificationEvent(
                initiator=initiator.id,
                request_id=request_id,
                resource_type=constants.ResourceType.ASSET_DISCOVERY_CONFIG,
                resource_id=str(asset_discovery_configuration_id),
                resource_name=resource_name,
                modification=constants.ResourceModification.UPDATED,
                succeeded=False,
                details=str(err),
            )
        )
        return None

    await event_dispatcher(
        event_schemas.ResourceModificationEvent(
            initiator=initiator.id,
            request_id=request_id,
            resource_type=constants.ResourceType.ASSET_DISCOVERY_CONFIG,
            resource_id=str(asset_discovery_configuration_id),
            resource_name=updated_asset_discovery_conf.name,
            modification=constants.ResourceModification.UPDATED,
            succeeded=True,
        )
    )
    return updated_asset_discovery_conf


async def delete_asset_discovery_configuration(
    *,
    request_id: identifiers.RequestId,
    asset_discovery_configuration_id: identifiers.AssetDiscoveryConfId,
    initiator: user_schemas.User,
    session: AsyncSession,
    event_dispatcher: dispatch.EventDispatcherProtocol,
) -> None:
    resource_name = None
    try:
        if (
            asset_discovery_conf
            := await discovery_queries.get_asset_discovery_configuration(
                session, asset_discovery_configuration_id
            )
        ) is None:
            raise errors.SeisLabDataError(
                f"asset discovery configuration with id {asset_discovery_configuration_id} does not exist."
            )
        resource_name = asset_discovery_conf.name
        if not discovery_permissions.can_delete_asset_discovery_configuration(
            initiator
        ):
            raise errors.SeisLabDataError(
                "User is not allowed to delete asset discovery configuration."
            )
        await discovery_commands.delete_asset_discovery_configuration(
            session, asset_discovery_configuration_id
        )
    except errors.SeisLabDataError as err:
        await event_dispatcher(
            event_schemas.ResourceModificationEvent(
                initiator=initiator.id,
                request_id=request_id,
                resource_type=constants.ResourceType.ASSET_DISCOVERY_CONFIG,
                resource_id=str(asset_discovery_configuration_id),
                resource_name=resource_name,
                modification=constants.ResourceModification.DELETED,
                succeeded=False,
                details=str(err),
            ),
        )
        return None

    await event_dispatcher(
        event_schemas.ResourceModificationEvent(
            initiator=initiator.id,
            request_id=request_id,
            resource_type=constants.ResourceType.ASSET_DISCOVERY_CONFIG,
            resource_id=str(asset_discovery_configuration_id),
            resource_name=resource_name,
            modification=constants.ResourceModification.DELETED,
            succeeded=True,
        ),
    )


async def run_mission_discovery(
    *,
    request_id: identifiers.RequestId,
    mission_id: identifiers.SurveyMissionId,
    session: AsyncSession,
    event_dispatcher: dispatch.EventDispatcherProtocol,
    settings: config.SeisLabDataSettings,
    user: user_schemas.User,
) -> None:
    """Discover the files of a survey mission and create records for them.

    The mission is held under discovery while the run lasts, and its heartbeat is
    refreshed in the background. The run stops early if the mission's status is
    set to cancelling discovery; the records created until then are kept. The
    mission's original status is restored at the end of the run, whatever its
    outcome. When that status is published, the mission's valid draft records are
    then published, the records of this run among them, as are those of a mission
    update. Preview generation for the mission is enqueued unless the run fails.
    """
    mission_name = None
    try:
        if (
            mission := await mission_queries.get_survey_mission(session, mission_id)
        ) is None:
            raise errors.SeisLabDataError(
                f"Survey mission with id {mission_id} does not exist."
            )
        mission_name = mission.name
        if not mission_permissions.can_discover_survey_mission(user, mission):
            raise errors.SeisLabDataError(
                "User is not allowed to run discovery on this survey mission."
            )
        if (mission_status := mission.status) not in (
            constants.SurveyMissionStatus.DRAFT,
            constants.SurveyMissionStatus.PUBLISHED,
        ):
            raise errors.SeisLabDataError(
                f"Cannot run discovery on survey mission because its status is "
                f"{mission_status}"
            )
        # an empty path would be the archive root, and `..` could lead out of the
        # mission's directory: either one would have the files of other missions
        # discovered as this mission's
        if (
            normalized_path := posixpath.normpath(mission.relative_path.strip("/"))
        ) == "." or normalized_path.split("/")[0] == "..":
            raise errors.SeisLabDataError(
                f"Cannot run discovery on survey mission because its relative path "
                f"{mission.relative_path!r} does not name a directory inside the "
                f"archive"
            )
        if not await mission_commands.compare_and_set_survey_mission_status(
            session,
            mission_id,
            mission_status,
            constants.SurveyMissionStatus.UNDER_DISCOVERY,
        ):
            raise errors.SeisLabDataError(
                "Cannot run discovery on survey mission because its status "
                "changed meanwhile"
            )
    except errors.SeisLabDataError as err:
        await event_dispatcher(
            event_schemas.DiscoveryEvent(
                initiator=user.id,
                resource_type=constants.ResourceType.MISSION,
                resource_id=str(mission_id),
                resource_name=mission_name,
                request_id=request_id,
                modification=constants.DiscoveryStage.ENDED,
                succeeded=False,
                details=str(err),
            )
        )
        return

    # from here on the mission is under discovery, and every way out of the
    # block below must report the end of the run and give the mission back its
    # status
    cancellation_requested = asyncio.Event()
    time_limit = asyncio.timeout(settings.discovery_time_limit_hours * 60 * 60)
    started_at = models.now_()
    heartbeat = asyncio.create_task(
        _refresh_discovery_heartbeat(
            mission_id, settings.get_db_session_maker(), cancellation_requested
        )
    )
    try:
        logger.debug(f"Discovering contents of mission {mission.name!r}...")
        asset_discovery_configs = (
            await discovery_queries.collect_all_asset_discovery_configurations(session)
        )
        # when there is a failure, the db session is rolled back, expiring everything it
        # holds; we dettach the mission and asset discovery confs in order to
        # keep them alive
        session.expunge(mission)
        for asset_discovery_conf in asset_discovery_configs:
            session.expunge(asset_discovery_conf)
        await event_dispatcher(
            event_schemas.ResourceStatusChangedEvent(
                request_id=request_id,
                initiator=user.id,
                resource_type=constants.ResourceType.MISSION,
                resource_id=str(mission_id),
                resource_name=mission_name,
                succeeded=True,
                new_status=constants.SurveyMissionStatus.UNDER_DISCOVERY,
            )
        )
        await event_dispatcher(
            event_schemas.DiscoveryEvent(
                initiator=user.id,
                resource_type=constants.ResourceType.MISSION,
                resource_id=str(mission_id),
                resource_name=mission_name,
                request_id=request_id,
                modification=constants.DiscoveryStage.STARTED,
                succeeded=True,
            )
        )
        async with time_limit:
            counts = await _discover_mission_records(
                request_id=request_id,
                mission=mission,
                session=session,
                event_dispatcher=event_dispatcher,
                settings=settings,
                user=user,
                asset_discovery_configs=asset_discovery_configs,
                cancellation_requested=cancellation_requested,
            )
    # raised into the run when dramatiq interrupts it, e.g. at its time limit
    except asyncio.CancelledError:
        logger.warning(f"Discovery of mission {mission_id} was interrupted")
        await event_dispatcher(
            event_schemas.DiscoveryEvent(
                initiator=user.id,
                resource_type=constants.ResourceType.MISSION,
                resource_id=str(mission_id),
                resource_name=mission_name,
                request_id=request_id,
                modification=constants.DiscoveryStage.ENDED,
                succeeded=False,
                details=(
                    "discovery was interrupted - the records created so far are "
                    "kept, run it again to resume"
                ),
            )
        )
        raise
    except Exception as err:
        logger.exception(f"Discovery of mission {mission_id} failed")
        await event_dispatcher(
            event_schemas.DiscoveryEvent(
                initiator=user.id,
                resource_type=constants.ResourceType.MISSION,
                resource_id=str(mission_id),
                resource_name=mission_name,
                request_id=request_id,
                modification=constants.DiscoveryStage.ENDED,
                succeeded=False,
                # anything else may carry internals, such as SQL, which stay in the logs
                details=(
                    f"discovery exceeded its time limit of "
                    f"{settings.discovery_time_limit_hours:g} hours - the records "
                    f"created so far are kept, run it again to resume"
                    if time_limit.expired()
                    else str(err)
                    if isinstance(err, (errors.SeisLabDataError, FileNotFoundError))
                    else f"unexpected error ({type(err).__name__})"
                ),
            )
        )
    else:
        await event_dispatcher(
            event_schemas.DiscoveryEvent(
                initiator=user.id,
                resource_type=constants.ResourceType.MISSION,
                resource_id=str(mission_id),
                resource_name=mission_name,
                request_id=request_id,
                modification=(
                    constants.DiscoveryStage.CANCELLED
                    if counts.cancelled
                    else constants.DiscoveryStage.ENDED
                ),
                succeeded=True,
                details=counts.describe(),
            )
        )
        # the records created by this run had their previews requested as they
        # were written; this covers the older records still missing previews
        preview_tasks.generate_mission_previews.send(
            raw_request_id=str(request_id),
            raw_survey_mission_id=str(mission_id),
            raw_initiator=json.dumps(dataclasses.asdict(user)),
            raw_created_before=started_at.isoformat(),
        )
    finally:
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat
        # whatever was left half-done must not be committed with the status
        await session.rollback()
        await mission_ops.change_survey_mission_status(
            request_id=request_id,
            target_status=mission_status,
            survey_mission_id=mission_id,
            initiator=user,
            session=session,
            event_dispatcher=event_dispatcher,
        )
        if mission_status == constants.SurveyMissionStatus.PUBLISHED:
            published_count = (
                await record_commands.bulk_publish_valid_survey_related_records(
                    session, mission_id
                )
            )
            if published_count:
                await event_dispatcher(
                    event_schemas.BulkResourceModificationEvent(
                        initiator=user.id,
                        request_id=request_id,
                        resource_type=constants.ResourceType.RECORD,
                        modification=constants.BulkResourceModification.UPDATED,
                        succeeded=True,
                        affected_count=published_count,
                    )
                )


async def _refresh_discovery_heartbeat(
    mission_id: identifiers.SurveyMissionId,
    session_maker: async_sessionmaker,
    cancellation_requested: asyncio.Event,
) -> None:
    """Refresh the heartbeat of a survey mission under discovery, until cancelled.

    The heartbeat is refreshed every `DISCOVERY_HEARTBEAT_INTERVAL_SECONDS`, each
    time in a session of its own. `cancellation_requested` is set once the
    mission's status is cancelling discovery. Refresh errors are logged.
    """
    while True:
        try:
            async with session_maker() as session:
                status = (
                    await mission_commands.refresh_survey_mission_discovery_heartbeat(
                        session, mission_id
                    )
                )
        except Exception:
            logger.exception(
                f"Could not refresh the discovery heartbeat of mission {mission_id}"
            )
        else:
            if status == constants.SurveyMissionStatus.CANCELLING_DISCOVERY:
                cancellation_requested.set()
        await asyncio.sleep(constants.DISCOVERY_HEARTBEAT_INTERVAL_SECONDS)


# number of slowest extractions named in the discovery timings
_SLOWEST_EXTRACTIONS_LOGGED = 5


@dataclasses.dataclass
class _DiscoveryCounts:
    """Counts and timings of the files processed by a discovery run."""

    found: int = 0
    created: int = 0
    failed: int = 0
    invalid_configuration_names: list[str] = dataclasses.field(default_factory=list)
    cancelled: bool = False
    started_at: float = dataclasses.field(default_factory=time.monotonic)
    walk_seconds: float = 0.0
    # summed over the extractions, which run concurrently
    extraction_seconds: float = 0.0
    db_seconds: float = 0.0
    # min-heap of (seconds, relative path), holding the slowest extractions
    slowest_extractions: list[tuple[float, str]] = dataclasses.field(
        default_factory=list
    )

    def describe(self) -> str:
        """Return a summary of the counts."""
        summary = f"{self.found} files found, {self.created} new records"
        if self.failed:
            summary += f", {self.failed} files could not be discovered"
        if self.invalid_configuration_names:
            summary += (
                f", invalid asset discovery configurations: "
                f"{', '.join(self.invalid_configuration_names)}"
            )
        return summary

    def describe_timings(self) -> str:
        """Return a summary of where the run's time went, for the logs.

        The walk, the extractions and the DB work overlap, so their times do not
        add up to the elapsed time. Extraction time is summed over the extractions
        that ran concurrently.
        """
        elapsed = time.monotonic() - self.started_at
        rate = self.found / elapsed if elapsed > 0 else 0.0
        slowest = ", ".join(
            f"{path} ({seconds:.1f} s)"
            for seconds, path in sorted(self.slowest_extractions, reverse=True)
        )
        return (
            f"{self.found} files in {elapsed:.1f} s ({rate:.2f} files/s): "
            f"walk {self.walk_seconds:.1f} s, "
            f"extraction {self.extraction_seconds:.1f} s (summed), "
            f"DB {self.db_seconds:.1f} s; "
            f"slowest extractions: {slowest or 'none'}"
        )


@dataclasses.dataclass
class _DiscoveredFile:
    """A matched file on its way through a discovery run."""

    relative_path: str
    configuration: models.AssetDiscoveryConfiguration
    # tracked record whose extent is updated; None when a new record is created
    record_id: identifiers.SurveyRelatedRecordId | None = None
    metadata: extractor_schemas.ExtractionResult | None = None
    bbox_wkt: str | None = None


async def _discover_mission_records(
    *,
    request_id: identifiers.RequestId,
    mission: models.SurveyMission,
    session: AsyncSession,
    event_dispatcher: dispatch.EventDispatcherProtocol,
    settings: config.SeisLabDataSettings,
    user: user_schemas.User,
    asset_discovery_configs: list[models.AssetDiscoveryConfiguration],
    cancellation_requested: asyncio.Event,
) -> _DiscoveryCounts:
    """Create records for the mission files that match asset discovery configurations.

    Only the directories along or below the literal prefixes of the configurations'
    path patterns are walked, once. Each file is assigned to the first
    configuration, in the given order, whose path pattern matches it. Configurations
    with an invalid path pattern are logged and skipped.

    The work is pipelined: the walk looks up matched paths in chunks of
    `discovery_batch_size`, `discovery_extraction_concurrency` extractions run
    concurrently, and a single writer stores the results in batches of up to
    `discovery_batch_size` files, each one written at most
    `discovery_batch_max_seconds` after it began. Chunks are held for at most as
    long. Tracked files are skipped, unless their record has no bbox and the
    mission's CRS is projected, in which case its extent is updated once per run. A
    batch that fails is written again file by file, so that a failing file is
    counted and skipped. Lookups use sessions of their own, writes use `session`.

    Once `cancellation_requested` is set the walk stops and queued files are left
    alone, while the files already being extracted are still written. A progress
    event is dispatched at most every `DISCOVERY_PROGRESS_INTERVAL_SECONDS`.

    Returns the counts of the processed files.
    """
    mission_root_path = Path(
        "/".join(
            (
                str(settings.readonly_archive_root_directory),
                mission.relative_path,
            )
        )
    )
    logger.debug(f"{mission_root_path=}")
    # without the mission's directory there is nothing to search
    if not await mission_root_path.is_dir():
        raise FileNotFoundError(
            f"The mission's directory {mission.relative_path!r} is not in the archive"
        )
    # under a geographic CRS only a header code could place metres: not worth a re-read
    extent_update_enabled = _is_projected_crs(mission.implicit_crs)
    if not extent_update_enabled:
        logger.info(
            "Records without a bbox are not read again: the mission's EPSG:%s is not "
            "a projected CRS",
            mission.implicit_crs,
        )
    counts = _DiscoveryCounts()
    patterns = []
    matchable_configs = []
    for asset_discovery_conf in asset_discovery_configs:
        try:
            patterns.append(
                pathpatterns.compile_path_pattern(
                    asset_discovery_conf.relative_path_regexp
                )
            )
        except re.error as err:
            logger.warning(
                f"Asset discovery configuration {asset_discovery_conf.name!r} has an "
                f"invalid path pattern: {err}"
            )
            counts.invalid_configuration_names.append(asset_discovery_conf.name)
        else:
            matchable_configs.append(asset_discovery_conf)
    pattern_set = pathpatterns.PathPatternSet(patterns)
    mission_id = identifiers.SurveyMissionId(mission.id)
    session_maker = settings.get_db_session_maker()
    concurrency = settings.discovery_extraction_concurrency
    batch_size = settings.discovery_batch_size
    batch_max_seconds = settings.discovery_batch_max_seconds
    # a None item ends each queue; the size bounds keep the directory walk from
    # getting far ahead of the extraction, and the extraction ahead of the writer
    to_extract: asyncio.Queue[_DiscoveredFile | None] = asyncio.Queue(
        maxsize=concurrency
    )
    extracted: asyncio.Queue[_DiscoveredFile | None] = asyncio.Queue(maxsize=batch_size)
    running_extractors = concurrency
    # a record with several data assets is updated once, from its first file
    attempted_record_ids: set[identifiers.SurveyRelatedRecordId] = set()
    last_progress_at = time.monotonic()

    async def report_progress() -> None:
        nonlocal last_progress_at
        if (
            time.monotonic() - last_progress_at
            < constants.DISCOVERY_PROGRESS_INTERVAL_SECONDS
        ):
            return
        last_progress_at = time.monotonic()
        logger.info(
            f"Discovery of mission {mission.name!r} in progress: "
            f"{counts.describe_timings()}"
        )
        await event_dispatcher(
            event_schemas.DiscoveryEvent(
                initiator=user.id,
                resource_type=constants.ResourceType.MISSION,
                resource_id=str(mission.id),
                resource_name=mission.name,
                request_id=request_id,
                modification=constants.DiscoveryStage.PROGRESS,
                succeeded=True,
                details=counts.describe(),
            )
        )

    async def schedule_path_chunk(chunk: list[_DiscoveredFile]) -> None:
        lookup_started_at = time.monotonic()
        # own session: the writer task uses `session` concurrently, and a session
        # cannot be shared between concurrent tasks
        async with session_maker() as lookup_session:
            tracked_file_paths = (
                await asset_queries.collect_survey_mission_tracked_file_paths(
                    lookup_session,
                    mission_id,
                    [discovered.relative_path for discovered in chunk],
                )
            )
        counts.db_seconds += time.monotonic() - lookup_started_at
        found_before = counts.found
        for discovered in chunk:
            if (
                tracked := tracked_file_paths.get(discovered.relative_path)
            ) is not None:
                record_id, has_bbox = tracked
                # a tracked record lacks a bbox when its file was discovered while the
                # mission's CRS was geographic; its extent is updated once per run
                if (
                    not extent_update_enabled
                    or has_bbox
                    or record_id in attempted_record_ids
                ):
                    logger.debug(
                        f"file {discovered.relative_path!r} is already tracked in "
                        f"the DB"
                    )
                    counts.found += 1
                    continue
                attempted_record_ids.add(record_id)
                discovered.record_id = record_id
            await to_extract.put(discovered)
        # on a re-run most files are already tracked and only counted here, so
        # progress must also be reported here
        if counts.found > found_before:
            await report_progress()

    async def walk_mission_directory() -> None:
        walk_started_at = time.monotonic()
        scheduling_seconds = 0.0
        chunk: list[_DiscoveredFile] = []
        chunk_started_at = time.monotonic()
        async with contextlib.aclosing(
            pathpatterns.iter_relative_file_paths(
                mission_root_path, pattern_set.prefixes
            )
        ) as relative_file_paths:
            async for relative_file_path in relative_file_paths:
                if cancellation_requested.is_set():
                    break
                if (match_index := pattern_set.first_match(relative_file_path)) is None:
                    continue
                if not chunk:
                    chunk_started_at = time.monotonic()
                chunk.append(
                    _DiscoveredFile(
                        relative_path=relative_file_path,
                        configuration=matchable_configs[match_index],
                    )
                )
                if (
                    len(chunk) >= batch_size
                    or time.monotonic() - chunk_started_at >= batch_max_seconds
                ):
                    scheduling_started_at = time.monotonic()
                    await schedule_path_chunk(chunk)
                    scheduling_seconds += time.monotonic() - scheduling_started_at
                    chunk = []
        if chunk and not cancellation_requested.is_set():
            scheduling_started_at = time.monotonic()
            await schedule_path_chunk(chunk)
            scheduling_seconds += time.monotonic() - scheduling_started_at
        counts.walk_seconds = time.monotonic() - walk_started_at - scheduling_seconds
        for _ in range(concurrency):
            await to_extract.put(None)

    async def extract_queued_file_metadata() -> None:
        nonlocal running_extractors
        while (discovered := await to_extract.get()) is not None:
            # after cancellation, drain the queue without extracting
            if cancellation_requested.is_set():
                continue
            extraction_started_at = time.monotonic()
            discovered.metadata, discovered.bbox_wkt = await _extract_file_metadata(
                str(mission_root_path / discovered.relative_path),
                mission.implicit_crs,
                # the extractors' Python code holds the GIL: in threads, concurrent
                # extractions would share a single CPU core
                in_worker_process=True,
            )
            extraction_seconds = time.monotonic() - extraction_started_at
            counts.extraction_seconds += extraction_seconds
            logger.debug(
                "Extracted %r in %.3f s", discovered.relative_path, extraction_seconds
            )
            if len(counts.slowest_extractions) < _SLOWEST_EXTRACTIONS_LOGGED:
                heapq.heappush(
                    counts.slowest_extractions,
                    (extraction_seconds, discovered.relative_path),
                )
            else:
                heapq.heappushpop(
                    counts.slowest_extractions,
                    (extraction_seconds, discovered.relative_path),
                )
            await extracted.put(discovered)
        running_extractors -= 1
        if running_extractors == 0:
            await extracted.put(None)

    async def write_batch(batch: list[_DiscoveredFile]) -> None:
        write_started_at = time.monotonic()
        counts.found += len(batch)
        creations = []
        for discovered in batch:
            if discovered.record_id is not None:
                continue
            try:
                creations.append(
                    (discovered, *_build_discovered_record_rows(discovered, mission))
                )
            except Exception:
                logger.exception(
                    f"Could not discover file {discovered.relative_path!r}"
                )
                counts.failed += 1
        # a record whose file still yields no bbox is left unchanged
        update_candidates = [
            discovered
            for discovered in batch
            if discovered.record_id is not None and discovered.bbox_wkt is not None
        ]
        extent_updates = []
        if update_candidates:
            current_fields = (
                await record_queries.collect_survey_related_record_validation_fields(
                    session, [discovered.record_id for discovered in update_candidates]
                )
            )
            for discovered in update_candidates:
                # the record was deleted after its path was looked up
                if (fields := current_fields.get(discovered.record_id)) is None:
                    continue
                extent_updates.append(
                    (discovered, _build_extent_update(discovered, fields))
                )
        try:
            await discovery_commands.write_discovered_survey_related_records(
                session,
                records=[record_row for _, record_row, _ in creations],
                assets=[asset_row for _, _, asset_row in creations],
                extent_updates=[update for _, update in extent_updates],
            )
        except Exception:
            await session.rollback()
            logger.warning(
                f"Could not write a batch of {len(batch)} discovered files, writing "
                f"them one by one",
                exc_info=True,
            )
            written = []
            for discovered, record_row, asset_row in creations:
                try:
                    await discovery_commands.write_discovered_survey_related_records(
                        session,
                        records=[record_row],
                        assets=[asset_row],
                        extent_updates=[],
                    )
                except Exception:
                    logger.exception(
                        f"Could not discover file {discovered.relative_path!r}"
                    )
                    counts.failed += 1
                    await session.rollback()
                else:
                    counts.created += 1
                    written.append((discovered, record_row))
            for discovered, extent_update in extent_updates:
                try:
                    await discovery_commands.write_discovered_survey_related_records(
                        session, records=[], assets=[], extent_updates=[extent_update]
                    )
                except Exception:
                    logger.exception(
                        f"Could not update the extent of the record of {discovered.relative_path!r}"
                    )
                    counts.failed += 1
                    await session.rollback()
        else:
            counts.created += len(creations)
            written = [
                (discovered, record_row) for discovered, record_row, _ in creations
            ]
        counts.db_seconds += time.monotonic() - write_started_at
        # whether a record gets previews is decided by the derivation itself
        preview_record_ids = [
            str(record_row["id"])
            for discovered, record_row in written
            if discovered.configuration.generate_previews
        ]
        for start in range(0, len(preview_record_ids), constants.PREVIEW_BATCH_SIZE):
            preview_tasks.generate_records_previews.send(
                raw_request_id=str(request_id),
                raw_survey_related_record_ids=preview_record_ids[
                    start : start + constants.PREVIEW_BATCH_SIZE
                ],
                raw_initiator=json.dumps(dataclasses.asdict(user)),
            )
        await report_progress()

    async def write_record_batches() -> None:
        batch: list[_DiscoveredFile] = []
        batch_started_at = time.monotonic()
        while True:
            timeout = (
                max(0.0, batch_started_at + batch_max_seconds - time.monotonic())
                if batch
                else None
            )
            try:
                discovered = await asyncio.wait_for(extracted.get(), timeout)
            except TimeoutError:
                await write_batch(batch)
                batch = []
                continue
            if discovered is None:
                break
            if not batch:
                batch_started_at = time.monotonic()
            batch.append(discovered)
            if len(batch) >= batch_size:
                await write_batch(batch)
                batch = []
        if batch:
            await write_batch(batch)

    try:
        async with asyncio.TaskGroup() as task_group:
            task_group.create_task(walk_mission_directory())
            for _ in range(concurrency):
                task_group.create_task(extract_queued_file_metadata())
            task_group.create_task(write_record_batches())
        # a run is reported as cancelled even if all its files were already being
        # extracted when cancellation was requested
        counts.cancelled = cancellation_requested.is_set()
    # re-raise the first error only; errors of the other tasks are caused by it
    except ExceptionGroup as group:
        raise group.exceptions[0]
    finally:
        # logged even for failed or cancelled runs, as partial timings still show
        # which discovery stage is slowest
        logger.info(
            f"Discovery of mission {mission.name!r} ended: {counts.describe_timings()}"
        )
    return counts


def _build_discovered_record_rows(
    discovered: _DiscoveredFile, mission: models.SurveyMission
) -> tuple[dict, dict]:
    """Build the record row and data asset row of a discovered file.

    The fields are validated with `SurveyRelatedRecordCreate`, the record status is
    `DRAFT` and its validation result is computed with `ValidSurveyRelatedRecord`.
    Raises `pydantic.ValidationError` for fields not valid in a draft record.

    Returns the record row and the asset row, as column values.
    """
    file_path = pathlib.PurePosixPath(discovered.relative_path)
    metadata = discovered.metadata
    to_create = record_schemas.SurveyRelatedRecordCreate(
        id=identifiers.SurveyRelatedRecordId(uuid.uuid4()),
        survey_mission_id=identifiers.SurveyMissionId(mission.id),
        # names are capped, the full file name lives on in the asset's path
        name=file_path.name[: constants.NAME_MAX_LENGTH],
        description=metadata.describe() if metadata is not None else "",
        dataset_category_id=identifiers.DatasetCategoryId(
            discovered.configuration.dataset_category_id
        ),
        workflow_stage_id=identifiers.WorkflowStageId(
            discovered.configuration.workflow_stage_id
        ),
        bbox_4326=discovered.bbox_wkt,
        temporal_extent_begin=metadata.temporal_extent_begin if metadata else None,
        temporal_extent_end=metadata.temporal_extent_end if metadata else None,
        assets=[
            record_schemas.DataRecordAssetCreate(
                id=identifiers.RecordAssetId(uuid.uuid4()),
                name=file_path.stem[: constants.NAME_MAX_LENGTH],
                description="",
                relative_path=discovered.relative_path,
            )
        ],
    )
    bbox_wkt = (
        get_bbox_4326_for_db(to_create.bbox_4326)
        if to_create.bbox_4326 is not None
        else None
    )
    record_row = {
        "id": to_create.id,
        "name": to_create.name,
        "description": to_create.description,
        "status": constants.SurveyRelatedRecordStatus.DRAFT,
        "survey_mission_id": to_create.survey_mission_id,
        "dataset_category_id": to_create.dataset_category_id,
        "workflow_stage_id": to_create.workflow_stage_id,
        "links": [],
        "bbox_4326": bbox_wkt,
        "temporal_extent_begin": to_create.temporal_extent_begin,
        "temporal_extent_end": to_create.temporal_extent_end,
        "created_at": models.now_(),
    }
    record_row["validation_result"] = _validate_record_fields(
        record_row
        | {
            "bbox_4326": (
                WKBElement(shapely.to_wkb(shapely.from_wkt(bbox_wkt)), srid=4326)
                if bbox_wkt is not None
                else None
            )
        }
    )
    (asset,) = to_create.assets
    asset_row = {
        "id": asset.id,
        "name": asset.name,
        "description": asset.description,
        "survey_related_record_id": to_create.id,
        "relative_path": asset.relative_path,
        "media_type": asset.media_type,
        "asset_type": [constants.AssetType.DATA],
        "links": [],
    }
    return record_row, asset_row


def _build_extent_update(discovered: _DiscoveredFile, current_fields: dict) -> dict:
    """Build the extent update of a tracked record from its file's metadata.

    The extracted bbox and temporal extent override `current_fields`, the temporal
    extent only when both of its ends were extracted, and the extracted summary
    replaces the one at the end of the current description. The merged
    fields are validated with `ValidSurveyRelatedRecord`.

    Returns a mapping with the record `id`, `bbox_wkt`, `description`,
    `temporal_extent_begin`, `temporal_extent_end`, `validation_result` and
    `is_valid`.
    """
    extracted_fields = _extracted_record_fields(
        discovered.metadata, discovered.bbox_wkt, current_fields["description"]
    )
    validation_result = _validate_record_fields(
        current_fields
        | extracted_fields
        | {
            "bbox_4326": WKBElement(
                shapely.to_wkb(shapely.from_wkt(discovered.bbox_wkt)), srid=4326
            )
        }
    )
    return {
        "id": current_fields["id"],
        "bbox_wkt": discovered.bbox_wkt,
        "description": extracted_fields["description"],
        "temporal_extent_begin": extracted_fields.get("temporal_extent_begin"),
        "temporal_extent_end": extracted_fields.get("temporal_extent_end"),
        "validation_result": validation_result,
        "is_valid": validation_result["is_valid"],
    }


def _validate_record_fields(record_fields: dict) -> dict:
    """Validate survey-related record fields with `ValidSurveyRelatedRecord`.

    Returns a mapping with `is_valid` and `errors`, the latter None when valid and
    otherwise a list of mappings with the `name`, `message` and `type_` of each
    error.
    """
    try:
        validation_schemas.ValidSurveyRelatedRecord.model_validate(record_fields)
    except pydantic.ValidationError as err:
        return {
            "is_valid": False,
            "errors": [
                {
                    "name": ".".join(str(i) for i in error["loc"]),
                    "message": error["msg"],
                    "type_": error["type"],
                }
                for error in err.errors()
            ],
        }
    return {"is_valid": True, "errors": None}


async def cancel_mission_discovery(
    *,
    request_id: identifiers.RequestId,
    mission_id: identifiers.SurveyMissionId,
    initiator: user_schemas.User,
    session: AsyncSession,
    event_dispatcher: dispatch.EventDispatcherProtocol,
) -> None:
    """Request the cancellation of a survey mission's running discovery.

    The mission's status is changed from under discovery to cancelling discovery.
    A mission whose discovery heartbeat is stale is recovered instead, as by
    `recover_stale_mission_discoveries`. Requesting it again while the mission is
    cancelling discovery only attempts that recovery, which frees a mission whose
    worker died before honouring the first request.
    """
    mission_name = None
    try:
        if (
            mission := await mission_queries.get_survey_mission(session, mission_id)
        ) is None:
            raise errors.SeisLabDataError(
                f"Survey mission with id {mission_id} does not exist."
            )
        mission_name = mission.name
        if not mission_permissions.can_discover_survey_mission(initiator, mission):
            raise errors.SeisLabDataError(
                "User is not allowed to cancel discovery on this survey mission."
            )
        if await recover_stale_mission_discoveries(
            request_id=request_id,
            initiator_id=initiator.id,
            session=session,
            event_dispatcher=event_dispatcher,
            mission_id=mission_id,
        ):
            return
        if mission.status == constants.SurveyMissionStatus.CANCELLING_DISCOVERY:
            raise errors.SeisLabDataError(
                f"Discovery is already being cancelled. If it is no longer running, "
                f"the survey mission can be recovered once its discovery has been "
                f"silent for {constants.DISCOVERY_STALE_AFTER_SECONDS // 60} minutes"
            )
        if not await mission_commands.compare_and_set_survey_mission_status(
            session,
            mission_id,
            constants.SurveyMissionStatus.UNDER_DISCOVERY,
            constants.SurveyMissionStatus.CANCELLING_DISCOVERY,
        ):
            raise errors.SeisLabDataError(
                "Cannot cancel discovery because the survey mission is not under "
                "discovery"
            )
    except errors.SeisLabDataError as err:
        await event_dispatcher(
            event_schemas.DiscoveryEvent(
                initiator=initiator.id,
                resource_type=constants.ResourceType.MISSION,
                resource_id=str(mission_id),
                resource_name=mission_name,
                request_id=request_id,
                modification=constants.DiscoveryStage.CANCELLED,
                succeeded=False,
                details=str(err),
            )
        )
        return
    await event_dispatcher(
        event_schemas.ResourceStatusChangedEvent(
            request_id=request_id,
            initiator=initiator.id,
            resource_type=constants.ResourceType.MISSION,
            resource_id=str(mission_id),
            resource_name=mission_name,
            succeeded=True,
            new_status=constants.SurveyMissionStatus.CANCELLING_DISCOVERY,
        )
    )


async def recover_stale_mission_discoveries(
    *,
    request_id: identifiers.RequestId,
    initiator_id: str,
    session: AsyncSession,
    event_dispatcher: dispatch.EventDispatcherProtocol,
    mission_id: identifiers.SurveyMissionId | None = None,
) -> list[identifiers.SurveyMissionId]:
    """Set to draft the survey missions whose discovery heartbeat is stale.

    The heartbeat is stale after `DISCOVERY_STALE_AFTER_SECONDS`. The recovery is
    restricted to a single mission if `mission_id` is given. A status change event
    and a failed discovery end event are dispatched for each recovered mission.

    Returns the ids of the recovered missions.
    """
    recovered = await mission_commands.recover_stale_survey_mission_discoveries(
        session,
        dt.timedelta(seconds=constants.DISCOVERY_STALE_AFTER_SECONDS),
        survey_mission_id=mission_id,
    )
    for recovered_mission_id, recovered_mission_name in recovered:
        logger.warning(
            f"Recovered survey mission {recovered_mission_id} from an abandoned "
            f"discovery"
        )
        await event_dispatcher(
            event_schemas.ResourceStatusChangedEvent(
                request_id=request_id,
                initiator=initiator_id,
                resource_type=constants.ResourceType.MISSION,
                resource_id=str(recovered_mission_id),
                resource_name=recovered_mission_name,
                succeeded=True,
                new_status=constants.SurveyMissionStatus.DRAFT,
            )
        )
        await event_dispatcher(
            event_schemas.DiscoveryEvent(
                initiator=initiator_id,
                resource_type=constants.ResourceType.MISSION,
                resource_id=str(recovered_mission_id),
                resource_name=recovered_mission_name,
                request_id=request_id,
                modification=constants.DiscoveryStage.ENDED,
                succeeded=False,
                details=(
                    "discovery was abandoned by its worker - the records created so "
                    "far are kept, run it again to resume"
                ),
            )
        )
    return [recovered_mission_id for recovered_mission_id, _ in recovered]


async def create_manual_survey_related_record(
    *,
    request_id: identifiers.RequestId,
    to_create: record_schemas.SurveyRelatedRecordCreate,
    initiator: user_schemas.User,
    session: AsyncSession,
    event_dispatcher: dispatch.EventDispatcherProtocol,
    settings: config.SeisLabDataSettings,
) -> models.SurveyRelatedRecord:
    """Create a record from user input, enriched with the metadata of its data files.

    The extents extracted from the first data asset path replace those of the
    payload, and the extracted summary is appended to the payload's description.
    Preview generation is enqueued after the record is created.
    """
    survey_mission = await mission_queries.get_survey_mission(
        session, to_create.survey_mission_id
    )
    # a failed check is left to the record operation, which emits the event
    if survey_mission is not None and (
        record_permissions.can_create_survey_related_record(initiator, survey_mission)
    ):
        fields = await _discover_record_fields(
            survey_mission,
            [asset.relative_path for asset in to_create.assets],
            to_create.description,
            settings,
        )
        # validated again, as the extracted bbox comes as WKT
        to_create = record_schemas.SurveyRelatedRecordCreate.model_validate(
            to_create.model_dump() | fields
        )
    # extraction can take a minute: the record operation's guards must see fresh state
    session.expire_all()
    created_record = await record_ops.create_survey_related_record(
        request_id=request_id,
        to_create=to_create,
        initiator=initiator,
        session=session,
        event_dispatcher=event_dispatcher,
    )
    # whether the record gets previews is decided by the derivation itself
    preview_tasks.generate_records_previews.send(
        raw_request_id=str(request_id),
        raw_survey_related_record_ids=[str(to_create.id)],
        raw_initiator=json.dumps(dataclasses.asdict(initiator)),
    )
    return created_record


async def update_manual_survey_related_record(
    *,
    request_id: identifiers.RequestId,
    survey_related_record_id: identifiers.SurveyRelatedRecordId,
    to_update: record_schemas.SurveyRelatedRecordUpdate,
    initiator: user_schemas.User,
    session: AsyncSession,
    event_dispatcher: dispatch.EventDispatcherProtocol,
    settings: config.SeisLabDataSettings,
) -> models.SurveyRelatedRecord:
    """Update a record from user input, re-extracting metadata if its data files change.

    Extraction runs only if the set of data asset paths differs from the stored one.
    The extents extracted from the first path then replace those of the payload, the
    extracted summary replaces the one at the end of the description, of the payload
    or else the stored one, and preview generation is enqueued.
    """
    survey_related_record = await record_queries.get_survey_related_record(
        session, survey_related_record_id
    )
    proposed_paths = [asset.relative_path for asset in to_update.assets]
    paths_changed = survey_related_record is not None and set(proposed_paths) != {
        asset.relative_path
        for asset in survey_related_record.assets
        if constants.AssetType.DATA in asset.asset_type
    }
    # a failed check is left to the record operation, which emits the event
    if paths_changed and record_permissions.can_update_survey_related_record(
        initiator, survey_related_record
    ):
        fields = await _discover_record_fields(
            survey_related_record.survey_mission,
            proposed_paths,
            (
                to_update.description
                if to_update.description is not None
                else survey_related_record.description
            ),
            settings,
        )
        # only the fields that were set, so that a partial update stays partial
        to_update = record_schemas.SurveyRelatedRecordUpdate.model_validate(
            to_update.model_dump(exclude_unset=True) | fields
        )
    # extraction can take a minute: the record operation's guards must see fresh state
    session.expire_all()
    updated_record = await record_ops.update_survey_related_record(
        request_id=request_id,
        survey_related_record_id=survey_related_record_id,
        to_update=to_update,
        initiator=initiator,
        session=session,
        event_dispatcher=event_dispatcher,
    )
    # previews only go stale with the data files
    if paths_changed:
        preview_tasks.generate_records_previews.send(
            raw_request_id=str(request_id),
            raw_survey_related_record_ids=[str(survey_related_record_id)],
            raw_initiator=json.dumps(dataclasses.asdict(initiator)),
        )
    return updated_record


async def _discover_record_fields(
    survey_mission: models.SurveyMission,
    data_asset_paths: list[str | None],
    description: str,
    settings: config.SeisLabDataSettings,
) -> dict:
    """Extract record fields from the first usable data asset path.

    Empty paths and paths with a `..` segment are not usable. The extracted summary
    is appended to `description` as by `_extracted_record_fields`.

    Returns the record fields produced by the extraction, empty if there is no usable
    path.
    """
    # a '..' segment would lead the extractor out of the archive
    usable_paths = [
        path for path in data_asset_paths if path and ".." not in path.split("/")
    ]
    if not usable_paths:
        return {}
    file_path = "/".join(
        (
            str(settings.readonly_archive_root_directory),
            survey_mission.relative_path,
            usable_paths[0],
        )
    )
    metadata, bbox_wkt = await _extract_file_metadata(
        file_path, survey_mission.implicit_crs
    )
    return _extracted_record_fields(metadata, bbox_wkt, description)


def _extracted_record_fields(
    metadata: extractor_schemas.ExtractionResult | None,
    bbox_wkt: str | None,
    description: str,
) -> dict:
    """Build the record fields produced by a metadata extraction.

    The description is `description` followed, on a new line, by the summary of the
    extracted metadata. A summary at the end of `description`, from an earlier
    extraction, is removed first. The summary is truncated so that the description
    fits `DESCRIPTION_MAX_LENGTH`, and left out if no room remains.

    Returns the bbox, the description and the temporal extent, each one only if the
    extraction produced it. The temporal extent requires both its begin and its end.

    The text of `description` is kept whole because it may have been written by a
    user, whereas the summary can be produced again from the file at any time.
    """
    fields = {}
    if bbox_wkt is not None:
        fields["bbox_4326"] = bbox_wkt
    if metadata is None:
        return fields
    summary = metadata.describe()
    kept_text = description
    for prefix in extractor_schemas.EXTRACTED_SUMMARY_PREFIXES:
        if kept_text.startswith(prefix):
            kept_text = ""
        elif (summary_start := kept_text.rfind(f"\n{prefix}")) != -1:
            kept_text = kept_text[:summary_start]
    kept_text = kept_text.rstrip()
    if not kept_text:
        fields["description"] = summary
    elif (room := constants.DESCRIPTION_MAX_LENGTH - len(kept_text) - 1) > 0:
        fields["description"] = f"{kept_text}\n{summary[:room]}"
    else:
        fields["description"] = kept_text
    if (
        metadata.temporal_extent_begin is not None
        and metadata.temporal_extent_end is not None
    ):
        fields["temporal_extent_begin"] = metadata.temporal_extent_begin
        fields["temporal_extent_end"] = metadata.temporal_extent_end
    return fields


async def _extract_file_metadata(
    file_path: str, implicit_crs: int, in_worker_process: bool = False
) -> tuple[extractor_schemas.ExtractionResult | None, str | None]:
    """Extract a file's metadata and its EPSG:4326 bbox as WKT.

    The extractor runs in a worker thread, or in a worker process if
    `in_worker_process` is set. The extractors' Python code holds the GIL, so
    concurrent extractions in threads share a single CPU core, while worker
    processes use one core each, at the cost of starting a process that loads GDAL
    on first use. Mission discovery, which extracts many files concurrently, sets
    it; the extraction of a single file for a record created or updated by hand
    does not, as it would gain nothing from another core and would wait for the
    process to start.

    Extraction errors, including a crashed worker process, are logged and result in
    None metadata. A bbox extracted in native coordinates without a CRS is
    reprojected using the projected CRS declared in the SEG-Y header, if exactly one
    is declared, or `implicit_crs` otherwise. The metadata is then updated with the
    applied CRS.

    Returns the metadata and the bbox WKT, each of which may be None.
    """
    metadata = None
    try:
        metadata = await (
            to_process.run_sync if in_worker_process else to_thread.run_sync
        )(extractor_dispatch.dispatch_extractor, file_path)
    except Exception as err:
        logger.warning("Metadata extraction failed for %s: %s", file_path, err)
        logger.debug("Extraction failure detail", exc_info=True)
    bbox_4326 = None
    header_crs = None
    applied_crs = implicit_crs
    applied_crs_name = None
    if metadata is not None:
        bbox_4326 = metadata.bbox_4326
        if (native_bbox := metadata.bbox_native_needing_crs) is not None:
            header_crs = _header_crs(metadata)
            if header_crs is not None:
                applied_crs = header_crs
                if header_crs != implicit_crs:
                    logger.info(
                        "Applying EPSG:%s from the header of %s instead of the "
                        "mission's EPSG:%s",
                        header_crs,
                        file_path,
                        implicit_crs,
                    )
            try:
                srs = osr.SpatialReference()
                srs.ImportFromEPSG(applied_crs)
                bbox_4326 = extractor_common.project_bbox_to_wgs84(native_bbox, srs)
                applied_crs_name = srs.GetName()
            except Exception as err:
                logger.warning(
                    "Could not apply CRS EPSG:%s to %s: %s",
                    applied_crs,
                    file_path,
                    err,
                )
    bbox_wkt = _bbox_4326_tuple_to_wkt(bbox_4326) if bbox_4326 is not None else None
    if applied_crs_name is not None and bbox_wkt is not None:
        metadata = metadata.model_copy(
            update={
                "epsg": applied_crs,
                "crs_name": applied_crs_name,
                "crs_from_mission": header_crs is None,
            }
        )
    return metadata, bbox_wkt


def _header_crs(metadata: extractor_schemas.ExtractionResult) -> int | None:
    """Return the projected CRS declared in a SEG-Y header.

    Returns None if the metadata is not SEG-Y metadata, or if its header declares
    either no projected CRS or more than one.
    """
    if not isinstance(metadata, extractor_schemas.SegyMetadata):
        return None
    projected_codes = {
        code for code in metadata.header_epsg_codes if _is_projected_crs(code)
    }
    return projected_codes.pop() if len(projected_codes) == 1 else None


def _is_projected_crs(epsg: int) -> bool:
    """Check whether an EPSG code identifies a projected CRS.

    Returns False for unknown codes.
    """
    spatial_reference = osr.SpatialReference()
    try:
        spatial_reference.ImportFromEPSG(epsg)
    # OverflowError: values beyond a C int never reach PROJ
    except (RuntimeError, OverflowError):
        return False
    return bool(spatial_reference.IsProjected())


def _bbox_4326_tuple_to_wkt(
    bbox: tuple[float, float, float, float],
) -> str | None:
    """Convert an EPSG:4326 bbox tuple into a WKT polygon.

    Returns None, and logs a warning, if a coordinate is non-finite or outside the
    longitude/latitude range. Otherwise the bbox is expanded by `_BBOX_BUFFER` on
    every side and snapped to a 1e-5 degree grid. Bboxes crossing the antimeridian
    are not supported.
    """
    minx, miny, maxx, maxy = bbox
    tolerance = 1e-6
    if not all(math.isfinite(value) for value in bbox) or not (
        -180 - tolerance <= minx <= maxx <= 180 + tolerance
        and -90 - tolerance <= miny <= maxy <= 90 + tolerance
    ):
        logger.warning(
            "Discarding extracted bbox with out-of-range or non-finite coordinates: %s",
            bbox,
        )
        return None
    # The envelope of the two corners is always valid (Point, LineString or
    # Polygon), unlike shapely.box on a degenerate bbox; buffering with square
    # caps and mitre joins keeps the result an axis-aligned rectangle.
    envelope = shapely.MultiPoint([(minx, miny), (maxx, maxy)]).envelope
    buffered = envelope.buffer(_BBOX_BUFFER, cap_style="square", join_style="mitre")
    # Snap to a 1e-5 degree grid (~1 m): finer precision is meaningless under
    # the ~10 m buffer, and the frontend's TerraDraw silently rejects
    # coordinates with more than 9 decimal places, dropping the map rectangle.
    return shapely.set_precision(buffered, 1e-5).wkt
