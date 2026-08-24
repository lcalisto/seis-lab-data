import enum
import typing

from starlette_babel import gettext_lazy as _


AUTH_CLIENT_NAME: typing.Final[str] = "authentik"
ROLE_SYSTEM_ADMIN: typing.Final[str] = "system-admin"
ROLE_ADMIN: typing.Final[str] = "catalog-admin"
ROLE_EDITOR: typing.Final[str] = "catalog-editor"
NAME_MAX_LENGTH: typing.Final[int] = 100
NAME_MIN_LENGTH: typing.Final[int] = 5
DESCRIPTION_MAX_LENGTH: typing.Final[int] = 500
DESCRIPTION_MIN_LENGTH: typing.Final[int] = 5

ASSET_MAX_LINKS: typing.Final[int] = 5
PROJECT_MAX_LINKS: typing.Final[int] = 5
SURVEY_MISSION_MAX_LINKS: typing.Final[int] = 5
SURVEY_RELATED_RECORD_MAX_LINKS: typing.Final[int] = 5
SURVEY_RELATED_RECORD_MAX_ASSETS: typing.Final[int] = 20
SURVEY_RELATED_RECORD_MAX_RELATED: typing.Final[int] = 5

NEW_TOPIC_PROJECTS: typing.Final[str] = "projects"
NEW_TOPIC_SURVEY_MISSIONS: typing.Final[str] = "survey_missions"
NEW_TOPIC_SURVEY_RELATED_RECORDS: typing.Final[str] = "survey_related_records"
NEW_TOPIC_ASSET_DISCOVERY_CONFIGURATIONS: typing.Final[str] = (
    "asset_discovery_conigurations"
)
NEW_TOPIC_DATASET_CATEGORIES: typing.Final[str] = "dataset_categories"
NEW_TOPIC_WORKFLOW_STAGES: typing.Final[str] = "workflow_stages"

PROGRESS_TOPIC_NAME_TEMPLATE: typing.Final[str] = "progress:{request_id}"

PROJECT_UPDATED_TOPIC: typing.Final[str] = "project-updated:{project_id}"
PROJECT_STATUS_CHANGED_TOPIC: typing.Final[str] = "project-status-changed:{project_id}"
PROJECT_VALIDITY_CHANGED_TOPIC: typing.Final[str] = (
    "project-validity-changed:{project_id}"
)
PROJECT_DELETED_TOPIC: typing.Final[str] = "project-deleted:{project_id}"
PROJECT_DISCOVERY_TOPIC: typing.Final[str] = "project-discovery:{project_id}"

SURVEY_MISSION_CREATED_TOPIC: typing.Final[str] = "survey-mission-created"
SURVEY_MISSION_DISCOVERY_TOPIC: typing.Final[str] = (
    "survey-mission-discovery:{survey_mission_id}"
)
SURVEY_MISSION_UPDATED_TOPIC: typing.Final[str] = (
    "survey-mission-updated:{survey_mission_id}"
)
SURVEY_MISSION_STATUS_CHANGED_TOPIC: typing.Final[str] = (
    "survey-mission-status-changed:{survey_mission_id}"
)
SURVEY_MISSION_VALIDITY_CHANGED_TOPIC: typing.Final[str] = (
    "survey-mission-validity-changed:{survey_mission_id}"
)
SURVEY_MISSION_DELETED_TOPIC: typing.Final[str] = (
    "survey-mission-deleted:{survey_mission_id}"
)

SURVEY_RELATED_RECORD_CREATED_TOPIC: typing.Final[str] = "survey-related-record-created"
SURVEY_RELATED_RECORD_UPDATED_TOPIC: typing.Final[str] = (
    "survey-related-record-updated:{survey_related_record_id}"
)
SURVEY_RELATED_RECORD_STATUS_CHANGED_TOPIC: typing.Final[str] = (
    "survey-related-record-status-changed:{survey_related_record_id}"
)
SURVEY_RELATED_RECORD_VALIDITY_CHANGED_TOPIC: typing.Final[str] = (
    "survey-related-record-validity-changed:{survey_related_record_id}"
)
SURVEY_RELATED_RECORD_DELETED_TOPIC: typing.Final[str] = (
    "survey-related-record-deleted:{survey_related_record_id}"
)


class PageType(str, enum.Enum):
    HOME = "home"
    RESOURCE_LIST = "resource_list"
    RESOURCE_NEW = "resource_new"
    RESOURCE_UPDATE = "resource_update"
    RESOURCE_DETAIL = "resource_detail"


class ResourceType(str, enum.Enum):
    ASSET_DISCOVERY_CONFIG = "asset_discovery_configuration"
    CATEGORY = "dataset_category"
    MISSION = "survey_mission"
    PROJECT = "project"
    RECORD = "survey_related_record"
    WORKFLOW_STAGE = "workflow_stage"

    def get_topic_name(self) -> str:
        return {
            self.ASSET_DISCOVERY_CONFIG: NEW_TOPIC_ASSET_DISCOVERY_CONFIGURATIONS,
            self.CATEGORY: NEW_TOPIC_DATASET_CATEGORIES,
            self.MISSION: NEW_TOPIC_SURVEY_MISSIONS,
            self.PROJECT: NEW_TOPIC_PROJECTS,
            self.RECORD: NEW_TOPIC_SURVEY_RELATED_RECORDS,
            self.WORKFLOW_STAGE: NEW_TOPIC_WORKFLOW_STAGES,
        }[self]


class ResourceModification(str, enum.Enum):
    CREATED = "created"
    DELETED = "deleted"
    UPDATED = "updated"
    PUBLISHED = "published"
    UNPUBLISHED = "unpublished"


class BulkResourceModification(str, enum.Enum):
    UPDATED = "updated"
    DELETED = "deleted"


class DiscoveryStage(str, enum.Enum):
    STARTED = "started"
    ENDED = "ended"
    PROGRESS = "progress"


class ValidationStage(str, enum.Enum):
    STARTED = "started"
    ENDED = "ended"


class TranslatableEnumProtocol(typing.Protocol):
    def get_translated_value(self) -> str: ...


class ProcessingStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"

    def get_translated_value(self) -> str:
        return {
            self.PENDING: _("pending"),
            self.RUNNING: _("running"),
            self.SUCCESS: _("success"),
            self.FAILED: _("failed"),
            self.CANCELLED: _("cancelled"),
        }.get(self, self.value)


class AssetType(str, enum.Enum):
    DATA = "data"
    THUMBNAIL = "thumbnail"
    PREVIEW = "preview"

    def get_translated_value(self) -> str:
        return {
            self.DATA: _("data"),
            self.THUMBNAIL: _("thumbnail"),
            self.PREVIEW: _("preview"),
        }.get(self, self.value)


class ProjectStatus(str, enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    UNDER_DISCOVERY = "under_discovery"
    UNDER_PARSING = "under_parsing"
    UNDER_VALIDATION = "under_validation"

    def get_translated_value(self) -> str:
        return {
            self.DRAFT: _("draft"),
            self.PUBLISHED: _("published"),
            self.UNDER_DISCOVERY: _("under_discovery"),
            self.UNDER_PARSING: _("under_parsing"),
            self.UNDER_VALIDATION: _("under_validation"),
        }.get(self, self.value)


class SurveyMissionStatus(str, enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    UNDER_DISCOVERY = "under_discovery"
    UNDER_PARSING = "under_parsing"
    UNDER_VALIDATION = "under_validation"

    def get_translated_value(self) -> str:
        return {
            self.DRAFT: _("draft"),
            self.PUBLISHED: _("published"),
            self.UNDER_DISCOVERY: _("under_discovery"),
            self.UNDER_PARSING: _("under_parsing"),
            self.UNDER_VALIDATION: _("under_validation"),
        }.get(self, self.value)


class SurveyRelatedRecordStatus(str, enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    UNDER_DERIVATION = "under_derivation"
    UNDER_DISCOVERY = "under_discovery"
    UNDER_EXPORT = "under_export"
    UNDER_VALIDATION = "under_validation"
    UNDER_PARSING = "under_parsing"

    def get_translated_value(self) -> str:
        return {
            self.DRAFT: _("draft"),
            self.PUBLISHED: _("published"),
            self.UNDER_DERIVATION: _("under_derivation"),
            self.UNDER_DISCOVERY: _("under_discovery"),
            self.UNDER_EXPORT: _("under_export"),
            self.UNDER_PARSING: _("under_parsing"),
            self.UNDER_VALIDATION: _("under_validation"),
        }.get(self, self.value)
