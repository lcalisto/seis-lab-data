import datetime as dt
from collections.abc import Collection

from sqlalchemy.orm import selectinload
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import (
    func,
    select,
)

from ...constants import AssetType
from ...db import models
from ...schemas import identifiers
from .common import _get_total_num_records

_SELECT_IN_LOAD_OPTIONS = (
    selectinload(models.RecordAsset.survey_related_record)
    .selectinload(models.SurveyRelatedRecord.survey_mission)
    .selectinload(models.SurveyMission.project)
)


async def collect_all_record_assets(
    session: AsyncSession,
    survey_related_record_id: identifiers.SurveyRelatedRecordId,
) -> list[models.RecordAsset]:
    statement = (
        select(models.RecordAsset)
        .where(models.RecordAsset.survey_related_record_id == survey_related_record_id)
        .options(_SELECT_IN_LOAD_OPTIONS)
    )
    return (await session.exec(statement)).all()


async def list_record_assets(
    session: AsyncSession,
    survey_related_record_id: identifiers.SurveyRelatedRecordId,
    limit: int = 20,
    offset: int = 0,
    include_total: bool = False,
) -> tuple[list[models.RecordAsset], int | None]:
    statement = (
        select(models.RecordAsset)
        .where(models.RecordAsset.survey_related_record_id == survey_related_record_id)
        .options(_SELECT_IN_LOAD_OPTIONS)
    )
    items = (await session.exec(statement.offset(offset).limit(limit))).all()
    num_total = (
        await _get_total_num_records(session, statement) if include_total else None
    )
    return items, num_total


async def get_record_asset(
    session: AsyncSession,
    record_asset_id: identifiers.RecordAssetId,
) -> models.RecordAsset | None:
    statement = (
        select(models.RecordAsset)
        .where(models.RecordAsset.id == record_asset_id)
        .options(_SELECT_IN_LOAD_OPTIONS)
    )
    return (await session.exec(statement)).first()


async def get_record_asset_by_name(
    session: AsyncSession,
    survey_related_record_id: identifiers.SurveyRelatedRecordId,
    name: str,
) -> models.RecordAsset | None:
    statement = (
        select(models.RecordAsset)
        .where(models.RecordAsset.name == name)
        .where(models.RecordAsset.survey_related_record_id == survey_related_record_id)
        .options(_SELECT_IN_LOAD_OPTIONS)
    )
    return (await session.exec(statement)).first()


async def collect_survey_mission_tracked_file_paths(
    session: AsyncSession,
    survey_mission_id: identifiers.SurveyMissionId,
    relative_paths: Collection[str],
) -> dict[str, tuple[identifiers.SurveyRelatedRecordId, bool]]:
    """Collect the assets of a survey mission located at any of `relative_paths`.

    Returns a mapping of each matching path to the id of its asset's record and a
    flag set when that record has a bbox.
    """
    statement = (
        select(
            models.RecordAsset.relative_path,
            models.SurveyRelatedRecord.id,
            models.SurveyRelatedRecord.bbox_4326.is_not(None),
        )
        .join(
            models.SurveyRelatedRecord,
            models.RecordAsset.survey_related_record_id
            == models.SurveyRelatedRecord.id,
        )
        .where(models.SurveyRelatedRecord.survey_mission_id == survey_mission_id)
        .where(models.RecordAsset.relative_path.in_(relative_paths))
    )
    return {
        relative_path: (identifiers.SurveyRelatedRecordId(record_id), has_bbox)
        for relative_path, record_id, has_bbox in (await session.exec(statement)).all()
    }


async def collect_survey_mission_data_asset_paths_without_derived_assets(
    session: AsyncSession,
    survey_mission_id: identifiers.SurveyMissionId,
    created_before: dt.datetime | None = None,
    after_record_id: identifiers.SurveyRelatedRecordId | None = None,
    limit: int | None = None,
) -> dict[identifiers.SurveyRelatedRecordId, list[str]]:
    """Collect the data asset paths of a survey mission's records without derived assets.

    Records are collected in id order, at most `limit` of them. When given,
    `created_before` restricts them to the records created earlier, and
    `after_record_id` to the records with a greater id.

    Returns a mapping of each record id to the relative paths of its data assets.
    Records without data asset paths are left out.
    """
    records_with_derived_assets = select(
        models.RecordAsset.survey_related_record_id
    ).where(~models.RecordAsset.asset_type.any(AssetType.DATA))
    statement = (
        select(
            models.RecordAsset.survey_related_record_id,
            func.array_agg(models.RecordAsset.relative_path),
        )
        .join(
            models.SurveyRelatedRecord,
            models.RecordAsset.survey_related_record_id
            == models.SurveyRelatedRecord.id,
        )
        .where(models.SurveyRelatedRecord.survey_mission_id == survey_mission_id)
        .where(models.RecordAsset.asset_type.any(AssetType.DATA))
        .where(models.RecordAsset.relative_path.is_not(None))
        .where(
            models.RecordAsset.survey_related_record_id.not_in(
                records_with_derived_assets
            )
        )
        .group_by(models.RecordAsset.survey_related_record_id)
        .order_by(models.RecordAsset.survey_related_record_id)
        .limit(limit)
    )
    if created_before is not None:
        statement = statement.where(
            models.SurveyRelatedRecord.created_at < created_before
        )
    if after_record_id is not None:
        statement = statement.where(
            models.RecordAsset.survey_related_record_id > after_record_id
        )
    return {
        identifiers.SurveyRelatedRecordId(record_id): list(relative_paths)
        for record_id, relative_paths in (await session.exec(statement)).all()
    }


async def get_record_asset_by_file_path(
    session: AsyncSession,
    file_path: str,
    survey_mission_id: identifiers.SurveyMissionId,
) -> models.RecordAsset | None:
    # Scoped per mission: the same relative path may legitimately exist in
    # several missions, each deserving its own record.
    statement = (
        select(models.RecordAsset)
        .join(
            models.SurveyRelatedRecord,
            models.RecordAsset.survey_related_record_id
            == models.SurveyRelatedRecord.id,
        )
        .where(models.RecordAsset.relative_path == file_path)
        .where(models.SurveyRelatedRecord.survey_mission_id == survey_mission_id)
        .options(_SELECT_IN_LOAD_OPTIONS)
    )
    return (await session.exec(statement)).first()


def _get_media_type_list_statement(
    name_filter: str | None = None,
    only_data_assets: bool = True,
):
    statement = (
        select(models.RecordAsset.media_type)
        .distinct()
        .order_by(models.RecordAsset.media_type)
    )
    if only_data_assets:
        statement = statement.where(models.RecordAsset.asset_type.any(AssetType.DATA))
    if name_filter:
        statement = statement.where(
            models.RecordAsset.media_type.ilike(f"%{name_filter}%")
        )
    return statement


async def list_media_types(
    session: AsyncSession,
    page: int = 1,
    page_size: int = 20,
    name_filter: str | None = None,
    only_data_assets: bool = True,
) -> list[str]:
    statement = _get_media_type_list_statement(name_filter, only_data_assets)
    limit = page_size
    offset = page_size * (page - 1)
    statement = statement.offset(offset).limit(limit)
    if name_filter:
        statement = statement.where(
            models.RecordAsset.media_type.ilike(f"%{name_filter}%")
        )
    return (await session.exec(statement)).all()


async def count_media_types(
    session: AsyncSession,
    name_filter: str | None = None,
    only_data_assets: bool = True,
) -> int:
    statement = _get_media_type_list_statement(name_filter, only_data_assets)
    return (await session.exec(select(func.count()).select_from(statement))).first()
