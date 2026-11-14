import logging
from collections.abc import Collection

import shapely
from sqlalchemy.orm import (
    aliased,
    selectinload,
)
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import (
    exists,
    func,
    or_,
    select,
)

from ...constants import (
    AssetType,
    SurveyRelatedRecordStatus,
)
from ...db import models
from ...schemas import (
    identifiers,
    filters as filter_schemas,
)
from .common import _get_total_num_records

logger = logging.getLogger(__name__)


def _apply_survey_related_record_filters(
    *,
    statement,
    survey_mission_ids: list[identifiers.SurveyMissionId] | None = None,
    project_id: identifiers.ProjectId | None = None,
    name_filter: str | None = None,
    spatial_intersect: shapely.Geometry | None = None,
    temporal_extent: filter_schemas.TemporalExtentFilterValue | None = None,
    asset_path_fragment_filter: str | None = None,
    asset_media_type_filter: str | None = None,
    record_ids: list[identifiers.SurveyRelatedRecordId] | None = None,
    dataset_category_id: identifiers.DatasetCategoryId | None = None,
    workflow_stage_id: identifiers.WorkflowStageId | None = None,
    only_data_assets: bool = True,
):
    """Apply the common survey-related record search filters to a statement.

    Shared by statement builders that select full records and by those
    that only need matching ids (e.g. for bulk-update operations).
    """
    if record_ids:
        statement = statement.where(models.SurveyRelatedRecord.id.in_(record_ids))
    if name_filter:
        statement = statement.where(
            models.SurveyRelatedRecord.name.ilike(f"%{name_filter}%")
        )
    if spatial_intersect is not None:
        statement = statement.where(
            or_(
                func.ST_Intersects(
                    models.SurveyRelatedRecord.bbox_4326,
                    func.ST_GeomFromText(spatial_intersect.wkt, 4326),
                ),
                models.SurveyRelatedRecord.bbox_4326.is_(None),
            )
        )
    if survey_mission_ids:
        statement = statement.where(
            models.SurveyRelatedRecord.survey_mission_id.in_(survey_mission_ids)
        )
    if project_id is not None:
        mission = aliased(models.SurveyMission)
        statement = statement.join(
            mission, models.SurveyRelatedRecord.survey_mission_id == mission.id
        ).where(mission.project_id == project_id)
    if temporal_extent is not None:
        if temporal_extent.begin is not None:
            statement = statement.where(
                or_(
                    models.SurveyRelatedRecord.temporal_extent_begin
                    >= temporal_extent.begin,
                    models.SurveyRelatedRecord.temporal_extent_begin.is_(None),
                )
            )
        if temporal_extent.end is not None:
            statement = statement.where(
                or_(
                    models.SurveyRelatedRecord.temporal_extent_end
                    <= temporal_extent.end,
                    models.SurveyRelatedRecord.temporal_extent_end.is_(None),
                )
            )
    if dataset_category_id is not None:
        statement = statement.where(
            models.SurveyRelatedRecord.dataset_category_id == dataset_category_id
        )
    if workflow_stage_id is not None:
        statement = statement.where(
            models.SurveyRelatedRecord.workflow_stage_id == workflow_stage_id
        )
    if asset_path_fragment_filter is not None:
        statement = statement.where(
            exists(
                select(models.RecordAsset)
                .where(
                    models.RecordAsset.survey_related_record_id
                    == models.SurveyRelatedRecord.id
                )
                .where(
                    models.RecordAsset.relative_path.ilike(
                        f"%{asset_path_fragment_filter}%"
                    )
                )
            )
        )
    if asset_media_type_filter is not None:
        asset_statement = (
            select(models.RecordAsset)
            .where(
                models.RecordAsset.survey_related_record_id
                == models.SurveyRelatedRecord.id
            )
            .where(models.RecordAsset.media_type.ilike(f"%{asset_media_type_filter}%"))
        )
        if only_data_assets:
            asset_statement = asset_statement.where(
                models.RecordAsset.asset_type.any(AssetType.DATA)
            )
        statement = statement.where(exists(asset_statement))
    return statement


def _build_survey_related_record_statement(
    survey_mission_ids: list[identifiers.SurveyMissionId] | None = None,
    project_id: identifiers.ProjectId | None = None,
    name_filter: str | None = None,
    spatial_intersect: shapely.Geometry | None = None,
    temporal_extent: filter_schemas.TemporalExtentFilterValue | None = None,
    asset_path_fragment_filter: str | None = None,
    asset_media_type_filter: str | None = None,
    record_ids: list[identifiers.SurveyRelatedRecordId] | None = None,
    dataset_category_id: identifiers.DatasetCategoryId | None = None,
    workflow_stage_id: identifiers.WorkflowStageId | None = None,
    only_data_assets: bool = True,
):
    statement = (
        select(models.SurveyRelatedRecord)
        .options(
            selectinload(models.SurveyRelatedRecord.survey_mission).selectinload(
                models.SurveyMission.project
            )
        )
        .options(selectinload(models.SurveyRelatedRecord.dataset_category))
        .options(selectinload(models.SurveyRelatedRecord.workflow_stage))
        # adding all assets too, since they will always be a small list. The
        # data column stays unloaded: it stores the preview image bytes, and
        # list pages never show images. Skipping the column must happen here at
        # query level, as sqlmodel ignores one declared as deferred on the model
        .options(
            selectinload(models.SurveyRelatedRecord.assets).defer(
                models.RecordAsset.data
            )
        )
        # also adding relationships with other records, only first order relationships are loaded, not the entire tree
        .options(selectinload(models.SurveyRelatedRecord.related_to_links))
        .options(selectinload(models.SurveyRelatedRecord.subject_links))
    )
    statement = _apply_survey_related_record_filters(
        statement=statement,
        survey_mission_ids=survey_mission_ids,
        project_id=project_id,
        name_filter=name_filter,
        spatial_intersect=spatial_intersect,
        temporal_extent=temporal_extent,
        asset_path_fragment_filter=asset_path_fragment_filter,
        asset_media_type_filter=asset_media_type_filter,
        record_ids=record_ids,
        dataset_category_id=dataset_category_id,
        workflow_stage_id=workflow_stage_id,
        only_data_assets=only_data_assets,
    )
    # name and id are tiebreakers - without them the order of items with the
    # same temporal extent is undefined and pages may overlap or skip items
    return statement.order_by(
        models.SurveyRelatedRecord.temporal_extent_end.desc().nullslast(),
        models.SurveyRelatedRecord.temporal_extent_begin.desc().nullslast(),
        models.SurveyRelatedRecord.name,
        models.SurveyRelatedRecord.id,
    )


def _build_survey_related_record_id_statement(
    survey_mission_id: identifiers.SurveyMissionId | None = None,
    name_filter: str | None = None,
    spatial_intersect: shapely.Polygon | None = None,
    temporal_extent: filter_schemas.TemporalExtentFilterValue | None = None,
    asset_path_fragment_filter: str | None = None,
    asset_media_type_filter: str | None = None,
    record_ids: list[identifiers.SurveyRelatedRecordId] | None = None,
    dataset_category_id: identifiers.DatasetCategoryId | None = None,
    workflow_stage_id: identifiers.WorkflowStageId | None = None,
    only_data_assets: bool = True,
):
    """Build a statement selecting only the ids of matching records.

    Intended for reuse as a subquery/executed-upfront id list (e.g. by
    bulk-update commands), where loading full records would be wasteful.
    """
    return _apply_survey_related_record_filters(
        statement=select(models.SurveyRelatedRecord.id),
        survey_mission_ids=(
            [survey_mission_id] if survey_mission_id is not None else None
        ),
        name_filter=name_filter,
        spatial_intersect=spatial_intersect,
        temporal_extent=temporal_extent,
        asset_path_fragment_filter=asset_path_fragment_filter,
        asset_media_type_filter=asset_media_type_filter,
        record_ids=record_ids,
        dataset_category_id=dataset_category_id,
        workflow_stage_id=workflow_stage_id,
        only_data_assets=only_data_assets,
    )


async def _exec_survey_related_record_list(
    session: AsyncSession,
    statement,
    limit: int,
    offset: int,
    include_total: bool,
) -> tuple[list[models.SurveyRelatedRecord], int | None]:
    items = (await session.exec(statement.offset(offset).limit(limit))).all()
    num_total = (
        await _get_total_num_records(session, statement) if include_total else None
    )
    return items, num_total


async def list_published_survey_related_records(
    session: AsyncSession,
    survey_mission_ids: list[identifiers.SurveyMissionId] | None = None,
    project_id: identifiers.ProjectId | None = None,
    page: int = 1,
    page_size: int = 20,
    include_total: bool = False,
    name_filter: str | None = None,
    spatial_intersect: shapely.Geometry | None = None,
    temporal_extent: filter_schemas.TemporalExtentFilterValue | None = None,
    asset_path_fragment_filter: str | None = None,
    asset_media_type_filter: str | None = None,
    record_ids: list[identifiers.SurveyRelatedRecordId] | None = None,
    dataset_category_id: identifiers.DatasetCategoryId | None = None,
    workflow_stage_id: identifiers.WorkflowStageId | None = None,
    only_data_assets: bool = True,
) -> tuple[list[models.SurveyRelatedRecord], int | None]:
    statement = _build_survey_related_record_statement(
        survey_mission_ids=survey_mission_ids,
        project_id=project_id,
        name_filter=name_filter,
        spatial_intersect=spatial_intersect,
        temporal_extent=temporal_extent,
        asset_path_fragment_filter=asset_path_fragment_filter,
        asset_media_type_filter=asset_media_type_filter,
        record_ids=record_ids,
        dataset_category_id=dataset_category_id,
        workflow_stage_id=workflow_stage_id,
        only_data_assets=only_data_assets,
    ).where(models.SurveyRelatedRecord.status == SurveyRelatedRecordStatus.PUBLISHED)
    limit = page_size
    offset = page_size * (page - 1)
    return await _exec_survey_related_record_list(
        session, statement, limit, offset, include_total
    )


def build_survey_related_record_id_statement(
    survey_mission_id: identifiers.SurveyMissionId | None = None,
    name_filter: str | None = None,
    spatial_intersect: shapely.Polygon | None = None,
    temporal_extent: filter_schemas.TemporalExtentFilterValue | None = None,
    asset_path_fragment_filter: str | None = None,
    asset_media_type_filter: str | None = None,
    record_ids: list[identifiers.SurveyRelatedRecordId] | None = None,
    excluded_record_ids: list[identifiers.SurveyRelatedRecordId] | None = None,
    dataset_category_id: identifiers.DatasetCategoryId | None = None,
    workflow_stage_id: identifiers.WorkflowStageId | None = None,
    only_data_assets: bool = True,
):
    """Build a statement selecting the ids of matching records, unrestricted.

    Intended for admins, who may bulk-update any matching record.
    """
    statement = _build_survey_related_record_id_statement(
        survey_mission_id,
        name_filter,
        spatial_intersect,
        temporal_extent,
        asset_path_fragment_filter,
        asset_media_type_filter,
        record_ids,
        dataset_category_id,
        workflow_stage_id,
        only_data_assets,
    )
    if excluded_record_ids:
        statement = statement.where(
            models.SurveyRelatedRecord.id.notin_(excluded_record_ids)
        )
    return statement


async def count_survey_related_records_matching(
    session: AsyncSession, ids_statement
) -> int:
    """Count how many records an id-only statement matches.

    Intended for the bulk-update id builders above, to show a user how many
    records a pending bulk update would affect without materializing ids.
    """
    return await _get_total_num_records(session, ids_statement)


async def list_survey_related_records(
    session: AsyncSession,
    survey_mission_ids: list[identifiers.SurveyMissionId] | None = None,
    project_id: identifiers.ProjectId | None = None,
    page: int = 1,
    page_size: int = 20,
    include_total: bool = False,
    name_filter: str | None = None,
    spatial_intersect: shapely.Geometry | None = None,
    temporal_extent: filter_schemas.TemporalExtentFilterValue | None = None,
    asset_path_fragment_filter: str | None = None,
    asset_media_type_filter: str | None = None,
    record_ids: list[identifiers.SurveyRelatedRecordId] | None = None,
    only_internal: bool = False,
    dataset_category_id: identifiers.DatasetCategoryId | None = None,
    workflow_stage_id: identifiers.WorkflowStageId | None = None,
    only_data_assets: bool = True,
) -> tuple[list[models.SurveyRelatedRecord], int | None]:
    """Return all records. Intended for admin use."""
    statement = _build_survey_related_record_statement(
        survey_mission_ids=survey_mission_ids,
        project_id=project_id,
        name_filter=name_filter,
        spatial_intersect=spatial_intersect,
        temporal_extent=temporal_extent,
        asset_path_fragment_filter=asset_path_fragment_filter,
        asset_media_type_filter=asset_media_type_filter,
        record_ids=record_ids,
        dataset_category_id=dataset_category_id,
        workflow_stage_id=workflow_stage_id,
        only_data_assets=only_data_assets,
    )
    if only_internal:
        statement = statement.where(
            models.SurveyRelatedRecord.status != SurveyRelatedRecordStatus.PUBLISHED
        )
    limit = page_size
    offset = page_size * (page - 1)
    return await _exec_survey_related_record_list(
        session, statement, limit, offset, include_total
    )


async def get_survey_related_record(
    session: AsyncSession,
    survey_related_record_id: identifiers.SurveyRelatedRecordId,
) -> models.SurveyRelatedRecord | None:
    statement = (
        select(models.SurveyRelatedRecord)
        .where(models.SurveyRelatedRecord.id == survey_related_record_id)
        .options(
            selectinload(models.SurveyRelatedRecord.survey_mission).selectinload(
                models.SurveyMission.project
            )
        )
        .options(selectinload(models.SurveyRelatedRecord.dataset_category))
        .options(selectinload(models.SurveyRelatedRecord.workflow_stage))
        # adding all assets too, since they will always be a small list
        .options(selectinload(models.SurveyRelatedRecord.assets))
        # also adding relationships with other records - only first order relationships are loaded, not the full tree
        .options(selectinload(models.SurveyRelatedRecord.related_to_links))
        .options(selectinload(models.SurveyRelatedRecord.subject_links))
    )
    return (await session.exec(statement)).first()


async def collect_survey_related_record_validation_fields(
    session: AsyncSession,
    survey_related_record_ids: Collection[identifiers.SurveyRelatedRecordId],
) -> dict[identifiers.SurveyRelatedRecordId, dict]:
    """Collect the non-spatial validation fields of survey-related records.

    Returns a mapping of record id to fields, keyed by the field names of
    `ValidSurveyRelatedRecord`. Ids without a record are omitted.
    """
    record = models.SurveyRelatedRecord
    statement = select(
        record.id,
        record.name,
        record.description,
        record.dataset_category_id,
        record.workflow_stage_id,
        record.status,
        record.links,
        record.temporal_extent_begin,
        record.temporal_extent_end,
    ).where(record.id.in_(survey_related_record_ids))
    return {
        identifiers.SurveyRelatedRecordId(row.id): row._asdict()
        for row in (await session.exec(statement)).all()
    }


async def get_survey_related_record_by_name(
    session: AsyncSession,
    survey_mission_id: identifiers.SurveyMissionId,
    name: str,
) -> models.SurveyRelatedRecord | None:
    statement = (
        select(models.SurveyRelatedRecord)
        .where(models.SurveyRelatedRecord.survey_mission_id == survey_mission_id)
        .where(models.SurveyRelatedRecord.name == name)
        .options(
            selectinload(models.SurveyRelatedRecord.survey_mission).selectinload(
                models.SurveyMission.project
            )
        )
        .options(selectinload(models.SurveyRelatedRecord.dataset_category))
        .options(selectinload(models.SurveyRelatedRecord.workflow_stage))
        # adding all assets too, since they will always be a small list
        .options(selectinload(models.SurveyRelatedRecord.assets))
        # also adding relationships with other records - only first order relationships are loaded, not the full tree
        .options(selectinload(models.SurveyRelatedRecord.related_to_links))
        .options(selectinload(models.SurveyRelatedRecord.subject_links))
    )
    return (await session.exec(statement)).first()


async def list_survey_related_record_related_to_records(
    session: AsyncSession,
    survey_related_record_id: identifiers.SurveyRelatedRecordId,
    limit: int = 20,
    offset: int = 0,
) -> list[tuple[dict, models.SurveyRelatedRecord]]:
    """Return records in which the input id is a subject of a relation.

    Returned records are those which are related to the input id.
    """
    statement = (
        select(
            models.SurveyRelatedRecordSelfLink.relation,
            models.SurveyRelatedRecord,
        )
        .join(
            models.SurveyRelatedRecordSelfLink,
            models.SurveyRelatedRecordSelfLink.related_to_id
            == models.SurveyRelatedRecord.id,
        )
        .where(
            models.SurveyRelatedRecordSelfLink.subject_id == survey_related_record_id
        )
        .options(
            selectinload(models.SurveyRelatedRecord.survey_mission).selectinload(
                models.SurveyMission.project
            )
        )
        .options(selectinload(models.SurveyRelatedRecord.dataset_category))
        .options(selectinload(models.SurveyRelatedRecord.workflow_stage))
    )
    return (await session.exec(statement.offset(offset).limit(limit))).all()


async def list_survey_related_record_subject_records(
    session: AsyncSession,
    survey_related_record_id: identifiers.SurveyRelatedRecordId,
    limit: int = 20,
    offset: int = 0,
) -> list[tuple[dict, models.SurveyRelatedRecord]]:
    """Return records which are subjects in a relation with the input id.

    Returned records are those which are subjects in a relation where the input id is involved
    """
    statement = (
        select(
            models.SurveyRelatedRecordSelfLink.relation,
            models.SurveyRelatedRecord,
        )
        .join(
            models.SurveyRelatedRecordSelfLink,
            models.SurveyRelatedRecordSelfLink.subject_id
            == models.SurveyRelatedRecord.id,
        )
        .where(
            models.SurveyRelatedRecordSelfLink.related_to_id == survey_related_record_id
        )
        .options(
            selectinload(models.SurveyRelatedRecord.survey_mission).selectinload(
                models.SurveyMission.project
            )
        )
        .options(selectinload(models.SurveyRelatedRecord.dataset_category))
        .options(selectinload(models.SurveyRelatedRecord.workflow_stage))
    )
    return (await session.exec(statement.offset(offset).limit(limit))).all()


async def count_survey_related_records_per_project(
    session: AsyncSession,
    project_ids: list[identifiers.ProjectId],
    published_only: bool,
) -> dict[identifiers.ProjectId, int]:
    """Count the survey-related records of each project.

    Projects without survey-related records are left out of the result.
    """
    statement = (
        select(
            models.SurveyMission.project_id, func.count(models.SurveyRelatedRecord.id)
        )
        .select_from(models.SurveyRelatedRecord)
        .join(
            models.SurveyMission,
            models.SurveyRelatedRecord.survey_mission_id == models.SurveyMission.id,
        )
        .where(models.SurveyMission.project_id.in_(project_ids))
        .group_by(models.SurveyMission.project_id)
    )
    if published_only:
        statement = statement.where(
            models.SurveyRelatedRecord.status == SurveyRelatedRecordStatus.PUBLISHED
        )
    return dict((await session.exec(statement)).all())


async def count_survey_related_records_per_survey_mission(
    session: AsyncSession,
    survey_mission_ids: list[identifiers.SurveyMissionId],
    published_only: bool,
) -> dict[identifiers.SurveyMissionId, int]:
    """Count the survey-related records of each survey mission.

    Survey missions without survey-related records are left out of the result.
    """
    statement = (
        select(
            models.SurveyRelatedRecord.survey_mission_id,
            func.count(models.SurveyRelatedRecord.id),
        )
        .where(models.SurveyRelatedRecord.survey_mission_id.in_(survey_mission_ids))
        .group_by(models.SurveyRelatedRecord.survey_mission_id)
    )
    if published_only:
        statement = statement.where(
            models.SurveyRelatedRecord.status == SurveyRelatedRecordStatus.PUBLISHED
        )
    return dict((await session.exec(statement)).all())


async def count_survey_related_records_per_lookup_value(
    session: AsyncSession,
    lookup_model: type[models.DatasetCategory] | type[models.WorkflowStage],
    published_only: bool,
    project_id: identifiers.ProjectId | None = None,
    survey_mission_id: identifiers.SurveyMissionId | None = None,
) -> list[tuple[models.DatasetCategory | models.WorkflowStage | None, int]]:
    """Count survey-related records per dataset category or per workflow stage.

    Records without a value are counted under `None`. The result is sorted by
    descending count.
    """
    statement = (
        select(lookup_model, func.count(models.SurveyRelatedRecord.id))
        .select_from(models.SurveyRelatedRecord)
        .outerjoin(lookup_model)
        .group_by(lookup_model.id)
        .order_by(
            func.count(models.SurveyRelatedRecord.id).desc(),
            lookup_model.name.nullslast(),
        )
    )
    if project_id is not None:
        statement = statement.join(
            models.SurveyMission,
            models.SurveyRelatedRecord.survey_mission_id == models.SurveyMission.id,
        ).where(models.SurveyMission.project_id == project_id)
    if survey_mission_id is not None:
        statement = statement.where(
            models.SurveyRelatedRecord.survey_mission_id == survey_mission_id
        )
    if published_only:
        statement = statement.where(
            models.SurveyRelatedRecord.status == SurveyRelatedRecordStatus.PUBLISHED
        )
    return (await session.exec(statement)).all()
