import json
import logging
import uuid

import dramatiq

from .. import config
from ..operations import previews as preview_ops
from ..schemas import (
    identifiers,
    user as user_schemas,
)
from . import decorators
from .stub import sld_stub_broker

dramatiq.set_broker(sld_stub_broker)
logger = logging.getLogger(__name__)


# Previews get a queue of their own so that rendering a large raster cannot
# delay the interactive tasks, and a time limit of their own because the
# dramatiq default of 10 minutes might not be enough for big files.
# They are never retried, discovery re-enqueues whatever is still missing.
@dramatiq.actor(queue_name="previews", max_retries=0, time_limit=1_800_000)
@decorators.sld_settings
async def generate_record_previews(
    raw_request_id: str,
    raw_survey_related_record_id: str,
    raw_initiator: str,
    *,
    settings: config.SeisLabDataSettings,
) -> None:
    async with settings.get_db_session_maker()() as session:
        await preview_ops.generate_record_previews(
            request_id=identifiers.RequestId(uuid.UUID(raw_request_id)),
            survey_related_record_id=identifiers.SurveyRelatedRecordId(
                uuid.UUID(raw_survey_related_record_id)
            ),
            initiator=user_schemas.User(**json.loads(raw_initiator)),
            session=session,
            event_dispatcher=settings.get_event_dispatcher(),
            settings=settings,
        )
