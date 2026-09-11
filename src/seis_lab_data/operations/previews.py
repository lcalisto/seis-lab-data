import json
import logging
import uuid

import shapely
from anyio import Path, to_thread
from sqlmodel.ext.asyncio.session import AsyncSession

from .. import (
    config,
    constants,
)
from ..db.commands import recordassets as asset_commands
from ..db.queries import surveyrelatedrecords as record_queries
from ..schemas import (
    common,
    events as event_schemas,
    identifiers,
    surveyrelatedrecords as record_schemas,
    user as user_schemas,
)
from .. import dispatch
from ..tasks.derivers import dispatch as deriver_dispatch

logger = logging.getLogger(__name__)


async def load_preview_folders(
    settings: config.SeisLabDataSettings,
) -> frozenset[str]:
    """Read the family/stage folder prefixes which gate preview generation."""
    contents = await Path(settings.preview_folders_path).read_text()
    return frozenset(json.loads(contents)["folders"])


async def generate_record_previews(
    *,
    request_id: identifiers.RequestId,
    survey_related_record_id: identifiers.SurveyRelatedRecordId,
    initiator: user_schemas.User,
    session: AsyncSession,
    event_dispatcher: dispatch.EventDispatcherProtocol,
    settings: config.SeisLabDataSettings,
) -> None:
    """Generate previews of a record's data assets, stored as derived assets.

    A new generation replaces the record's existing derived assets. Previews
    are best-effort: a file which cannot be rendered is logged and skipped,
    both because the archive holds corrupt files and because no record's state
    may depend on them.
    """
    # no permission check, unlike user-facing operations: generation is
    # system-initiated, authorized when the discovery that enqueued it ran
    if (
        record := await record_queries.get_survey_related_record(
            session, survey_related_record_id
        )
    ) is None:
        logger.debug(
            f"Survey-related record {survey_related_record_id} no longer exists - "
            f"not generating previews..."
        )
        return
    folder_prefixes = await load_preview_folders(settings)
    mission_root_path = "/".join(
        (
            str(settings.readonly_archive_root_directory),
            record.survey_mission.relative_path,
        )
    )
    derived = []
    for asset in record.assets:
        if constants.AssetType.DATA not in asset.asset_type:
            continue
        if asset.relative_path is None:
            continue
        asset_path = "/".join((mission_root_path, asset.relative_path))
        if not deriver_dispatch.is_previewable(
            asset_path, asset.relative_path, folder_prefixes
        ):
            continue
        try:
            preview = await to_thread.run_sync(
                deriver_dispatch.dispatch_deriver, asset_path
            )
        except Exception as err:
            logger.warning(f"Preview generation failed for {asset_path!r}: {err}")
            continue
        if preview is None:  # the file went away between the two checks
            continue
        # asset names may use the full 100-char cap; leave room for the labels
        source_name = asset.name["en"][:80]
        derived.append(
            record_schemas.DerivedRecordAssetCreate(
                id=identifiers.RecordAssetId(uuid.uuid4()),
                name=common.LocalizableDraftName(
                    en=f"{source_name} preview",
                    pt=f"Pré-visualização de {source_name}",
                ),
                description=common.LocalizableDraftDescription(en="", pt=""),
                media_type="image/webp",
                # a single image serves both the list thumbnail and the map overlay
                asset_type=[
                    constants.AssetType.THUMBNAIL,
                    constants.AssetType.PREVIEW,
                ],
                data=preview.image,
                geog=shapely.box(*preview.bounds_4326).wkt,
            )
        )
    if not derived:
        logger.debug(
            f"No preview could be generated for record {survey_related_record_id} - "
            f"leaving its existing assets alone..."
        )
        return
    await asset_commands.replace_derived_record_assets(session, record, derived)
    await event_dispatcher(
        event_schemas.ResourceModificationEvent(
            initiator=initiator.id,
            request_id=request_id,
            resource_type=constants.ResourceType.RECORD,
            resource_id=str(survey_related_record_id),
            modification=constants.ResourceModification.UPDATED,
            succeeded=True,
        )
    )
