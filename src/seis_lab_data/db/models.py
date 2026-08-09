import base64
import datetime as dt
import json
import uuid
import warnings
from functools import partial
from typing import (
    Any,
    Annotated,
    Optional,
    TypedDict,
)

import shapely
from geoalchemy2 import (
    Geography,
    Geometry,
    WKBElement,
)
from pydantic import (
    ConfigDict,
    PlainSerializer,
    computed_field,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.exc import SAWarning
from sqlalchemy import (
    Enum,
    Index,
    LargeBinary,
    select,
)
from sqlalchemy.orm import (
    column_property,
    declared_attr,
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

warnings.filterwarnings(
    "ignore",
    r".*Unmanaged access of declarative attribute.*",
    SAWarning,
)

now_ = partial(dt.datetime.now, tz=dt.timezone.utc)


class ValidationError(TypedDict):
    name: str
    type_: str
    message: str


class ValidationResult(TypedDict):
    is_valid: bool
    errors: list[ValidationError] | None


class LocalizableString(TypedDict):
    locale: str


def serialize_wkbelement(wkbelement: WKBElement):
    geom = shapely.from_wkb(bytes(wkbelement.data))
    return json.loads(shapely.to_geojson(geom))


def serialize_localizable_field(value: LocalizableString, _info):
    """Serialize a localizable field.

    Localizable fields use a JSONB type, which is not serialized by default, hence
    the need for this function.
    """
    return value


class Link(TypedDict):
    url: str
    media_type: str
    relation: str
    link_description: LocalizableString


class User(SQLModel, table=True):
    __tablename__ = "appuser"

    id: str = Field(max_length=100, primary_key=True)
    username: str = Field(max_length=150)
    email: str = Field(max_length=254)


class DatasetCategory(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: Annotated[LocalizableString, PlainSerializer(serialize_localizable_field)] = (
        Field(sa_column=Column(JSONB))
    )

    survey_related_records: list["SurveyRelatedRecord"] = Relationship(
        back_populates="dataset_category",
    )
    asset_discovery_configurations: list["AssetDiscoveryConfiguration"] = Relationship(
        back_populates="dataset_category"
    )


class WorkflowStage(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: Annotated[LocalizableString, PlainSerializer(serialize_localizable_field)] = (
        Field(sa_column=Column(JSONB))
    )

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
    __table_args__ = (
        Index("idx_surveyrelatedrecord_name_gin", "name", postgresql_using="gin"),
    )
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    owner_id: str = Field(max_length=100, index=True, foreign_key="appuser.id")
    name: Annotated[LocalizableString, PlainSerializer(serialize_localizable_field)] = (
        Field(sa_column=Column(JSONB))
    )
    description: Annotated[
        LocalizableString, PlainSerializer(serialize_localizable_field)
    ] = Field(sa_column=Column(JSONB))
    status: constants.SurveyRelatedRecordStatus = (
        constants.SurveyRelatedRecordStatus.DRAFT
    )
    is_valid: bool = False
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
    links: Annotated[list[Link], PlainSerializer(serialize_localizable_field)] = Field(
        sa_column=Column(JSONB), default_factory=list
    )
    survey_mission: "SurveyMission" = Relationship(
        back_populates="survey_related_records"
    )
    dataset_category: DatasetCategory = Relationship(
        back_populates="survey_related_records"
    )
    workflow_stage: WorkflowStage = Relationship(
        back_populates="survey_related_records"
    )
    bbox_4326: Annotated[
        WKBElement,
        PlainSerializer(serialize_wkbelement, return_type=dict, when_used="json"),
    ] = Field(
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
    relation: Annotated[
        LocalizableString, PlainSerializer(serialize_localizable_field)
    ] = Field(sa_column=Column(JSONB))

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
    __table_args__ = (
        Index("idx_surveymission_name_gin", "name", postgresql_using="gin"),
    )
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    owner_id: str = Field(max_length=100, index=True, foreign_key="appuser.id")
    name: Annotated[LocalizableString, PlainSerializer(serialize_localizable_field)] = (
        Field(sa_column=Column(JSONB))
    )
    description: Annotated[
        LocalizableString, PlainSerializer(serialize_localizable_field)
    ] = Field(sa_column=Column(JSONB))
    project_id: uuid.UUID = Field(
        foreign_key="project.id",
        ondelete="CASCADE",
        index=True,
    )
    links: Annotated[list[Link], PlainSerializer(serialize_localizable_field)] = Field(
        sa_column=Column(JSONB), default_factory=list
    )
    relative_path: str = ""
    # fallback EPSG code for discovered files whose format cannot declare a CRS
    implicit_crs: int = Field(default=4326, sa_column_kwargs={"server_default": "4326"})
    status: constants.SurveyMissionStatus = constants.SurveyMissionStatus.DRAFT
    is_valid: bool = False
    validation_result: ValidationResult = Field(sa_column=Column(JSONB))
    bbox_4326: Annotated[
        WKBElement,
        PlainSerializer(serialize_wkbelement, return_type=dict, when_used="json"),
    ] = Field(
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

    project: "Project" = Relationship(back_populates="survey_missions")
    survey_related_records: list["SurveyRelatedRecord"] = Relationship(
        back_populates="survey_mission",
        sa_relationship_kwargs={
            "cascade": "all, delete-orphan",
            "passive_deletes": True,
        },
    )

    @computed_field(return_type=Optional[int])
    @declared_attr
    def num_survey_related_records(self):
        return column_property(
            select(func.count(SurveyRelatedRecord.id))
            .where(SurveyRelatedRecord.survey_mission_id == self.id)
            .correlate_except(SurveyRelatedRecord)
            .scalar_subquery()
        )


class Project(SQLModel, table=True):
    __table_args__ = (Index("idx_project_name_gin", "name", postgresql_using="gin"),)
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    owner_id: str = Field(max_length=100, index=True, foreign_key="appuser.id")
    name: Annotated[LocalizableString, PlainSerializer(serialize_localizable_field)] = (
        Field(sa_column=Column(JSONB))
    )
    description: Annotated[
        LocalizableString, PlainSerializer(serialize_localizable_field)
    ] = Field(sa_column=Column(JSONB))
    status: constants.ProjectStatus = constants.ProjectStatus.DRAFT
    root_path: str = ""
    is_valid: bool = False
    validation_result: ValidationResult = Field(sa_column=Column(JSONB))
    links: Annotated[list[Link], PlainSerializer(serialize_localizable_field)] = Field(
        sa_column=Column(JSONB), default_factory=list
    )
    bbox_4326: Annotated[
        WKBElement,
        PlainSerializer(serialize_wkbelement, return_type=dict, when_used="json"),
    ] = Field(
        sa_column=Column(
            Geometry(
                srid=4326,
                geometry_type="POLYGON",
                spatial_index=True,
            ),
        )
    )
    discovery_configuration: dict[str, Any] | None = Field(sa_column=Column(JSONB))
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

    @computed_field(return_type=Optional[int])
    @declared_attr
    def num_survey_missions(self):
        return column_property(
            select(func.count(SurveyMission.id))
            .where(SurveyMission.project_id == self.id)
            .correlate_except(SurveyMission)
            .scalar_subquery()
        )

    @computed_field(return_type=Optional[int])
    @declared_attr
    def num_survey_related_records(self):
        return column_property(
            select(func.count(SurveyRelatedRecord.id))
            .join(SurveyMission)
            .where(SurveyMission.project_id == self.id)
            .correlate_except(SurveyRelatedRecord)
            .scalar_subquery()
        )


class RecordAsset(SQLModel, table=True):
    __table_args__ = (
        Index("idx_recordasset_name_gin", "name", postgresql_using="gin"),
    )
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: Annotated[LocalizableString, PlainSerializer(serialize_localizable_field)] = (
        Field(sa_column=Column(JSONB))
    )
    description: Annotated[
        LocalizableString, PlainSerializer(serialize_localizable_field)
    ] = Field(sa_column=Column(JSONB))
    is_valid: bool = False
    survey_related_record_id: uuid.UUID = Field(
        foreign_key="surveyrelatedrecord.id", ondelete="CASCADE", index=True
    )
    # derived assets (previews, thumbnails) have no file in the archive
    relative_path: str | None = None
    media_type: str
    asset_type: list[constants.AssetType] = Field(
        default_factory=lambda: [constants.AssetType.DATA],
        sa_column=Column(
            ARRAY(Enum(constants.AssetType, name="assettype")), nullable=False
        ),
    )
    # simplified version of the main data asset - deliberately not one single geometry type
    geog: Annotated[
        WKBElement | None,
        PlainSerializer(
            serialize_wkbelement, return_type=dict, when_used="json-unless-none"
        ),
    ] = Field(default=None, sa_column=Column(Geography(srid=4326, spatial_index=True)))
    # simplified version of the main data asset (low-res raster, histogram, ...)
    data: Annotated[
        bytes | None,
        PlainSerializer(
            lambda v: base64.b64encode(v).decode(),
            return_type=str,
            when_used="json-unless-none",
        ),
    ] = Field(default=None, sa_column=Column(LargeBinary))
    links: Annotated[list[Link], PlainSerializer(serialize_localizable_field)] = Field(
        sa_column=Column(JSONB), default_factory=list
    )
    survey_related_record: SurveyRelatedRecord = Relationship(
        back_populates="assets",
    )
