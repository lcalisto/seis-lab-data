import datetime as dt
from typing import Annotated

import pydantic

from ..constants import (
    DEFAULT_IMPLICIT_CRS,
    SurveyMissionStatus,
)
from ..db import models
from .common import (
    ArchivePath,
    LinkSchema,
    DraftDescription,
    DraftName,
    EpsgCode,
    PolygonOut,
    PossiblyInvalidPolygon,
    serialize_id,
    serialize_possibly_empty_date,
)
from .identifiers import (
    ProjectId,
    SurveyMissionId,
)
from .projects import ProjectReadEmbedded


class SurveyMissionCreate(pydantic.BaseModel):
    id: SurveyMissionId
    project_id: ProjectId
    name: DraftName
    description: DraftDescription
    relative_path: ArchivePath
    implicit_crs: EpsgCode = DEFAULT_IMPLICIT_CRS
    bbox_4326: PossiblyInvalidPolygon | None = None
    temporal_extent_begin: dt.date | None = None
    temporal_extent_end: dt.date | None = None
    links: list[LinkSchema] = []


class SurveyMissionUpdate(pydantic.BaseModel):
    project_id: ProjectId | None = None
    name: DraftName | None = None
    description: DraftDescription | None = None
    relative_path: ArchivePath | None = None
    implicit_crs: EpsgCode | None = None
    bbox_4326: PossiblyInvalidPolygon | None = None
    temporal_extent_begin: dt.date | None = None
    temporal_extent_end: dt.date | None = None
    links: list[LinkSchema] | None = None


class SurveyMissionReadEmbedded(pydantic.BaseModel):
    id: Annotated[SurveyMissionId, pydantic.PlainSerializer(serialize_id)]
    name: DraftName
    status: SurveyMissionStatus
    validation_result: models.ValidationResult | None
    relative_path: str
    temporal_extent_begin: Annotated[
        dt.date | None, pydantic.PlainSerializer(serialize_possibly_empty_date)
    ]
    temporal_extent_end: Annotated[
        dt.date | None, pydantic.PlainSerializer(serialize_possibly_empty_date)
    ]
    project: ProjectReadEmbedded
    bbox_4326: PolygonOut | None

    @classmethod
    def from_db_instance(
        cls, instance: models.SurveyMission
    ) -> "SurveyMissionReadEmbedded":
        return cls(
            **instance.model_dump(),
            project=ProjectReadEmbedded.from_db_instance(instance.project),
        )


class SurveyMissionReadListItem(pydantic.BaseModel):
    id: Annotated[SurveyMissionId, pydantic.PlainSerializer(serialize_id)]
    name: DraftName
    description: DraftDescription
    status: SurveyMissionStatus
    validation_result: models.ValidationResult | None
    project: ProjectReadEmbedded
    temporal_extent_begin: Annotated[
        dt.date | None, pydantic.PlainSerializer(serialize_possibly_empty_date)
    ]
    temporal_extent_end: Annotated[
        dt.date | None, pydantic.PlainSerializer(serialize_possibly_empty_date)
    ]
    bbox_4326: PolygonOut | None
    has_thumbnail: bool

    @classmethod
    def from_db_instance(
        cls, instance: models.SurveyMission
    ) -> "SurveyMissionReadListItem":
        return cls(
            **instance.model_dump(),
            project=ProjectReadEmbedded.from_db_instance(instance.project),
            has_thumbnail=instance.thumbnail is not None,
        )


class SurveyMissionReadDetail(SurveyMissionReadListItem):
    relative_path: str
    implicit_crs: int
    links: list[LinkSchema] = []

    @classmethod
    def from_db_instance(
        cls, instance: models.SurveyMission
    ) -> "SurveyMissionReadDetail":
        return cls(
            **instance.model_dump(),
            project=ProjectReadEmbedded.from_db_instance(instance.project),
            has_thumbnail=instance.thumbnail is not None,
        )
