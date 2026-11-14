import uuid

import pytest

from seis_lab_data import (
    constants,
    errors,
)
from seis_lab_data.db.commands import (
    recordassets as asset_commands,
    surveyrelatedrecords as record_commands,
)
from seis_lab_data.operations import surveyrelatedrecords as record_ops
from seis_lab_data.schemas import (
    identifiers,
    surveyrelatedrecords as record_schemas,
    events as event_schemas,
)
from seis_lab_data.schemas.user import User
from seis_lab_data.schemas.identifiers import (
    UserId,
    RequestId,
)


class _EventCollector:
    def __init__(self):
        self.events: list[event_schemas.SeisLabDataEvent] = []

    async def __call__(self, event: event_schemas.SeisLabDataEvent) -> None:
        self.events.append(event)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_published_record_gives_anonymous_visitors_its_derived_asset_data(
    db,
    db_session_maker,
    sample_survey_related_records,
):
    # this is what the record asset data endpoint relies on in order to serve
    # previews of published records to visitors who are not logged in
    record = sample_survey_related_records[0]
    preview_id = identifiers.RecordAssetId(uuid.uuid4())
    async with db_session_maker() as session:
        await asset_commands.replace_derived_record_assets(
            session,
            record,
            [
                record_schemas.DerivedRecordAssetCreate(
                    id=preview_id,
                    name="A preview",
                    media_type="image/webp",
                    asset_type=[
                        constants.AssetType.THUMBNAIL,
                        constants.AssetType.PREVIEW,
                    ],
                    data=b"not a webp",
                )
            ],
        )
        # sample records are created as drafts
        await record_commands.set_survey_related_record_status(
            session,
            identifiers.SurveyRelatedRecordId(record.id),
            constants.SurveyRelatedRecordStatus.PUBLISHED,
        )
        found, _related_to, _subject_for = await record_ops.get_survey_related_record(
            identifiers.SurveyRelatedRecordId(record.id), None, session
        )
    assert [a.data for a in found.assets if a.id == preview_id] == [b"not a webp"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_draft_record_denies_anonymous_visitors_its_derived_asset_data(
    db,
    db_session_maker,
    sample_survey_related_records,
):
    # the record asset data endpoint turns this error into a 404, so that a
    # draft record's previews are not even known to exist
    record = sample_survey_related_records[0]
    async with db_session_maker() as session:
        with pytest.raises(errors.UserNotAllowedError):
            await record_ops.get_survey_related_record(
                identifiers.SurveyRelatedRecordId(record.id), None, session
            )


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
            name_filter="First",
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
        w for w in bootstrap_workflow_stages if w.name == "quality control data"
    ][0]
    to_update = record_schemas.SurveyRelatedRecordBulkUpdate(
        description="Should not apply"
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
    # both sample records are in "bathymetry", so this narrows only via name_filter
    matching_category = [
        c for c in bootstrap_dataset_categories if c.name == "bathymetry"
    ][0]
    to_update = record_schemas.SurveyRelatedRecordBulkUpdate(description="Should apply")
    dispatcher = _EventCollector()
    async with db_session_maker() as session:
        result = await record_ops.bulk_update_survey_related_records(
            request_id=RequestId(uuid.uuid4()),
            to_update=to_update,
            initiator=admin_user,
            session=session,
            event_dispatcher=dispatcher,
            name_filter="First",
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
        description="Should not apply"
    )
    dispatcher = _EventCollector()
    async with db_session_maker() as session:
        result = await record_ops.bulk_update_survey_related_records(
            request_id=RequestId(uuid.uuid4()),
            to_update=to_update,
            initiator=admin_user,
            session=session,
            event_dispatcher=dispatcher,
            name_filter="First",
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
        description="Bulk-updated via operation"
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


@pytest.mark.integration
@pytest.mark.asyncio
async def test_update_refuses_record_under_derivation(
    db,
    db_session_maker,
    sample_survey_related_records,
    admin_user,
):
    first_record, _ = sample_survey_related_records
    record_id = identifiers.SurveyRelatedRecordId(first_record.id)
    async with db_session_maker() as session:
        await record_commands.set_survey_related_record_status(
            session, record_id, constants.SurveyRelatedRecordStatus.UNDER_DERIVATION
        )
    dispatcher = _EventCollector()
    async with db_session_maker() as session:
        with pytest.raises(errors.SeisLabDataError):
            await record_ops.update_survey_related_record(
                request_id=RequestId(uuid.uuid4()),
                survey_related_record_id=record_id,
                to_update=record_schemas.SurveyRelatedRecordUpdate(
                    description="Should not apply"
                ),
                initiator=admin_user,
                session=session,
                event_dispatcher=dispatcher,
            )
    assert len(dispatcher.events) == 1
    assert dispatcher.events[0].succeeded is False
