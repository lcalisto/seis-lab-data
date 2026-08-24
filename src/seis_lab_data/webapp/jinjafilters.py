"""Custom jinja filters."""

import json
import logging
import typing

import shapely
from jinja2 import pass_context
from markupsafe import Markup
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import JsonLexer

from .. import constants
from ..schemas.common import Localizable
from ..schemas.webui import UserPermissionDetails
from ..localization import translate_localizable

if typing.TYPE_CHECKING:
    from ..config import SeisLabDataSettings
    from ..schemas import projects as project_schemas
    from ..schemas import surveymissions as mission_schemas
    from ..schemas import surveyrelatedrecords as record_schemas

    ItemWithStatus = typing.TypeVar(
        "ItemWithStatus",
        bound=(
            project_schemas.ProjectReadDetail,
            project_schemas.ProjectReadEmbedded,
            project_schemas.ProjectReadListItem,
            mission_schemas.SurveyMissionReadDetail,
            mission_schemas.SurveyMissionReadEmbedded,
            mission_schemas.SurveyMissionReadListItem,
            record_schemas.SurveyRelatedRecordReadDetail,
            record_schemas.SurveyRelatedRecordReadEmbedded,
            record_schemas.SurveyRelatedRecordReadListItem,
        ),
    )

logger = logging.getLogger(__name__)


@pass_context
def get_secondary_language_value(
    context: dict[str, typing.Any], value: Localizable
) -> str:
    current_lang = context["request"].state.language
    secondary_lang = "en" if current_lang == "pt" else "pt"
    return getattr(value, secondary_lang)


@pass_context
def translate_localizable_string(
    context: dict[str, typing.Any], value: Localizable
) -> str:
    return translate_localizable(value, context["request"].state.language)


def is_publishable(
    item: "ItemWithStatus", permissions: "UserPermissionDetails"
) -> bool:
    return all(
        (
            {
                constants.ProjectStatus.DRAFT: True,
                constants.SurveyMissionStatus.DRAFT: True,
                constants.SurveyRelatedRecordStatus.DRAFT: True,
            }.get(item.status),
            (item.validation_result or {}).get("is_valid"),
            permissions.can_update,
        )
    )


def is_unpublishable(
    item: "ItemWithStatus",
    permissions: "UserPermissionDetails",
) -> bool:
    return all(
        (
            {
                constants.ProjectStatus.PUBLISHED: True,
                constants.SurveyMissionStatus.PUBLISHED: True,
                constants.SurveyRelatedRecordStatus.PUBLISHED: True,
            }.get(item.status),
            permissions.can_update,
        )
    )


def is_deletable(
    item: "ItemWithStatus",
    permissions: "UserPermissionDetails",
) -> bool:
    return bool(
        {
            constants.ProjectStatus.DRAFT: True,
            constants.SurveyMissionStatus.DRAFT: True,
            constants.SurveyRelatedRecordStatus.DRAFT: True,
        }.get(item.status)
        and permissions.can_delete
    )


def is_updatable(
    item: "ItemWithStatus",
    permissions: "UserPermissionDetails",
) -> bool:
    return bool(
        {
            constants.ProjectStatus.DRAFT: True,
            constants.SurveyMissionStatus.DRAFT: True,
            constants.SurveyRelatedRecordStatus.DRAFT: True,
        }.get(item.status)
        and permissions.can_update
    )


@pass_context
def get_status_icon_name(
    context: dict[str, typing.Any],
    item: "ItemWithStatus",
) -> str:
    return {
        constants.ProjectStatus.DRAFT: context["icons"]["status_draft"],
        constants.ProjectStatus.UNDER_VALIDATION: context["icons"][
            "status_under_validation"
        ],
        constants.ProjectStatus.PUBLISHED: context["icons"]["status_published"],
        constants.SurveyMissionStatus.DRAFT: context["icons"]["status_draft"],
        constants.SurveyMissionStatus.UNDER_VALIDATION: context["icons"][
            "status_under_validation"
        ],
        constants.SurveyMissionStatus.PUBLISHED: context["icons"]["status_published"],
        constants.SurveyRelatedRecordStatus.DRAFT: context["icons"]["status_draft"],
        constants.SurveyRelatedRecordStatus.UNDER_VALIDATION: context["icons"][
            "status_under_validation"
        ],
        constants.SurveyRelatedRecordStatus.PUBLISHED: context["icons"][
            "status_published"
        ],
    }.get(item.status, context["icons"]["status_other"])


def translate_enum(value: constants.TranslatableEnumProtocol) -> str:
    return value.get_translated_value()


def get_polygon_bounds(polygon_wkt: str) -> tuple[float, float, float, float]:
    geom = shapely.from_wkt(polygon_wkt)
    return geom.bounds


def highlight_json(value: dict) -> Markup:
    json_str = json.dumps(value, indent=2, ensure_ascii=False)
    return Markup(highlight(json_str, JsonLexer(), HtmlFormatter()))


@pass_context
def get_url_for_asset(
    context: dict[str, typing.Any],
    asset: "record_schemas.RecordAssetReadDetailEmbedded",
    item: "record_schemas.SurveyRelatedRecordReadDetail",
) -> str:
    if constants.AssetType.DATA not in asset.asset_type:
        # derived assets have no file in the archive
        return ""
    settings: SeisLabDataSettings = context.get("settings")
    return "/".join(
        (
            settings.public_url,
            item.survey_mission.project.root_path,
            item.survey_mission.relative_path,
            asset.relative_path,
        )
    )
