import datetime as dt
import logging
import re
import uuid
from collections.abc import AsyncIterator

import shapely
from anyio import to_thread
from geoalchemy2 import WKBElement
from sqlmodel.ext.asyncio.session import AsyncSession

from .. import (
    config,
    constants,
    dispatch,
    pathpatterns,
)
from ..db import models
from ..db.commands import (
    projects as project_commands,
    recordassets as asset_commands,
    surveymissions as mission_commands,
    surveyrelatedrecords as record_commands,
)
from ..db.queries import (
    discovery as discovery_queries,
    recordassets as asset_queries,
)
from ..schemas import (
    events as event_schemas,
    identifiers,
    surveyrelatedrecords as record_schemas,
    user as user_schemas,
)
from ..tasks.derivers import (
    bbox_thumbnail,
    dispatch as deriver_dispatch,
)

logger = logging.getLogger(__name__)


async def iter_survey_mission_records_missing_previews(
    session: AsyncSession,
    survey_mission_id: identifiers.SurveyMissionId,
    created_before: dt.datetime | None = None,
    page_size: int = constants.PREVIEW_BATCH_SIZE,
) -> AsyncIterator[list[identifiers.SurveyRelatedRecordId]]:
    """Yield the ids of a survey mission's records that are missing previews, by page.

    These are the records without derived assets that have at least one data asset
    eligible for a preview, as defined in `generate_record_previews`, restricted to
    those created before `created_before` when given. Each page holds the eligible
    records among `page_size` records without derived assets, so it may be shorter
    or empty.
    """
    # no permission check, unlike user-facing operations: generation is
    # system-initiated, authorized when the discovery that enqueued it ran
    preview_patterns = await _collect_preview_patterns(session)
    after_record_id = None
    while paths_by_record := (
        await asset_queries.collect_survey_mission_data_asset_paths_without_derived_assets(
            session,
            survey_mission_id,
            created_before=created_before,
            after_record_id=after_record_id,
            limit=page_size,
        )
    ):
        yield [
            record_id
            for record_id, relative_paths in paths_by_record.items()
            if any(
                next(
                    (
                        generates_previews
                        for pattern, generates_previews in preview_patterns
                        if pattern.matches(relative_path)
                    ),
                    False,
                )
                for relative_path in relative_paths
            )
        ]
        after_record_id = next(reversed(paths_by_record))


async def _collect_preview_patterns(
    session: AsyncSession,
) -> list[tuple[pathpatterns.PathPattern, bool]]:
    """Compile the path patterns of the asset discovery configurations, in name order.

    Returns each compiled pattern along with its configuration's `generate_previews`
    flag. Configurations with an invalid path pattern are logged and skipped.
    """
    preview_patterns = []
    for (
        configuration
    ) in await discovery_queries.collect_all_asset_discovery_configurations(session):
        try:
            preview_patterns.append(
                (
                    pathpatterns.compile_path_pattern(
                        configuration.relative_path_regexp
                    ),
                    configuration.generate_previews,
                )
            )
        except re.error as err:
            logger.warning(
                f"Asset discovery configuration {configuration.name!r} has an "
                f"invalid path pattern: {err}"
            )
    return preview_patterns


async def generate_record_previews(
    *,
    request_id: identifiers.RequestId,
    survey_related_record: models.SurveyRelatedRecord,
    initiator: user_schemas.User,
    session: AsyncSession,
    event_dispatcher: dispatch.EventDispatcherProtocol,
    settings: config.SeisLabDataSettings,
    skip_if_derived: bool = False,
) -> None:
    """Generate previews of a record's data assets and store them as derived assets.

    A data asset is eligible if the first asset discovery configuration, in name
    order, whose path pattern matches its path has `generate_previews` enabled.
    Records whose status is neither draft nor published are skipped, as are
    records that already have derived assets if `skip_if_derived` is set.
    Generation is best-effort: an asset whose preview cannot be rendered is logged
    and skipped.

    The generated previews replace the record's existing derived assets. If no
    preview is generated, or if the record's status changes during rendering, the
    existing derived assets are kept. A derivation event is dispatched once the
    previews are stored.
    """
    record_id = identifiers.SurveyRelatedRecordId(survey_related_record.id)
    if (original_status := survey_related_record.status) not in (
        constants.SurveyRelatedRecordStatus.DRAFT,
        constants.SurveyRelatedRecordStatus.PUBLISHED,
    ):
        logger.warning(
            f"Survey-related record {record_id} is {original_status} - not "
            f"generating its previews..."
        )
        return
    if skip_if_derived and any(
        constants.AssetType.DATA not in asset.asset_type
        for asset in survey_related_record.assets
    ):
        logger.debug(
            f"Survey-related record {record_id} already has derived assets - not "
            f"generating its previews..."
        )
        return
    preview_patterns = await _collect_preview_patterns(session)
    mission_root_path = "/".join(
        (
            str(settings.readonly_archive_root_directory),
            survey_related_record.survey_mission.relative_path,
        )
    )
    derived = []
    for asset in survey_related_record.assets:
        if constants.AssetType.DATA not in asset.asset_type:
            continue
        if asset.relative_path is None:
            continue
        # paths typed by hand are not checked, and a '..' segment leaves the archive
        if ".." in asset.relative_path.split("/"):
            logger.debug(
                f"Asset path {asset.relative_path!r} points outside the archive - "
                f"not generating its preview..."
            )
            continue
        if not next(
            (
                generates_previews
                for pattern, generates_previews in preview_patterns
                if pattern.matches(asset.relative_path)
            ),
            False,
        ):
            logger.debug(
                f"Asset path {asset.relative_path!r} does not match a discovery "
                f"configuration that generates previews - not generating its "
                f"preview..."
            )
            continue
        asset_path = "/".join((mission_root_path, asset.relative_path))
        if not deriver_dispatch.can_derive(asset_path):
            continue
        try:
            preview = await to_thread.run_sync(
                deriver_dispatch.dispatch_deriver,
                asset_path,
                survey_related_record.survey_mission.implicit_crs,
            )
        except Exception as err:
            logger.warning(f"Preview generation failed for {asset_path!r}: {err}")
            continue
        if preview is None:  # the file went away between the two checks
            continue
        # asset names may use the full 100-char cap; leave room for the labels
        source_name = asset.name[:80]
        derived.append(
            record_schemas.DerivedRecordAssetCreate(
                id=identifiers.RecordAssetId(uuid.uuid4()),
                name=f"{source_name} preview",
                description="",
                media_type="image/webp",
                # a single image serves both the list thumbnail and the map overlay
                asset_type=[
                    constants.AssetType.THUMBNAIL,
                    constants.AssetType.PREVIEW,
                ],
                data=preview.image,
            )
        )
    if not derived:
        logger.debug(
            f"No preview could be generated for record {record_id} - "
            f"leaving its existing assets alone..."
        )
        return
    # the record is only held under derivation while its derived assets are
    # replaced, never during the render, so a worker killed mid-render cannot
    # leave it stranded. The flip expects the status the record was fetched
    # with: one that moved meanwhile means the record was touched and the
    # previews may be stale
    if not await record_commands.compare_and_set_survey_related_record_status(
        session,
        record_id,
        original_status,
        constants.SurveyRelatedRecordStatus.UNDER_DERIVATION,
    ):
        logger.warning(
            f"Survey-related record {record_id} changed status while its "
            f"previews were being rendered - not storing them..."
        )
        return
    try:
        await asset_commands.replace_derived_record_assets(
            session, survey_related_record, derived
        )
    finally:
        # conditional as well, so as not to undo a status which something else,
        # such as the bulk publication of the mission, has set meanwhile
        await record_commands.compare_and_set_survey_related_record_status(
            session,
            record_id,
            constants.SurveyRelatedRecordStatus.UNDER_DERIVATION,
            original_status,
        )
    await event_dispatcher(
        event_schemas.DerivationEvent(
            initiator=initiator.id,
            request_id=request_id,
            resource_type=constants.ResourceType.RECORD,
            resource_id=str(record_id),
            parent_resource_id=str(survey_related_record.survey_mission_id),
        )
    )


async def generate_project_thumbnail(
    *,
    request_id: identifiers.RequestId,
    project: models.Project,
    initiator: user_schemas.User,
    session: AsyncSession,
    event_dispatcher: dispatch.EventDispatcherProtocol,
    settings: config.SeisLabDataSettings,
) -> None:
    """Render the project's bbox over the base map and store it as its thumbnail."""
    project_id = identifiers.ProjectId(project.id)
    if project.bbox_4326 is None:
        # removed after the task was enqueued, the removal cleared the thumbnail too
        logger.warning(
            f"Project {project_id} no longer has a bbox - not generating its "
            f"thumbnail..."
        )
        return
    thumbnail = await _render_bbox_thumbnail(project.bbox_4326, settings)
    if not await project_commands.set_project_thumbnail(session, project_id, thumbnail):
        logger.warning(
            f"Project {project_id} no longer exists - not storing its thumbnail..."
        )
        return
    await event_dispatcher(
        event_schemas.ResourceModificationEvent(
            initiator=initiator.id,
            request_id=request_id,
            resource_type=constants.ResourceType.PROJECT,
            resource_id=str(project_id),
            resource_name=project.name,
            modification=constants.ResourceModification.UPDATED,
            succeeded=True,
        )
    )


async def generate_survey_mission_thumbnail(
    *,
    request_id: identifiers.RequestId,
    survey_mission: models.SurveyMission,
    initiator: user_schemas.User,
    session: AsyncSession,
    event_dispatcher: dispatch.EventDispatcherProtocol,
    settings: config.SeisLabDataSettings,
) -> None:
    """Render the mission's bbox over the base map and store it as its thumbnail."""
    survey_mission_id = identifiers.SurveyMissionId(survey_mission.id)
    if survey_mission.bbox_4326 is None:
        # removed after the task was enqueued, the removal cleared the thumbnail too
        logger.warning(
            f"Survey mission {survey_mission_id} no longer has a bbox - not "
            f"generating its thumbnail..."
        )
        return
    thumbnail = await _render_bbox_thumbnail(survey_mission.bbox_4326, settings)
    if not await mission_commands.set_survey_mission_thumbnail(
        session, survey_mission_id, thumbnail
    ):
        logger.warning(
            f"Survey mission {survey_mission_id} no longer exists - not storing "
            f"its thumbnail..."
        )
        return
    await event_dispatcher(
        event_schemas.ResourceModificationEvent(
            initiator=initiator.id,
            request_id=request_id,
            resource_type=constants.ResourceType.MISSION,
            resource_id=str(survey_mission_id),
            resource_name=survey_mission.name,
            modification=constants.ResourceModification.UPDATED,
            succeeded=True,
        )
    )


async def _render_bbox_thumbnail(
    bbox_4326: WKBElement, settings: config.SeisLabDataSettings
) -> bytes:
    if (tile_url_template := settings.thumbnail_base_tile_layer_url) is None:
        raise RuntimeError(
            "No base tile layer to render thumbnails with, set "
            "SEIS_LAB_DATA__THUMBNAIL_BASE_TILE_LAYER_URL"
        )
    return await to_thread.run_sync(
        bbox_thumbnail.render_bbox_thumbnail,
        bbox_thumbnail.build_tms_basemap_xml(
            tile_url_template, settings.webmap_base_tile_layer_max_zoom
        ),
        shapely.from_wkb(bbox_4326.data).bounds,
        bbox_thumbnail.BboxStyle(
            fill_color=settings.webmap_default_polygon_fill_color,
            fill_opacity=settings.webmap_default_polygon_fill_opacity,
            outline_color=settings.webmap_default_polygon_outline_color,
            outline_opacity=settings.webmap_default_polygon_outline_opacity,
            outline_width=settings.webmap_default_polygon_outline_width,
        ),
    )
