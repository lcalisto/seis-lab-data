import uuid

import pytest

from seis_lab_data.operations import surveyrelatedrecords as record_ops
from seis_lab_data.schemas import (
    identifiers,
    surveyrelatedrecords as record_schemas,
    common as common_schemas,
    events as event_schemas,
)
from seis_lab_data.schemas.user import User
from seis_lab_data.schemas.identifiers import UserId, RequestId


class _EventCollector:
    def __init__(self):
        self.events: list[event_schemas.SeisLabDataEvent] = []

    async def __call__(self, event: event_schemas.SeisLabDataEvent) -> None:
        self.events.append(event)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bulk_update_denies_user_without_editor_role(
    db,
    db_session_maker,
    sample_survey_related_records,
):
    plain_user = User(
        id=UserId("plain-user"), username="plain", email="plain@tests.dev", roles=[]
    )
    dispatcher = _EventCollector()
    async with db_session_maker() as session:
        result = await record_ops.bulk_update_survey_related_records(
            request_id=RequestId(uuid.uuid4()),
            to_update=record_schemas.SurveyRelatedRecordBulkUpdate(),
            initiator=plain_user,
            session=session,
            event_dispatcher=dispatcher,
            en_name_filter="First",
        )
    assert result is None
    assert len(dispatcher.events) == 1
    assert dispatcher.events[0].succeeded is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bulk_update_workflow_stage_filter_excludes_non_matching_records(
    db,
    db_session_maker,
    sample_survey_related_records,
    bootstrap_workflow_stages,
    admin_user,
):
    # sample records are all in the "raw data" workflow stage, not this one
    non_matching_stage = [
        w for w in bootstrap_workflow_stages if w.name["en"] == "quality control data"
    ][0]
    to_update = record_schemas.SurveyRelatedRecordBulkUpdate(
        description=common_schemas.LocalizableDraftDescription(en="Should not apply")
    )
    dispatcher = _EventCollector()
    async with db_session_maker() as session:
        result = await record_ops.bulk_update_survey_related_records(
            request_id=RequestId(uuid.uuid4()),
            to_update=to_update,
            initiator=admin_user,
            session=session,
            event_dispatcher=dispatcher,
            workflow_stage_id=identifiers.WorkflowStageId(non_matching_stage.id),
        )
    assert result == 0
    assert dispatcher.events[0].succeeded is True
    assert dispatcher.events[0].affected_count == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bulk_update_dataset_category_filter_combines_with_name_filter(
    db,
    db_session_maker,
    sample_survey_related_records,
    bootstrap_dataset_categories,
    admin_user,
):
    # both sample records are in "bathymetry", so this narrows only via en_name_filter
    matching_category = [
        c for c in bootstrap_dataset_categories if c.name["en"] == "bathymetry"
    ][0]
    to_update = record_schemas.SurveyRelatedRecordBulkUpdate(
        description=common_schemas.LocalizableDraftDescription(en="Should apply")
    )
    dispatcher = _EventCollector()
    async with db_session_maker() as session:
        result = await record_ops.bulk_update_survey_related_records(
            request_id=RequestId(uuid.uuid4()),
            to_update=to_update,
            initiator=admin_user,
            session=session,
            event_dispatcher=dispatcher,
            en_name_filter="First",
            dataset_category_id=identifiers.DatasetCategoryId(matching_category.id),
        )
    assert result == 1
    assert dispatcher.events[0].succeeded is True
    assert dispatcher.events[0].affected_count == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bulk_update_asset_media_type_filter_excludes_non_matching_records(
    db,
    db_session_maker,
    sample_survey_related_records,
    admin_user,
):
    # sample record assets declare application/octet-stream as their media type,
    # so this filter matches none of them
    to_update = record_schemas.SurveyRelatedRecordBulkUpdate(
        description=common_schemas.LocalizableDraftDescription(en="Should not apply")
    )
    dispatcher = _EventCollector()
    async with db_session_maker() as session:
        result = await record_ops.bulk_update_survey_related_records(
            request_id=RequestId(uuid.uuid4()),
            to_update=to_update,
            initiator=admin_user,
            session=session,
            event_dispatcher=dispatcher,
            en_name_filter="First",
            asset_media_type_filter="video/mp4",
        )
    assert result == 0
    assert dispatcher.events[0].succeeded is True
    assert dispatcher.events[0].affected_count == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bulk_update_manually_selected_records_via_operation(
    db,
    db_session_maker,
    sample_survey_related_records,
    admin_user,
):
    first_record, second_record = sample_survey_related_records
    to_update = record_schemas.SurveyRelatedRecordBulkUpdate(
        description=common_schemas.LocalizableDraftDescription(
            en="Bulk-updated via operation"
        )
    )
    dispatcher = _EventCollector()
    async with db_session_maker() as session:
        result = await record_ops.bulk_update_survey_related_records(
            request_id=RequestId(uuid.uuid4()),
            to_update=to_update,
            initiator=admin_user,
            session=session,
            event_dispatcher=dispatcher,
            selected=[identifiers.SurveyRelatedRecordId(second_record.id)],
        )
    assert result == 1
    assert dispatcher.events[0].succeeded is True
    assert dispatcher.events[0].affected_count == 1
