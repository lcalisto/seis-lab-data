"""Integration tests for mission discovery with metadata extraction.

These run against the test database and a fake archive built under tmp_path.
GDAL is required to build the synthetic fixture files; the module self-skips
where it is unavailable.
"""

import datetime as dt
import logging
import math
import uuid

import pytest
import pytest_asyncio
import shapely
import sqlmodel
from geoalchemy2.shape import to_shape

pytest.importorskip("osgeo")

from osgeo import gdal, osr  # noqa: E402

from seis_lab_data import constants  # noqa: E402
from seis_lab_data.db import models  # noqa: E402
from seis_lab_data.db.commands import (  # noqa: E402
    discovery as discovery_commands,
    projects as project_commands,
    surveymissions as mission_commands,
)
from seis_lab_data.operations import discovery as discovery_ops  # noqa: E402
from seis_lab_data.schemas import (  # noqa: E402
    common as common_schemas,
    discovery as discovery_schemas,
    events as event_schemas,
    identifiers,
    projects as project_schemas,
    surveymissions as mission_schemas,
)
from seis_lab_data.tasks.extractors import schemas as extractor_schemas  # noqa: E402

gdal.UseExceptions()

_MISSION_RELATIVE_PATH = "surveys/test-mission"
# ETRS89/PT-TM06 metres, around the projection origin in central Portugal
_NATIVE_BBOX_TM06 = (0.0, 1900.0, 100.0, 2000.0)


class _EventCollector:
    def __init__(self):
        self.events: list[event_schemas.SeisLabDataEvent] = []

    async def __call__(self, event: event_schemas.SeisLabDataEvent) -> None:
        self.events.append(event)


def _write_geotiff(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(3763)
    ds = gdal.GetDriverByName("GTiff").Create(str(path), 10, 10, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((0.0, 10.0, 0.0, 2000.0, 0.0, -10.0))
    ds.SetProjection(srs.ExportToWkt())
    ds.GetRasterBand(1).SetNoDataValue(-9999.0)
    ds.GetRasterBand(1).Fill(1.0)
    ds = None


async def _create_mission(
    session, admin_user, project_id, mission_relative_path, name_suffix=""
):
    mission = await mission_commands.create_survey_mission(
        session,
        mission_schemas.SurveyMissionCreate(
            id=identifiers.SurveyMissionId(uuid.uuid4()),
            owner_id=identifiers.UserId(admin_user.id),
            project_id=project_id,
            name=common_schemas.LocalizableDraftName(
                en=f"Discovery test mission{name_suffix}"
            ),
            description=common_schemas.LocalizableDraftDescription(en=""),
            relative_path=mission_relative_path,
        ),
    )
    return mission


@pytest_asyncio.fixture
async def discovery_env(
    tmp_path,
    settings,
    db,
    db_session_maker,
    admin_user,
    bootstrap_dataset_categories,
    bootstrap_workflow_stages,
):
    """A fake archive plus one project, mission and discovery configuration."""
    settings.readonly_archive_root_directory = tmp_path
    async with db_session_maker() as session:
        project = await project_commands.create_project(
            session,
            project_schemas.ProjectCreate(
                id=identifiers.ProjectId(uuid.uuid4()),
                owner_id=identifiers.UserId(admin_user.id),
                name=common_schemas.LocalizableDraftName(en="Discovery test project"),
                root_path="",
            ),
        )
        mission = await _create_mission(
            session,
            admin_user,
            identifiers.ProjectId(project.id),
            _MISSION_RELATIVE_PATH,
        )
        configuration = await discovery_commands.create_asset_discovery_configuration(
            session,
            discovery_schemas.AssetDiscoveryConfigurationCreate(
                id=identifiers.AssetDiscoveryConfId(uuid.uuid4()),
                name="test tif",
                relative_path_regexp=r"s01/.*\.tif",
                media_type="image/tiff",
                workflow_stage_id=identifiers.WorkflowStageId(
                    bootstrap_workflow_stages[0].id
                ),
                dataset_category_id=identifiers.DatasetCategoryId(
                    bootstrap_dataset_categories[0].id
                ),
            ),
        )
    return {
        "archive_root": tmp_path,
        "settings": settings,
        "project": project,
        "mission": mission,
        "configuration": configuration,
    }


async def _run_discovery(db_session_maker, mission_id, settings, admin_user):
    collector = _EventCollector()
    async with db_session_maker() as session:
        await discovery_ops.run_mission_discovery(
            request_id=identifiers.RequestId(uuid.uuid4()),
            mission_id=identifiers.SurveyMissionId(mission_id),
            session=session,
            event_dispatcher=collector,
            settings=settings,
            user=admin_user,
        )
    return collector


async def _get_mission_records(db_session_maker, mission_id):
    async with db_session_maker() as session:
        statement = sqlmodel.select(models.SurveyRelatedRecord).where(
            models.SurveyRelatedRecord.survey_mission_id == mission_id
        )
        return (await session.exec(statement)).all()


def _ended_events(collector):
    return [
        e
        for e in collector.events
        if isinstance(e, event_schemas.DiscoveryEvent)
        and e.modification == constants.DiscoveryStage.ENDED
    ]


def test_bbox_tuple_to_wkt_buffers_every_side():
    wkt = discovery_ops._bbox_4326_tuple_to_wkt((10.0, 40.0, 10.5, 40.5))
    assert shapely.from_wkt(wkt).bounds == pytest.approx(
        (9.9999, 39.9999, 10.5001, 40.5001)
    )


def test_bbox_tuple_to_wkt_pads_degenerate_point():
    wkt = discovery_ops._bbox_4326_tuple_to_wkt((-8.5, 39.0, -8.5, 39.0))
    polygon = shapely.from_wkt(wkt)
    assert polygon.is_valid
    assert polygon.area > 0
    assert polygon.bounds == pytest.approx((-8.5001, 38.9999, -8.4999, 39.0001))


def test_bbox_tuple_to_wkt_discards_out_of_range(caplog):
    with caplog.at_level(logging.WARNING, logger=discovery_ops.logger.name):
        result = discovery_ops._bbox_4326_tuple_to_wkt((200.0, 40.0, 201.0, 41.0))
    assert result is None
    assert any("Discarding extracted bbox" in r.message for r in caplog.records)


def test_bbox_tuple_to_wkt_discards_non_finite():
    assert discovery_ops._bbox_4326_tuple_to_wkt((math.nan, 40.0, 10.0, 41.0)) is None
    assert discovery_ops._bbox_4326_tuple_to_wkt((10.0, 40.0, math.inf, 41.0)) is None


def test_bbox_tuple_to_wkt_discards_inverted_bbox():
    assert discovery_ops._bbox_4326_tuple_to_wkt((10.5, 40.0, 10.0, 41.0)) is None


def test_bbox_tuple_to_wkt_rounds_to_five_decimal_places():
    # the frontend's TerraDraw silently drops features with coordinates over 9
    # decimal places, so stored bboxes must come out rounded
    wkt = discovery_ops._bbox_4326_tuple_to_wkt(
        (-9.370596897483855, 40.51113433598111, -9.159202392776214, 40.805561916939304)
    )
    for coordinate in shapely.from_wkt(wkt).exterior.coords:
        for value in coordinate:
            assert value == round(value, 5)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_discovery_extracts_metadata(db_session_maker, admin_user, discovery_env):
    _write_geotiff(
        discovery_env["archive_root"] / _MISSION_RELATIVE_PATH / "s01/sub/grid.tif"
    )

    collector = await _run_discovery(
        db_session_maker,
        discovery_env["mission"].id,
        discovery_env["settings"],
        admin_user,
    )

    ended = _ended_events(collector)
    assert len(ended) == 1
    assert ended[0].succeeded is True

    records = await _get_mission_records(db_session_maker, discovery_env["mission"].id)
    assert len(records) == 1
    record = records[0]
    assert record.name["en"] == "grid.tif"
    assert record.description["en"].startswith("Auto-extracted: GTiff raster")
    assert record.description["pt"].startswith("Extração automática: raster GTiff")
    assert record.bbox_4326 is not None
    # the synthetic EPSG:3763 grid reprojects to central Portugal
    minx, miny, maxx, maxy = to_shape(record.bbox_4326).bounds
    assert -8.2 < minx <= maxx < -8.0
    assert 39.6 < miny <= maxy < 39.8
    async with db_session_maker() as session:
        statement = sqlmodel.select(models.RecordAsset).where(
            models.RecordAsset.survey_related_record_id == record.id
        )
        assets = (await session.exec(statement)).all()
    assert len(assets) == 1
    assert assets[0].relative_path == "s01/sub/grid.tif"
    # the extracted summary goes on the record only; the asset stays empty
    assert assets[0].description["en"] == ""
    # discovered assets are the record's data files, with a media type derived
    # from the file extension
    assert assets[0].asset_type == [constants.AssetType.DATA]
    assert assets[0].media_type == "application/prs.ipma.tif"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_discovery_is_idempotent(
    db_session_maker, admin_user, discovery_env, monkeypatch
):
    _write_geotiff(
        discovery_env["archive_root"] / _MISSION_RELATIVE_PATH / "s01/grid.tif"
    )
    extraction_calls = []
    real_dispatch = discovery_ops.extractor_dispatch.dispatch_extractor

    def counting_dispatch(path):
        extraction_calls.append(path)
        return real_dispatch(path)

    monkeypatch.setattr(
        discovery_ops.extractor_dispatch, "dispatch_extractor", counting_dispatch
    )

    await _run_discovery(
        db_session_maker,
        discovery_env["mission"].id,
        discovery_env["settings"],
        admin_user,
    )
    first_records = await _get_mission_records(
        db_session_maker, discovery_env["mission"].id
    )
    second_collector = await _run_discovery(
        db_session_maker,
        discovery_env["mission"].id,
        discovery_env["settings"],
        admin_user,
    )

    records = await _get_mission_records(db_session_maker, discovery_env["mission"].id)
    assert len(records) == 1
    assert records[0].id == first_records[0].id
    # dedup runs BEFORE extraction, so the second run must not extract at all
    assert len(extraction_calls) == 1
    # and the second run must not even attempt a record creation (a failed
    # attempt would surface as a succeeded=False modification event)
    assert not any(
        isinstance(e, event_schemas.ResourceModificationEvent) and e.succeeded is False
        for e in second_collector.events
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_discovery_dedup_is_scoped_per_mission(
    db_session_maker, admin_user, discovery_env
):
    # the same mission-relative file path exists in two missions: each mission
    # must get its own record (dedup must not be global)
    second_mission_relative_path = "surveys/test-mission-2"
    _write_geotiff(
        discovery_env["archive_root"] / _MISSION_RELATIVE_PATH / "s01/grid.tif"
    )
    _write_geotiff(
        discovery_env["archive_root"] / second_mission_relative_path / "s01/grid.tif"
    )
    async with db_session_maker() as session:
        second_mission = await _create_mission(
            session,
            admin_user,
            identifiers.ProjectId(discovery_env["project"].id),
            second_mission_relative_path,
            name_suffix=" 2",
        )

    for mission_id in (discovery_env["mission"].id, second_mission.id):
        await _run_discovery(
            db_session_maker, mission_id, discovery_env["settings"], admin_user
        )

    first_records = await _get_mission_records(
        db_session_maker, discovery_env["mission"].id
    )
    second_records = await _get_mission_records(db_session_maker, second_mission.id)
    assert len(first_records) == 1
    assert len(second_records) == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_discovery_survives_extraction_failure(
    db_session_maker, admin_user, discovery_env, caplog
):
    bad_file = discovery_env["archive_root"] / _MISSION_RELATIVE_PATH / "s01/bad.tif"
    bad_file.parent.mkdir(parents=True, exist_ok=True)
    bad_file.write_bytes(b"this is not a tif")

    with caplog.at_level(logging.WARNING, logger=discovery_ops.logger.name):
        collector = await _run_discovery(
            db_session_maker,
            discovery_env["mission"].id,
            discovery_env["settings"],
            admin_user,
        )

    ended = _ended_events(collector)
    assert len(ended) == 1
    assert ended[0].succeeded is True
    assert any(
        "Metadata extraction failed" in record.message for record in caplog.records
    )

    records = await _get_mission_records(db_session_maker, discovery_env["mission"].id)
    assert len(records) == 1
    record = records[0]
    assert record.name["en"] == "bad.tif"
    assert record.description["en"] == ""
    assert record.description["pt"] == ""
    assert record.bbox_4326 is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_discovery_passes_temporal_extent_through(
    db_session_maker, admin_user, discovery_env, monkeypatch
):
    # KMALL and SEG-Y do emit temporal dates, but a faked dispatcher keeps this
    # test about the passthrough itself rather than about any one extractor
    target = discovery_env["archive_root"] / _MISSION_RELATIVE_PATH / "s01/dated.tif"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"content is irrelevant, dispatch is faked")

    def fake_dispatch(path):
        return extractor_schemas.RasterMetadata(
            driver="GTiff",
            width=1,
            height=1,
            band_count=1,
            bbox_4326=(-8.2, 39.6, -8.1, 39.7),
            temporal_extent_begin=dt.date(2024, 9, 28),
            temporal_extent_end=dt.date(2024, 9, 29),
        )

    monkeypatch.setattr(
        discovery_ops.extractor_dispatch, "dispatch_extractor", fake_dispatch
    )

    await _run_discovery(
        db_session_maker,
        discovery_env["mission"].id,
        discovery_env["settings"],
        admin_user,
    )

    records = await _get_mission_records(db_session_maker, discovery_env["mission"].id)
    assert len(records) == 1
    record = records[0]
    assert record.temporal_extent_begin == dt.date(2024, 9, 28)
    assert record.temporal_extent_end == dt.date(2024, 9, 29)
    # the stored bbox is the metadata bbox expanded by the always-applied buffer
    assert to_shape(record.bbox_4326).bounds == pytest.approx(
        (-8.2001, 39.5999, -8.0999, 39.7001)
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_discovery_applies_mission_implicit_crs(
    db_session_maker, admin_user, discovery_env, monkeypatch
):
    # formats that cannot carry a CRS (XYZ grids, SEG-Y) only yield a native
    # bbox: the mission's implicit CRS is what turns it into a map bbox
    target = discovery_env["archive_root"] / _MISSION_RELATIVE_PATH / "s01/implicit.tif"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"content is irrelevant, dispatch is faked")

    def fake_dispatch(path):
        return extractor_schemas.RasterMetadata(
            driver="XYZ",
            width=10,
            height=10,
            band_count=1,
            bbox_native=_NATIVE_BBOX_TM06,
        )

    monkeypatch.setattr(
        discovery_ops.extractor_dispatch, "dispatch_extractor", fake_dispatch
    )
    async with db_session_maker() as session:
        mission = await session.get(models.SurveyMission, discovery_env["mission"].id)
        mission.implicit_crs = 3763
        session.add(mission)
        await session.commit()

    await _run_discovery(
        db_session_maker,
        discovery_env["mission"].id,
        discovery_env["settings"],
        admin_user,
    )

    records = await _get_mission_records(db_session_maker, discovery_env["mission"].id)
    assert len(records) == 1
    # the native bbox reprojects from ETRS89/PT-TM06 to central Portugal
    minx, miny, maxx, maxy = to_shape(records[0].bbox_4326).bounds
    assert -8.2 < minx <= maxx < -8.0
    assert 39.6 < miny <= maxy < 39.8


@pytest.mark.integration
@pytest.mark.asyncio
async def test_discovery_implicit_crs_default_discards_projected_coordinates(
    db_session_maker, admin_user, discovery_env, monkeypatch, caplog
):
    # the 4326 default is a placeholder: metre coordinates then fail the lon/lat
    # range check and the bbox correctly stays NULL
    assert discovery_env["mission"].implicit_crs == 4326
    target = discovery_env["archive_root"] / _MISSION_RELATIVE_PATH / "s01/metres.tif"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"content is irrelevant, dispatch is faked")

    def fake_dispatch(path):
        return extractor_schemas.RasterMetadata(
            driver="XYZ",
            width=10,
            height=10,
            band_count=1,
            bbox_native=_NATIVE_BBOX_TM06,
        )

    monkeypatch.setattr(
        discovery_ops.extractor_dispatch, "dispatch_extractor", fake_dispatch
    )

    with caplog.at_level(logging.WARNING, logger=discovery_ops.logger.name):
        await _run_discovery(
            db_session_maker,
            discovery_env["mission"].id,
            discovery_env["settings"],
            admin_user,
        )

    records = await _get_mission_records(db_session_maker, discovery_env["mission"].id)
    assert len(records) == 1
    assert records[0].bbox_4326 is None
    assert any("Discarding extracted bbox" in r.message for r in caplog.records)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_discovery_survives_invalid_implicit_crs(
    db_session_maker, admin_user, discovery_env, monkeypatch
):
    target = discovery_env["archive_root"] / _MISSION_RELATIVE_PATH / "s01/bogus.tif"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"content is irrelevant, dispatch is faked")

    def fake_dispatch(path):
        return extractor_schemas.RasterMetadata(
            driver="XYZ",
            width=10,
            height=10,
            band_count=1,
            bbox_native=_NATIVE_BBOX_TM06,
        )

    monkeypatch.setattr(
        discovery_ops.extractor_dispatch, "dispatch_extractor", fake_dispatch
    )
    async with db_session_maker() as session:
        mission = await session.get(models.SurveyMission, discovery_env["mission"].id)
        mission.implicit_crs = 999999
        session.add(mission)
        await session.commit()

    collector = await _run_discovery(
        db_session_maker,
        discovery_env["mission"].id,
        discovery_env["settings"],
        admin_user,
    )

    ended = _ended_events(collector)
    assert len(ended) == 1
    assert ended[0].succeeded is True
    records = await _get_mission_records(db_session_maker, discovery_env["mission"].id)
    assert len(records) == 1
    assert records[0].bbox_4326 is None
