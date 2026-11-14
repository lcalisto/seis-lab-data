import logging

import pydantic
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.requests import Request
from starlette_babel import gettext_lazy as _
from starlette_wtf import StarletteForm
from wtforms import (
    FieldList,
    FormField,
    HiddenField,
    StringField,
)
from wtforms.widgets import TextInput

from ... import constants
from ...db.queries.surveymissions import get_survey_mission_by_name
from ...schemas import (
    identifiers,
    surveymissions as survey_mission_schemas,
)
from .common import (
    BoundingBoxForm,
    NameField,
    DescriptionField,
    incorporate_schema_validation_errors_into_form,
    LinkForm,
)
from .fields import (
    EpsgCodeField,
    OptionalDateField,
)

logger = logging.getLogger(__name__)


class _SurveyMissionForm(StarletteForm):
    """Base form for survey missions.

    This form performs only a very light validation of user input
    There is a more thorough validation phase when checking if the
    project can be made public - the idea is to let the creation process
    succeed (as much as possible) and give the user a chance to fix errors
    later.

    A notable exception is we do want to validate the max length of string-based
    inputs.
    """

    request_id = HiddenField()
    name = NameField()
    description = DescriptionField()
    relative_path = StringField(
        _("Relative path"),
        description=_(
            "Path for the survey mission in the archive file system, "
            "relative to the archive root directory"
        ),
    )
    implicit_crs = EpsgCodeField(
        _("Implicit CRS"),
        default=constants.DEFAULT_IMPLICIT_CRS,
        description=_(
            "EPSG code assumed for discovered files that do not declare a "
            "coordinate reference system. Leave 32629 (WGS 84 / UTM zone 29N) "
            "unless the survey used another one, e.g. around Madeira or the Azores."
        ),
        # text, not number, so a CRS name can be typed to search the suggestions
        widget=TextInput(),
        render_kw={"list": "epsg-code-options", "autocomplete": "off"},
    )
    bounding_box = FormField(BoundingBoxForm)
    temporal_extent_begin = OptionalDateField(_("Temporal extent begin"))
    temporal_extent_end = OptionalDateField(_("Temporal extent end"))
    links = FieldList(
        FormField(LinkForm),
        label=_("Links"),
        min_entries=0,
        max_entries=constants.SURVEY_MISSION_MAX_LINKS,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.implicit_crs.flags.backend_required = True

    async def check_if_name_is_unique_for_project(
        self,
        session: AsyncSession,
        project_id: identifiers.ProjectId,
        disregard_id: identifiers.ProjectId | None = None,
    ):
        """Check if the current name is already used by another survey mission under the same project.

        The `disregard_id` argument can be used when checking uniqueness of the name in the
        context of updating an already existing mission, in which case the mission itself should be
        disregarded, as it is not a conflict for a mission to have the same name as itself.
        """
        error_message = _(
            "There is already a survey mission with this name under the same project"
        )

        if candidate := await get_survey_mission_by_name(
            session, project_id, self.name.data
        ):
            if disregard_id:
                if identifiers.SurveyMissionId(candidate.id) != disregard_id:
                    self.name.errors.append(error_message)
            else:
                self.name.errors.append(error_message)

    def has_validation_errors(self) -> bool:
        # For some unknown reason, wtforms does not report validation errors for
        # listfields together with the other validation errors. This may
        # have something to with the fact that we are setting the 'errors' property
        # of fields manually when performing in the `validate_with_schema()` method.
        # Anyway, we need to employ the below workaround in order
        # to verify if the form contains any errors.
        all_form_validation_errors = {**self.errors}
        for link in self.links.entries:
            all_form_validation_errors.update(**link.errors)
        logger.debug(f"{all_form_validation_errors=}")
        return bool(all_form_validation_errors)

    def validate_with_schema(self) -> None:
        raise NotImplementedError()

    @classmethod
    async def get_validated_form_instance(
        cls,
        request: Request,
        project_id: identifiers.ProjectId,
        disregard_id: identifiers.SurveyMissionId | None = None,
    ):
        """Performs full validation of a survey-mission-related form.

        This performs multiple validations:

        - validate the form with WTForms' validation logic
        - validate the form data with our custom pydantic model
        - validate that the English name is unique across missions of the same
        project

        The already validated form instance is returned.
        """

        form_instance = await cls.from_formdata(request)
        # first validate the form with WTForms' validation logic
        # then validate the form data with our custom pydantic model
        await form_instance.validate_on_submit()
        form_instance.validate_with_schema()
        session_maker = request.state.settings.get_db_session_maker()
        async with session_maker() as session:
            await form_instance.check_if_name_is_unique_for_project(
                session, project_id=project_id, disregard_id=disregard_id
            )
        return form_instance


class SurveyMissionCreateForm(_SurveyMissionForm):
    def validate_with_schema(self):
        # note: we build the schema manually and make sure to not use
        # sub-schemas, but rather provide data with lists and dicts. This is
        # in order to ensure pydantic validates the full set of data at once and
        # includes full error locations - otherwise it would be harder to match
        # pydantic validation errors with wtforms field errors
        try:
            survey_mission_schemas.SurveyMissionCreate(
                # these are not part of the form, but we must provide something
                id=None,
                project_id=None,
                name=self.name.data,
                description=self.description.data,
                relative_path=self.relative_path.data,
                implicit_crs=self.implicit_crs.data,
                temporal_extent_begin=self.temporal_extent_begin.data or None,
                temporal_extent_end=self.temporal_extent_end.data or None,
                links=[
                    {
                        "url": li.url.data,
                        "media_type": li.media_type.data,
                        "relation": li.relation.data,
                        "link_description": li.link_description.data,
                    }
                    for li in self.links.entries
                ],
            )
        except pydantic.ValidationError as exc:
            logger.error(f"pydantic errors {exc.errors()=}")
            incorporate_schema_validation_errors_into_form(exc.errors(), self)


class SurveyMissionUpdateForm(_SurveyMissionForm):
    def validate_with_schema(self):
        # note: we build the schema manually and make sure to not use
        # sub-schemas, but rather provide data with lists and dicts. This is
        # in order to ensure pydantic validates the full set of data at once and
        # includes full error locations - otherwise it would be harder to match
        # pydantic validation errors with wtforms field errors
        try:
            survey_mission_schemas.SurveyMissionUpdate(
                # these are not part of the form, but we must provide something
                project_id=None,
                name=self.name.data,
                description=self.description.data,
                relative_path=self.relative_path.data,
                implicit_crs=self.implicit_crs.data,
                temporal_extent_begin=self.temporal_extent_begin.data or None,
                temporal_extent_end=self.temporal_extent_end.data or None,
                links=[
                    {
                        "url": li.url.data,
                        "media_type": li.media_type.data,
                        "relation": li.relation.data,
                        "link_description": li.link_description.data,
                    }
                    for li in self.links.entries
                ],
            )
        except pydantic.ValidationError as exc:
            logger.error(f"pydantic errors {exc.errors()=}")
            incorporate_schema_validation_errors_into_form(exc.errors(), self)
