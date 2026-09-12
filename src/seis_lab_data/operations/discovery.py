import dataclasses
import json
import logging
import math
import re
import uuid
from collections.abc import AsyncIterator
from typing import AsyncGenerator

import shapely
from anyio import Path, to_thread
from osgeo import osr
from sqlmodel.ext.asyncio.session import AsyncSession

from .. import (
    config,
    constants,
    errors,
)
from ..db import models
from ..db.queries import (
    discovery as discovery_queries,
    surveymissions as mission_queries,
    recordassets as asset_queries,
)
from ..db.commands import discovery as discovery_commands
from ..permissions import (
    discovery as discovery_permissions,
    surveymissions as mission_permissions,
)
from ..schemas import (
    common,
    events as event_schemas,
    discovery as discovery_schemas,
    identifiers,
    surveyrelatedrecords as record_schemas,
    user as user_schemas,
)
from .. import dispatch
from ..tasks import previews as preview_tasks
from ..tasks.derivers import dispatch as deriver_dispatch
from ..tasks.extractors import (
    common as extractor_common,
    dispatch as extractor_dispatch,
)

from . import (
    previews as preview_ops,
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
            modification=constants.ResourceModification.CREATED,
            succeeded=True,
            resource_id=str(asset_discovery_configuration.id),
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
    try:
        if (
            await discovery_queries.get_asset_discovery_configuration(
                session, asset_discovery_configuration_id
            )
        ) is None:
            raise errors.SeisLabDataError(
                f"asset discovery configuration with id {asset_discovery_configuration_id} does not exist."
            )
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
    try:
        if (
            mission := await mission_queries.get_survey_mission(session, mission_id)
        ) is None:
            raise errors.SeisLabDataError(
                f"Survey mission with id {mission_id} does not exist."
            )
        if not mission_permissions.can_discover_survey_mission(user, mission):
            raise errors.SeisLabDataError(
                "User is not allowed to run discovery on this survey mission."
            )
    except errors.SeisLabDataError as err:
        await event_dispatcher(
            event_schemas.DiscoveryEvent(
                initiator=user.id,
                resource_type=constants.ResourceType.MISSION,
                resource_id=str(mission_id),
                request_id=request_id,
                modification=constants.DiscoveryStage.ENDED,
                succeeded=False,
                details=str(err),
            )
        )
        return

    logger.debug(f"Discovering contents of mission {mission.name['en']!r}...")
    asset_discovery_configs = (
        await discovery_queries.collect_all_asset_discovery_configurations(session)
    )
    await mission_ops.change_survey_mission_status(
        request_id=request_id,
        target_status=constants.SurveyMissionStatus.UNDER_DISCOVERY,
        survey_mission_id=mission_id,
        initiator=user,
        session=session,
        event_dispatcher=event_dispatcher,
    )
    await event_dispatcher(
        event_schemas.DiscoveryEvent(
            initiator=user.id,
            resource_type=constants.ResourceType.MISSION,
            resource_id=str(mission_id),
            request_id=request_id,
            modification=constants.DiscoveryStage.STARTED,
            succeeded=True,
        )
    )
    try:
        preview_folders = await preview_ops.load_preview_folders(settings)
        await _discover_mission_records(
            request_id=request_id,
            mission=mission,
            session=session,
            event_dispatcher=event_dispatcher,
            settings=settings,
            user=user,
            asset_discovery_configs=asset_discovery_configs,
            preview_folders=preview_folders,
        )
    except FileNotFoundError as err:
        await event_dispatcher(
            event_schemas.DiscoveryEvent(
                initiator=user.id,
                resource_type=constants.ResourceType.MISSION,
                resource_id=str(mission_id),
                request_id=request_id,
                modification=constants.DiscoveryStage.ENDED,
                succeeded=False,
                details=str(err),
            )
        )
    else:
        await event_dispatcher(
            event_schemas.DiscoveryEvent(
                initiator=user.id,
                resource_type=constants.ResourceType.MISSION,
                resource_id=str(mission_id),
                request_id=request_id,
                modification=constants.DiscoveryStage.ENDED,
                succeeded=True,
            )
        )
    finally:
        await mission_ops.change_survey_mission_status(
            request_id=request_id,
            target_status=constants.SurveyMissionStatus.DRAFT,
            survey_mission_id=mission_id,
            initiator=user,
            session=session,
            event_dispatcher=event_dispatcher,
        )


async def _discover_mission_records(
    *,
    request_id: identifiers.RequestId,
    mission: models.SurveyMission,
    session: AsyncSession,
    event_dispatcher: dispatch.EventDispatcherProtocol,
    settings: config.SeisLabDataSettings,
    user: user_schemas.User,
    asset_discovery_configs: list[models.AssetDiscoveryConfiguration],
    preview_folders: frozenset[str],
) -> None:
    mission_root_path = Path(
        "/".join(
            (
                str(settings.readonly_archive_root_directory),
                mission.relative_path,
            )
        )
    )
    logger.debug(f"{mission_root_path=}")
    for asset_discovery_conf in asset_discovery_configs:
        logger.debug(f"Searching for asset {asset_discovery_conf=}...")
        full_path_regexp = "/".join(
            (
                str(mission_root_path),
                asset_discovery_conf.relative_path_regexp,
            )
        )
        logger.debug(f"{full_path_regexp=}")
        async for found_path in _discover_asset_paths(full_path_regexp):
            # each found_path is to become a record with a single asset
            relative_file_path = str(found_path.relative_to(mission_root_path))
            if (
                existing_asset := await asset_queries.get_record_asset_by_file_path(
                    session,
                    relative_file_path,
                    identifiers.SurveyMissionId(mission.id),
                )
            ) is None:
                # best-effort metadata extraction: a failure must never abort
                # discovery or record creation
                metadata = None
                try:
                    metadata = await to_thread.run_sync(
                        extractor_dispatch.dispatch_extractor, str(found_path)
                    )
                except Exception as err:
                    logger.warning(
                        "Metadata extraction failed for %s: %s", found_path, err
                    )
                    logger.debug("Extraction failure detail", exc_info=True)
                bbox_4326 = None
                if metadata is not None:
                    bbox_4326 = metadata.bbox_4326
                    if (native_bbox := metadata.bbox_native_needing_crs) is not None:
                        try:
                            implicit_srs = osr.SpatialReference()
                            implicit_srs.ImportFromEPSG(mission.implicit_crs)
                            bbox_4326 = extractor_common.project_bbox_to_wgs84(
                                native_bbox, implicit_srs
                            )
                        except Exception as err:
                            logger.warning(
                                "Could not apply implicit CRS %s to %s: %s",
                                mission.implicit_crs,
                                found_path,
                                err,
                            )
                bbox_wkt = (
                    _bbox_4326_tuple_to_wkt(bbox_4326)
                    if bbox_4326 is not None
                    else None
                )
                # create a new record and a new asset
                record_id = identifiers.SurveyRelatedRecordId(uuid.uuid4())
                await record_ops.create_survey_related_record(
                    request_id=request_id,
                    to_create=record_schemas.SurveyRelatedRecordCreate(
                        id=record_id,
                        owner_id=identifiers.UserId(user.id),
                        survey_mission_id=identifiers.SurveyMissionId(mission.id),
                        name=common.LocalizableDraftName(en=found_path.name),
                        description=common.LocalizableDraftDescription(
                            en=metadata.describe("en") if metadata is not None else "",
                            pt=metadata.describe("pt") if metadata is not None else "",
                        ),
                        dataset_category_id=identifiers.DatasetCategoryId(
                            asset_discovery_conf.dataset_category_id
                        ),
                        workflow_stage_id=identifiers.WorkflowStageId(
                            asset_discovery_conf.workflow_stage_id
                        ),
                        bbox_4326=bbox_wkt,
                        temporal_extent_begin=(
                            metadata.temporal_extent_begin if metadata else None
                        ),
                        temporal_extent_end=(
                            metadata.temporal_extent_end if metadata else None
                        ),
                        assets=[
                            record_schemas.DataRecordAssetCreate(
                                id=identifiers.RecordAssetId(uuid.uuid4()),
                                name=common.LocalizableDraftName(en=found_path.stem),
                                description=common.LocalizableDraftDescription(en=""),
                                relative_path=relative_file_path,
                            )
                        ],
                    ),
                    initiator=user,
                    session=session,
                    event_dispatcher=event_dispatcher,
                )
                if deriver_dispatch.is_previewable(
                    str(found_path), relative_file_path, preview_folders
                ):
                    preview_tasks.generate_record_previews.send(
                        raw_request_id=str(request_id),
                        raw_survey_related_record_id=str(record_id),
                        raw_initiator=json.dumps(dataclasses.asdict(user)),
                    )
            else:
                logger.debug(
                    f"file {found_path!r} is already tracked in the DB - ignoring..."
                )
                # re-running discovery is the recovery path for records whose
                # previews are missing, so only those get enqueued again
                if deriver_dispatch.is_previewable(
                    str(found_path), relative_file_path, preview_folders
                ):
                    existing_record_id = identifiers.SurveyRelatedRecordId(
                        existing_asset.survey_related_record_id
                    )
                    has_derived_assets = any(
                        constants.AssetType.DATA not in asset.asset_type
                        for asset in await asset_queries.collect_all_record_assets(
                            session, existing_record_id
                        )
                    )
                    if not has_derived_assets:
                        preview_tasks.generate_record_previews.send(
                            raw_request_id=str(request_id),
                            raw_survey_related_record_id=str(existing_record_id),
                            raw_initiator=json.dumps(dataclasses.asdict(user)),
                        )


def _bbox_4326_tuple_to_wkt(
    bbox: tuple[float, float, float, float],
) -> str | None:
    """Turn an extracted lon/lat bbox into a WKT polygon for the record.

    Garbage coordinates (non-finite or out of lon/lat range, e.g. from a bogus
    CRS transform) are discarded with a warning. The surviving bbox is expanded
    by _BBOX_BUFFER on every side. Antimeridian-crossing bboxes are not handled
    (Portuguese waters).
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


async def _discover_asset_paths(
    full_path_regexp: str,
) -> AsyncGenerator[Path, None]:
    """Discover assets for a particular asset discovery configuration.

    Discovery assumptions:

    - One record only holds one asset. Although generally we support multiple assets per record,
      for discovery the only supported use case is a 1:1 mapping between record and asset.
    """
    root, pattern = split_pattern_path(full_path_regexp)
    if not pattern:
        if await root.is_file():
            yield root
        return

    pattern_parts = Path(pattern).parts
    async for matched_path in walk_pattern(root, pattern_parts):
        yield matched_path


async def walk_pattern(
    current: Path, remaining: tuple[str, ...]
) -> AsyncIterator[Path]:
    if not remaining:
        if await current.is_file():
            yield current
        return

    head, *tail = remaining
    tail = tuple(tail)
    regex = re.compile(f"^{head}$")
    try:
        async for entry in current.iterdir():
            if await entry.is_dir():
                async for matched in walk_pattern(entry, remaining):
                    yield matched
            if regex.match(entry.name):
                if tail:
                    async for matched in walk_pattern(entry, tail):
                        yield matched
                else:
                    if await entry.is_file():
                        yield entry
    except (PermissionError, NotADirectoryError):
        return


def split_pattern_path(regexp_path: str) -> tuple[Path, str]:
    """Split a regexp path into a Path component and a regexp pattern"""
    _re_meta = re.compile(r"[.*+?^${}()\[\]|\\]")
    parts = Path(regexp_path).parts
    plain_parts = []
    for i, part in enumerate(parts):
        if _re_meta.search(part):
            pattern = str(Path(*parts[i:])) if parts[i:] else ""
            return Path(*plain_parts) if plain_parts else Path("."), pattern
        plain_parts.append(part)
    return Path(regexp_path), ""
