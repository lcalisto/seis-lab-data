import base64
import datetime as dt
import json
import uuid
from functools import partial
from typing import (
    Annotated,
    TypedDict,
)

import shapely
from geoalchemy2 import (
    Geometry,
    WKBElement,
)
from pydantic import (
    ConfigDict,
    PlainSerializer,
)
from sqlalchemy.dialects.postgresql import (
    ARRAY,
    JSONB,
)
from sqlalchemy import (
    Enum,
    LargeBinary,
)
from sqlmodel import (
    Column,
    Date,
    DateTime,
    Field,
    func,
    SQLModel,
    Relationship,
)

from .. import constants

now_ = partial(dt.datetime.now, tz=dt.timezone.utc)


class ValidationError(TypedDict):
    name: str
    type_: str
    message: str


class ValidationResult(TypedDict):
    is_valid: bool
    errors: list[ValidationError] | None


def serialize_wkbelement(wkbelement: WKBElement):
    geom = shapely.from_wkb(bytes(wkbelement.data))
    return json.loads(shapely.to_geojson(geom))


class Link(TypedDict):
    url: str
    media_type: str
    relation: str
    link_description: str


class User(SQLModel, table=True):
    __tablename__ = "appuser"

    id: str = Field(max_length=100, primary_key=True)
    username: str = Field(max_length=150)
    email: str = Field(max_length=254)


class DatasetCategory(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(max_length=constants.NAME_MAX_LENGTH)

    survey_related_records: list["SurveyRelatedRecord"] = Relationship(
        back_populates="dataset_category",
    )
    asset_discovery_configurations: list["AssetDiscoveryConfiguration"] = Relationship(
        back_populates="dataset_category"
    )


class WorkflowStage(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(max_length=constants.NAME_MAX_LENGTH)

    survey_related_records: list["SurveyRelatedRecord"] = Relationship(
        back_populates="workflow_stage",
    )
    asset_discovery_configurations: list["AssetDiscoveryConfiguration"] = Relationship(
        back_populates="workflow_stage"
    )


class AssetDiscoveryConfiguration(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(unique=True)
    relative_path_regexp: str
    media_type: str
    generate_previews: bool = Field(
        default=False, sa_column_kwargs={"server_default": "false"}
    )
    workflow_stage_id: uuid.UUID | None = Field(
        foreign_key="workflowstage.id", ondelete="CASCADE", index=True
    )
    dataset_category_id: uuid.UUID | None = Field(
        foreign_key="datasetcategory.id", ondelete="CASCADE", index=True
    )
    dataset_category: DatasetCategory = Relationship(
        back_populates="asset_discovery_configurations"
    )
    workflow_stage: WorkflowStage = Relationship(
        back_populates="asset_discovery_configurations"
    )


class SurveyRelatedRecord(SQLModel, table=True):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(max_length=constants.NAME_MAX_LENGTH)
    description: str = Field(default="", max_length=constants.DESCRIPTION_MAX_LENGTH)
    status: constants.SurveyRelatedRecordStatus = (
        constants.SurveyRelatedRecordStatus.DRAFT
    )
    validation_result: ValidationResult = Field(sa_column=Column(JSONB))
    survey_mission_id: uuid.UUID = Field(
        foreign_key="surveymission.id",
        ondelete="CASCADE",
        index=True,
    )
    dataset_category_id: uuid.UUID | None = Field(
        foreign_key="datasetcategory.id", default=None, ondelete="SET NULL"
    )
    workflow_stage_id: uuid.UUID | None = Field(
        foreign_key="workflowstage.id", default=None, ondelete="SET NULL"
    )
    links: list[Link] = Field(sa_column=Column(JSONB), default_factory=list)
    survey_mission: "SurveyMission" = Relationship(
        back_populates="survey_related_records"
    )
    dataset_category: DatasetCategory = Relationship(
        back_populates="survey_related_records"
    )
    workflow_stage: WorkflowStage = Relationship(
        back_populates="survey_related_records"
    )
    bbox_4326: (
        Annotated[
            WKBElement,
            PlainSerializer(serialize_wkbelement, return_type=dict, when_used="json"),
        ]
        | None
    ) = Field(
        sa_column=Column(
            Geometry(
                srid=4326,
                geometry_type="POLYGON",
                spatial_index=True,
            ),
        )
    )
    created_at: dt.datetime | None = Field(default_factory=now_)
    updated_at: dt.datetime | None = Field(
        sa_column=Column(DateTime(), onupdate=func.now())
    )
    temporal_extent_begin: dt.date | None = Field(sa_column=Column(Date()))
    temporal_extent_end: dt.date | None = Field(sa_column=Column(Date()))
    geonode_resource_url: str | None = None
    geonode_exported_at: dt.datetime | None = None

    related_to_links: list["SurveyRelatedRecordSelfLink"] = Relationship(
        back_populates="subject",
        sa_relationship_kwargs={
            "primaryjoin": "SurveyRelatedRecordSelfLink.subject_id == SurveyRelatedRecord.id",
        },
    )
    subject_links: list["SurveyRelatedRecordSelfLink"] = Relationship(
        back_populates="related_to",
        sa_relationship_kwargs={
            "primaryjoin": "SurveyRelatedRecordSelfLink.related_to_id == SurveyRelatedRecord.id",
        },
    )

    assets: list["RecordAsset"] = Relationship(
        back_populates="survey_related_record",
        sa_relationship_kwargs={
            # "cascade": "all, delete-orphan",
            "cascade": "save-update, merge, expunge, delete, delete-orphan",
            "passive_deletes": True,
        },
    )


class SurveyRelatedRecordSelfLink(SQLModel, table=True):
    subject_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="surveyrelatedrecord.id",
        primary_key=True,
        ondelete="CASCADE",
    )
    related_to_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="surveyrelatedrecord.id",
        primary_key=True,
        ondelete="CASCADE",
    )
    relation: str = Field(max_length=constants.RELATION_MAX_LENGTH)

    subject: SurveyRelatedRecord = Relationship(
        back_populates="related_to_links",
        sa_relationship_kwargs={
            "primaryjoin": "SurveyRelatedRecordSelfLink.subject_id == SurveyRelatedRecord.id",
        },
    )
    related_to: SurveyRelatedRecord = Relationship(
        back_populates="subject_links",
        sa_relationship_kwargs={
            "primaryjoin": "SurveyRelatedRecordSelfLink.related_to_id == SurveyRelatedRecord.id",
        },
    )


class SurveyMission(SQLModel, table=True):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(max_length=constants.NAME_MAX_LENGTH)
    description: str = Field(default="", max_length=constants.DESCRIPTION_MAX_LENGTH)
    project_id: uuid.UUID = Field(
        foreign_key="project.id",
        ondelete="CASCADE",
        index=True,
    )
    links: list[Link] = Field(sa_column=Column(JSONB), default_factory=list)
    relative_path: str = ""
    # fallback EPSG code for discovered files whose format cannot declare a CRS
    implicit_crs: int = Field(
        default=constants.DEFAULT_IMPLICIT_CRS,
        sa_column_kwargs={"server_default": str(constants.DEFAULT_IMPLICIT_CRS)},
    )
    status: constants.SurveyMissionStatus = constants.SurveyMissionStatus.DRAFT
    validation_result: ValidationResult = Field(sa_column=Column(JSONB))
    bbox_4326: (
        Annotated[
            WKBElement,
            PlainSerializer(serialize_wkbelement, return_type=dict, when_used="json"),
        ]
        | None
    ) = Field(
        sa_column=Column(
            Geometry(
                srid=4326,
                geometry_type="POLYGON",
                spatial_index=True,
            ),
        )
    )
    # always a WEBP image, so no media type is stored alongside it
    thumbnail: Annotated[
        bytes | None,
        PlainSerializer(
            lambda v: base64.b64encode(v).decode(),
            return_type=str,
            when_used="json-unless-none",
        ),
    ] = Field(default=None, sa_column=Column(LargeBinary))
    created_at: dt.datetime | None = Field(default_factory=now_)
    updated_at: dt.datetime | None = Field(
        sa_column=Column(DateTime(), onupdate=func.now())
    )
    temporal_extent_begin: dt.date | None = Field(sa_column=Column(Date()))
    temporal_extent_end: dt.date | None = Field(sa_column=Column(Date()))

    project: "Project" = Relationship(back_populates="survey_missions")
    survey_related_records: list["SurveyRelatedRecord"] = Relationship(
        back_populates="survey_mission",
        sa_relationship_kwargs={
            "cascade": "all, delete-orphan",
            "passive_deletes": True,
        },
    )


class Project(SQLModel, table=True):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(max_length=constants.NAME_MAX_LENGTH)
    description: str = Field(default="", max_length=constants.DESCRIPTION_MAX_LENGTH)
    status: constants.ProjectStatus = constants.ProjectStatus.DRAFT
    validation_result: ValidationResult = Field(sa_column=Column(JSONB))
    links: list[Link] = Field(sa_column=Column(JSONB), default_factory=list)
    bbox_4326: (
        Annotated[
            WKBElement,
            PlainSerializer(serialize_wkbelement, return_type=dict, when_used="json"),
        ]
        | None
    ) = Field(
        sa_column=Column(
            Geometry(
                srid=4326,
                geometry_type="POLYGON",
                spatial_index=True,
            ),
        )
    )
    # always a WEBP image, so no media type is stored alongside it
    thumbnail: Annotated[
        bytes | None,
        PlainSerializer(
            lambda v: base64.b64encode(v).decode(),
            return_type=str,
            when_used="json-unless-none",
        ),
    ] = Field(default=None, sa_column=Column(LargeBinary))
    created_at: dt.datetime | None = Field(default_factory=now_)
    updated_at: dt.datetime | None = Field(
        sa_column=Column(DateTime(), onupdate=func.now())
    )
    temporal_extent_begin: dt.date | None = Field(sa_column=Column(Date()))
    temporal_extent_end: dt.date | None = Field(sa_column=Column(Date()))

    survey_missions: list["SurveyMission"] = Relationship(
        back_populates="project",
        sa_relationship_kwargs={
            "cascade": "all, delete-orphan",
            "passive_deletes": True,
        },
    )


class RecordAsset(SQLModel, table=True):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(max_length=constants.NAME_MAX_LENGTH)
    description: str = Field(default="", max_length=constants.DESCRIPTION_MAX_LENGTH)
    survey_related_record_id: uuid.UUID = Field(
        foreign_key="surveyrelatedrecord.id", ondelete="CASCADE", index=True
    )
    # derived assets (previews, thumbnails) have no file in the archive
    relative_path: str | None = Field(default=None, index=True)
    media_type: str
    asset_type: list[constants.AssetType] = Field(
        sa_column=Column(
            ARRAY(Enum(constants.AssetType, name="assettype")), nullable=False
        ),
    )
    # simplified version of the main data asset (low-res raster, histogram, ...)
    data: Annotated[
        bytes | None,
        PlainSerializer(
            lambda v: base64.b64encode(v).decode(),
            return_type=str,
            when_used="json-unless-none",
        ),
    ] = Field(default=None, sa_column=Column(LargeBinary))
    links: list[Link] = Field(sa_column=Column(JSONB), default_factory=list)
    survey_related_record: SurveyRelatedRecord = Relationship(
        back_populates="assets",
    )
