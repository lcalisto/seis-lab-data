import logging
from typing import cast

from sqlalchemy import (
    Boolean,
    Date,
    String,
    case,
    column,
    func,
    insert,
    literal,
    update,
    values,
)
from sqlalchemy.dialects.postgresql import (
    JSONB,
    UUID as PG_UUID,
)
from sqlalchemy.exc import IntegrityError
from sqlmodel.ext.asyncio.session import AsyncSession

from ... import errors
from ...constants import SurveyRelatedRecordStatus
from ...schemas import (
    identifiers,
    discovery as discovery_schemas,
)
from .. import models
from ..queries import discovery as discovery_queries

logger = logging.getLogger(__name__)


async def create_asset_discovery_configuration(
    session: AsyncSession,
    to_create: discovery_schemas.AssetDiscoveryConfigurationCreate,
) -> models.AssetDiscoveryConfiguration:
    asset_discovery_conf = models.AssetDiscoveryConfiguration.model_validate(
        to_create.model_dump(
            exclude_none=True,
        ),
        from_attributes=False,
    )
    session.add(asset_discovery_conf)
    try:
        await session.commit()
    except IntegrityError as err:
        await session.rollback()
        raise errors.SeisLabDataError(str(err)) from err
    await session.refresh(asset_discovery_conf)
    return cast(
        models.AssetDiscoveryConfiguration,
        await discovery_queries.get_asset_discovery_configuration(
            session, to_create.id
        ),
    )


async def delete_asset_discovery_configuration(
    session: AsyncSession,
    asset_discovery_configuration_id: identifiers.AssetDiscoveryConfId,
) -> None:
    if asset_discovery_conf := (
        await discovery_queries.get_asset_discovery_configuration(
            session, asset_discovery_configuration_id
        )
    ):
        await session.delete(asset_discovery_conf)
        await session.commit()
    else:
        raise errors.SeisLabDataError(
            f"asset_discovery_configuration with id {asset_discovery_configuration_id} does not exist."
        )


async def update_asset_discovery_configuration(
    session: AsyncSession,
    asset_discovery_configuration: models.AssetDiscoveryConfiguration,
    to_update: discovery_schemas.AssetDiscoveryConfigurationUpdate,
) -> models.AssetDiscoveryConfiguration:
    for key, value in to_update.model_dump(exclude_unset=True).items():
        setattr(asset_discovery_configuration, key, value)
    session.add(asset_discovery_configuration)
    await session.commit()
    await session.refresh(asset_discovery_configuration)
    return cast(
        models.AssetDiscoveryConfiguration,
        await discovery_queries.get_asset_discovery_configuration(
            session, identifiers.AssetDiscoveryConfId(asset_discovery_configuration.id)
        ),
    )


async def write_discovered_survey_related_records(
    session: AsyncSession,
    records: list[dict],
    assets: list[dict],
    extent_updates: list[dict],
) -> int:
    """Insert records with their assets and update the extent of existing records.

    `records` and `assets` are rows of column values, inserted with SQLAlchemy Core
    multi-row statements instead of ORM instances: the ORM's per-object identity
    tracking, attribute instrumentation and flush ordering cost far more CPU time
    than the SQL itself, which becomes the bottleneck when writing thousands of
    rows. Each item of `extent_updates` maps a record `id` to its new
    `bbox_wkt`, `description`, `temporal_extent_begin`, `temporal_extent_end`,
    `validation_result` and `is_valid`; a temporal extent end that is None keeps
    the stored value. An extent update applies only to a record with a null bbox
    and a `DRAFT` or `PUBLISHED` status, and sets an invalid record to `DRAFT`.
    All writes share a single transaction.

    Returns the number of records whose extent was updated.
    """
    if records:
        await session.execute(insert(models.SurveyRelatedRecord.__table__), records)
        await session.execute(insert(models.RecordAsset.__table__), assets)
    updated = 0
    if extent_updates:
        record = models.SurveyRelatedRecord
        updated_values = values(
            column("id", PG_UUID(as_uuid=True)),
            column("bbox_wkt", String),
            column("description", String),
            column("temporal_extent_begin", Date),
            column("temporal_extent_end", Date),
            column("validation_result", JSONB),
            column("is_valid", Boolean),
            name="extent_update",
        ).data(
            [
                (
                    extent_update["id"],
                    extent_update["bbox_wkt"],
                    extent_update["description"],
                    extent_update["temporal_extent_begin"],
                    extent_update["temporal_extent_end"],
                    extent_update["validation_result"],
                    extent_update["is_valid"],
                )
                for extent_update in extent_updates
            ]
        )
        result = await session.execute(
            update(record)
            .where(record.id == updated_values.c.id)
            # keep a bbox set since the record was looked up, e.g. by a user
            .where(record.bbox_4326.is_(None))
            .where(
                record.status.in_(
                    (
                        SurveyRelatedRecordStatus.DRAFT,
                        SurveyRelatedRecordStatus.PUBLISHED,
                    )
                )
            )
            .values(
                bbox_4326=func.ST_GeomFromText(updated_values.c.bbox_wkt, 4326),
                description=updated_values.c.description,
                temporal_extent_begin=func.coalesce(
                    updated_values.c.temporal_extent_begin,
                    record.temporal_extent_begin,
                ),
                temporal_extent_end=func.coalesce(
                    updated_values.c.temporal_extent_end, record.temporal_extent_end
                ),
                validation_result=updated_values.c.validation_result,
                status=case(
                    (updated_values.c.is_valid, record.status),
                    # cast to the column's enum type, which stores the enum names
                    else_=literal(
                        SurveyRelatedRecordStatus.DRAFT, type_=record.status.type
                    ),
                ),
            )
            .execution_options(synchronize_session=False)
        )
        updated = result.rowcount
    await session.commit()
    return updated
