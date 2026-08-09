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


async def get_record_asset_by_english_name(
    session: AsyncSession,
    survey_related_record_id: identifiers.SurveyRelatedRecordId,
    english_name: str,
) -> models.RecordAsset | None:
    statement = (
        select(models.RecordAsset)
        .where(models.RecordAsset.name["en"].astext == english_name)
        .where(models.RecordAsset.survey_related_record_id == survey_related_record_id)
        .options(_SELECT_IN_LOAD_OPTIONS)
    )
    return (await session.exec(statement)).first()


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
