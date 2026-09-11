import logging

from sqlalchemy import (
    delete,
    text,
)
from sqlmodel.ext.asyncio.session import AsyncSession

from ... import errors
from ...constants import AssetType
from ...schemas import (
    identifiers,
    surveyrelatedrecords as record_schemas,
)
from .. import models
from ..queries import recordassets as asset_queries

logger = logging.getLogger(__name__)


async def delete_record_asset(
    session: AsyncSession,
    record_asset_id: identifiers.RecordAssetId,
) -> None:
    if record_asset := (await asset_queries.get_record_asset(session, record_asset_id)):
        await session.delete(record_asset)
        await session.commit()
    else:
        raise errors.SeisLabDataError(
            f"Record asset with id {record_asset!r} does not exist."
        )


async def replace_derived_record_assets(
    session: AsyncSession,
    survey_related_record: models.SurveyRelatedRecord,
    derived: list[record_schemas.DerivedRecordAssetCreate],
) -> None:
    """Replace a record's derived assets with the given ones.

    Existing derived assets are deleted and the given ones stored in their
    place; the record's data assets are never touched.

    Two discovery runs may ask for previews of the same record at the same time,
    and interleaved deletes and inserts would then commit duplicates, so the
    replacement is serialized per record with an advisory lock and done in a
    single transaction.
    """
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:record_id))"),
        {"record_id": str(survey_related_record.id)},
    )
    await session.execute(
        delete(models.RecordAsset)
        .where(models.RecordAsset.survey_related_record_id == survey_related_record.id)
        .where(~models.RecordAsset.asset_type.any(AssetType.DATA))
    )
    for asset_to_create in derived:
        session.add(
            models.RecordAsset(
                **asset_to_create.model_dump(),
                survey_related_record_id=survey_related_record.id,
            )
        )
    await session.commit()
