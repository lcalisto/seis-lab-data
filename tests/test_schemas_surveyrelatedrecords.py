import uuid

import pytest

from seis_lab_data import constants
from seis_lab_data.schemas import (
    common as common_schemas,
    identifiers,
    surveyrelatedrecords as record_schemas,
)


@pytest.mark.parametrize(
    "relative_path, expected",
    [
        pytest.param("s01/grid.tif", "application/prs.ipma.tif"),
        pytest.param("s01/FOO.TIF", "application/prs.ipma.tif"),
        pytest.param("s01/no-extension", None),
        pytest.param("s01/trailing-dot.", None),
        pytest.param(".hidden", "application/prs.ipma.hidden"),
        pytest.param("", None),
    ],
)
def test_derive_media_type(relative_path, expected):
    assert record_schemas.derive_media_type(relative_path) == expected


@pytest.mark.parametrize(
    "media_type",
    [
        pytest.param(None),
        pytest.param(""),
    ],
)
def test_record_asset_create_derives_missing_media_type(media_type):
    asset = record_schemas.DataRecordAssetCreate(
        id=identifiers.RecordAssetId(uuid.uuid4()),
        name=common_schemas.LocalizableDraftName(en="An asset"),
        description=common_schemas.LocalizableDraftDescription(en="An asset"),
        media_type=media_type,
        relative_path="s01/grid.tif",
    )
    assert asset.media_type == "application/prs.ipma.tif"


def test_record_asset_create_keeps_explicit_media_type():
    asset = record_schemas.DataRecordAssetCreate(
        id=identifiers.RecordAssetId(uuid.uuid4()),
        name=common_schemas.LocalizableDraftName(en="An asset"),
        description=common_schemas.LocalizableDraftDescription(en="An asset"),
        media_type="image/tiff",
        relative_path="s01/grid.tif",
    )
    assert asset.media_type == "image/tiff"


def test_record_asset_update_derives_blank_media_type():
    # the update form always submits the field, currently as an empty string
    asset = record_schemas.DataRecordAssetUpdate(
        id=identifiers.RecordAssetId(uuid.uuid4()),
        media_type="",
        relative_path="s01/grid.tif",
    )
    assert asset.media_type == "application/prs.ipma.tif"


def test_record_asset_update_leaves_unsent_media_type_alone():
    # deriving it here would add the field to the set of values to be applied,
    # thereby overwriting whatever media type is already stored
    asset = record_schemas.DataRecordAssetUpdate(
        id=identifiers.RecordAssetId(uuid.uuid4()),
        relative_path="s01/grid.tif",
    )
    assert asset.media_type is None
    assert "media_type" not in asset.model_dump(exclude_unset=True)


def test_record_asset_update_without_relative_path_has_no_media_type_to_derive():
    asset = record_schemas.DataRecordAssetUpdate(
        id=identifiers.RecordAssetId(uuid.uuid4()),
        media_type="",
    )
    assert asset.media_type == ""


def test_record_asset_update_keeps_explicit_media_type():
    asset = record_schemas.DataRecordAssetUpdate(
        id=identifiers.RecordAssetId(uuid.uuid4()),
        media_type="image/tiff",
        relative_path="s01/grid.tif",
    )
    assert asset.media_type == "image/tiff"


def test_derived_record_asset_create_requires_data_or_geog():
    with pytest.raises(ValueError, match="Either data or geog must be provided"):
        record_schemas.DerivedRecordAssetCreate(
            id=identifiers.RecordAssetId(uuid.uuid4()),
            name=common_schemas.LocalizableDraftName(en="A preview"),
            media_type="image/webp",
            asset_type=[constants.AssetType.THUMBNAIL, constants.AssetType.PREVIEW],
        )


def test_survey_related_record_update_allows_multiple_assets_with_unset_names():
    # a partial asset update that doesn't touch the name must not be treated
    # as colliding with other assets that also don't touch their name
    record_schemas.SurveyRelatedRecordUpdate(
        assets=[
            record_schemas.DataRecordAssetUpdate(
                id=identifiers.RecordAssetId(uuid.uuid4()),
                relative_path="first-asset",
            ),
            record_schemas.DataRecordAssetUpdate(
                id=identifiers.RecordAssetId(uuid.uuid4()),
                relative_path="second-asset",
            ),
        ]
    )


def test_survey_related_record_update_rejects_duplicate_asset_english_names():
    with pytest.raises(ValueError, match="Duplicate asset english name found"):
        record_schemas.SurveyRelatedRecordUpdate(
            assets=[
                record_schemas.DataRecordAssetUpdate(
                    id=identifiers.RecordAssetId(uuid.uuid4()),
                    name=common_schemas.LocalizableDraftName(en="Same name"),
                    relative_path="first-asset",
                ),
                record_schemas.DataRecordAssetUpdate(
                    id=identifiers.RecordAssetId(uuid.uuid4()),
                    name=common_schemas.LocalizableDraftName(en="Same name"),
                    relative_path="second-asset",
                ),
            ]
        )
