import datetime as dt
import random
import uuid
from itertools import count
from typing import (
    Iterator,
    Sequence,
)

import pydantic
import shapely
from faker import Faker

from .. import constants
from ..schemas import (
    common as common_schemas,
    identifiers,
    projects as project_schemas,
    surveymissions as mission_schemas,
    surveyrelatedrecords as record_schemas,
    user as user_schemas,
)

from ..db import models

_FAKE_EN = Faker("en_US")
_FAKE_PT = Faker("pt_PT")


_real_owf_seism_2024_project_id = identifiers.ProjectId(
    uuid.UUID("8f931331-15c3-4899-846c-38470f6bcb5a")
)
_real_raw_bathy_record_discovery_conf_id = identifiers.RecordDiscoveryConfId(
    "real_raw_bathy"
)

_raw_bathy_record_discovery_conf_id = identifiers.RecordDiscoveryConfId("raw_bathy")
_processed_bathy_record_discovery_conf_id = identifiers.RecordDiscoveryConfId(
    "processed_bathy"
)
_prr_eolicas_project_id = identifiers.ProjectId(
    uuid.UUID("2b663029-2651-4c2f-b4a9-2f53d5d00c41")
)

_my_first_project_id = identifiers.ProjectId(
    uuid.UUID("74f07051-1aa9-4c08-bc27-3ecf101ab5b3")
)
_my_second_project_id = identifiers.ProjectId(
    uuid.UUID("9a877fbe-da98-45ab-af70-711879c6fc01")
)

_owf_seism_2024_mission_id = identifiers.SurveyMissionId(
    uuid.UUID("73315036-c34a-4e14-a373-697dbb94db3c")
)

_my_first_survey_mission_id = identifiers.SurveyMissionId(
    uuid.UUID("cfe10cd8-5a5e-40e4-807b-7064f94a2edf")
)
_my_second_survey_mission_id = identifiers.SurveyMissionId(
    uuid.UUID("38d9ad16-6cf5-4c64-abfe-0915c6c22268")
)
_my_third_survey_mission_id = identifiers.SurveyMissionId(
    uuid.UUID("ebedf3e5-38a4-42ad-bb60-52b4eee6bd54")
)
_my_fourth_survey_mission_id = identifiers.SurveyMissionId(
    uuid.UUID("03a5f8c1-60ba-4309-a06a-e7b0c8851f20")
)
_my_fifth_survey_mission_id = identifiers.SurveyMissionId(
    uuid.UUID("51a44e56-42e7-4aab-a1c7-659436df99c1")
)


def get_projects_to_create(
    owner: user_schemas.User,
) -> list[project_schemas.ProjectCreate]:
    owner_id = identifiers.UserId(owner.id)
    return [
        project_schemas.ProjectCreate(
            id=_real_owf_seism_2024_project_id,
            owner_id=owner_id,
            name=common_schemas.LocalizableDraftName(
                en="prr eolicas",
            ),
            description=common_schemas.LocalizableDraftDescription(
                en="A description about the prr eolicas project",
            ),
            root_path="projects/prr-eolicas",
        ),
        # project_schemas.ProjectCreate(
        #     id=_prr_eolicas_project_id,
        #     owner_id=owner_id,
        #     name=common_schemas.LocalizableDraftName(
        #         en="PRR windfarms", pt="PRR Eólicas"
        #     ),
        #     description=common_schemas.LocalizableDraftDescription(
        #         en="A description about the PRR windfarms project",
        #         pt="Uma descrição sobre o projeto PRR Eólicas",
        #     ),
        #     root_path="simulated_archive/surveys",
        #     discovery_configuration=discovery_schemas.ProjectDiscoveryConfiguration(
        #         survey_missions=[
        #             discovery_schemas.SurveyMissionDiscoveryConfiguration(
        #                 name=discovery_schemas.TranslatableString(
        #                     {"en": discovery_schemas.TemplatedString("seism-2024")}
        #                 ),
        #                 description=discovery_schemas.TranslatableString(
        #                     {
        #                         "en": discovery_schemas.TemplatedString(
        #                             "Some description about the seism-2024 survey"
        #                         )
        #                     }
        #                 ),
        #                 relative_path="owf-seism-2024",
        #                 record_configuration_ids=[
        #                     _raw_bathy_record_discovery_conf_id,
        #                     _processed_bathy_record_discovery_conf_id,
        #                 ],
        #             ),
        #         ],
        #         records={
        #             str(
        #                 _raw_bathy_record_discovery_conf_id
        #             ): discovery_schemas.SurveyRecordDiscoveryConfiguration(
        #                 id_=_raw_bathy_record_discovery_conf_id,
        #                 dataset_category="bathymetry",
        #                 workflow_stage="raw data",
        #                 name=discovery_schemas.TranslatableString(
        #                     {
        #                         "en": discovery_schemas.TemplatedString(
        #                             "Raw bathymetry {date_dashed} - pathway #{pathway}"
        #                         ),
        #                         "pt": discovery_schemas.TemplatedString(
        #                             "Batimetria em bruto {date_dashed} - pathway #{pathway}"
        #                         ),
        #                     }
        #                 ),
        #                 extra_properties=[
        #                     discovery_schemas.RecordProperty(
        #                         identifier="date",
        #                         handler=discovery_schemas.DateYmdProperty(),
        #                     ),
        #                     discovery_schemas.RecordProperty(
        #                         identifier="date_dashed",
        #                         handler=discovery_schemas.DateYmdDashedProperty(),
        #                     ),
        #                     discovery_schemas.RecordProperty(
        #                         identifier="pathway",
        #                         handler=discovery_schemas.ConstantProperty(
        #                             pattern=r"\d{4}"
        #                         ),
        #                     ),
        #                     discovery_schemas.RecordProperty(
        #                         identifier="ship",
        #                         handler=discovery_schemas.ConstantProperty(
        #                             pattern=r"\w+"
        #                         ),
        #                     ),
        #                 ],
        #                 assets=[
        #                     discovery_schemas.RecordAssetDiscoveryConfiguration(
        #                         name=discovery_schemas.TranslatableString(
        #                             {
        #                                 "en": discovery_schemas.TemplatedString(
        #                                     "kmall file"
        #                                 ),
        #                                 "pt": discovery_schemas.TemplatedString(
        #                                     "Ficheiro kmall"
        #                                 ),
        #                             }
        #                         ),
        #                         discovery_patterns=[
        #                             discovery_schemas.TemplatedString(
        #                                 r"s06-mbes/s02-raw-data/01-EM712/{{date_dashed}}/{{pathway}}_{{date}}_\d{6}_{{ship}}.kmall"
        #                             )
        #                         ],
        #                     )
        #                 ],
        #             ),
        #             str(
        #                 _processed_bathy_record_discovery_conf_id
        #             ): discovery_schemas.SurveyRecordDiscoveryConfiguration(
        #                 id_=_processed_bathy_record_discovery_conf_id,
        #                 dataset_category="bathymetry",
        #                 workflow_stage="processed data",
        #                 name=discovery_schemas.TranslatableString(
        #                     {
        #                         "en": discovery_schemas.TemplatedString(
        #                             "{region} - Processed bathymetry"
        #                         ),
        #                         "pt": discovery_schemas.TemplatedString(
        #                             "Batimetria processada - {region}"
        #                         ),
        #                     }
        #                 ),
        #                 extra_properties=[
        #                     discovery_schemas.RecordProperty(
        #                         identifier="region",
        #                         handler=discovery_schemas.ConstantProperty(
        #                             pattern=r"[A-Z]{3}"
        #                         ),
        #                     ),
        #                 ],
        #                 assets=[
        #                     discovery_schemas.RecordAssetDiscoveryConfiguration(
        #                         name=discovery_schemas.TranslatableString(
        #                             {
        #                                 "en": discovery_schemas.TemplatedString(
        #                                     "XYZ file"
        #                                 ),
        #                                 "pt": discovery_schemas.TemplatedString(
        #                                     "Ficheiro XYZ"
        #                                 ),
        #                             }
        #                         ),
        #                         discovery_patterns=[
        #                             discovery_schemas.TemplatedString(
        #                                 r"s06-mbes/s05-processed-data/{{region}}_All_Mainlines?_and_Xlines?_MBES_Grid_4m.xyz"
        #                             )
        #                         ],
        #                     )
        #                 ],
        #             ),
        #         },
        #         record_relations=[],
        #     ),
        # ),
        project_schemas.ProjectCreate(
            id=_my_first_project_id,
            owner_id=owner_id,
            name=common_schemas.LocalizableDraftName(
                en="My first project", pt="O meu primeiro projeto"
            ),
            description=common_schemas.LocalizableDraftDescription(
                en="A Fake description for my first project",
                pt="Uma descrição falsa para o meu primeiro projeto",
            ),
            root_path="/projects/first",
            links=[
                common_schemas.LinkSchema(
                    url=pydantic.AnyHttpUrl("https://fakeurl.com"),
                    media_type="text/html",
                    relation="related",
                    link_description=common_schemas.LocalizableDraftDescription(
                        en="A fake description for link",
                        pt="Uma descrição falsa para o link",
                    ),
                ),
            ],
        ),
        project_schemas.ProjectCreate(
            id=_my_second_project_id,
            owner_id=owner_id,
            name=common_schemas.LocalizableDraftName(
                en="My second project", pt="O meu segundo projeto"
            ),
            description=common_schemas.LocalizableDraftDescription(
                en="A fake description for my second project",
                pt="Uma descrição sintética para o meu segundo projeto",
            ),
            root_path="/projects/second",
            links=[
                common_schemas.LinkSchema(
                    url=pydantic.AnyHttpUrl("https://fakeurl.com"),
                    media_type="text/html",
                    relation="related",
                    link_description=common_schemas.LocalizableDraftDescription(
                        en="A fake description for link",
                        pt="Uma descrição falsa para o link",
                    ),
                )
            ],
        ),
    ]


def get_survey_missions_to_create(
    owner: user_schemas.User,
) -> list[mission_schemas.SurveyMissionCreate]:
    return [
        mission_schemas.SurveyMissionCreate(
            id=_owf_seism_2024_mission_id,
            owner_id=identifiers.UserId(owner.id),
            project_id=_real_owf_seism_2024_project_id,
            name=common_schemas.LocalizableDraftName(en="owf-seism-2024"),
            description=common_schemas.LocalizableDraftDescription(en=""),
            relative_path="surveys/owf-seism-2024",
        ),
        mission_schemas.SurveyMissionCreate(
            id=_my_first_survey_mission_id,
            owner_id=identifiers.UserId(owner.id),
            project_id=_my_first_project_id,
            name=common_schemas.LocalizableDraftName(
                en="My first survey mission", pt="A minha primeira missão"
            ),
            description=common_schemas.LocalizableDraftDescription(
                en="This is the description for my first survey mission",
                pt="Esta é a descrição para a minha primeira missão",
            ),
            relative_path="mission1",
            links=[
                common_schemas.LinkSchema(
                    url=pydantic.AnyHttpUrl("https://fakeurl1.com"),
                    media_type="text/html",
                    relation="related",
                    link_description=common_schemas.LocalizableDraftDescription(
                        en="A fake description for the first link",
                        pt="Uma descrição falsa para o primeiro link",
                    ),
                ),
                common_schemas.LinkSchema(
                    url=pydantic.AnyHttpUrl("https://fakeurl2.com"),
                    media_type="text/html",
                    relation="also-related",
                    link_description=common_schemas.LocalizableDraftDescription(
                        en="A fake description for the second link",
                        pt="Uma descrição falsa para o segundo link",
                    ),
                ),
            ],
        ),
        mission_schemas.SurveyMissionCreate(
            id=_my_second_survey_mission_id,
            owner_id=identifiers.UserId(owner.id),
            project_id=_my_first_project_id,
            name=common_schemas.LocalizableDraftName(
                en="My second survey mission", pt="A minha segunda missão"
            ),
            description=common_schemas.LocalizableDraftDescription(
                en="This is the description for my second survey mission",
                pt="Esta é a descrição para a minha segunda missão",
            ),
            relative_path="mission2",
            links=[
                common_schemas.LinkSchema(
                    url=pydantic.AnyHttpUrl("https://fakeurl1.com"),
                    media_type="text/html",
                    relation="related",
                    link_description=common_schemas.LocalizableDraftDescription(
                        en="A fake description for the first link",
                        pt="Uma descrição falsa para o primeiro link",
                    ),
                ),
                common_schemas.LinkSchema(
                    url=pydantic.AnyHttpUrl("https://fakeurl2.com"),
                    media_type="text/html",
                    relation="also-related",
                    link_description=common_schemas.LocalizableDraftDescription(
                        en="A fake description for the second link",
                        pt="Uma descrição falsa para o segundo link",
                    ),
                ),
            ],
        ),
        mission_schemas.SurveyMissionCreate(
            id=_my_third_survey_mission_id,
            owner_id=identifiers.UserId(owner.id),
            project_id=_my_first_project_id,
            name=common_schemas.LocalizableDraftName(
                en="My third survey mission", pt="A minha terceira missão"
            ),
            description=common_schemas.LocalizableDraftDescription(
                en="This is the description for my third survey mission",
                pt="Esta é a descrição para a minha terceira missão",
            ),
            relative_path="mission3",
            links=[
                common_schemas.LinkSchema(
                    url=pydantic.AnyHttpUrl("https://fakeurl1.com"),
                    media_type="text/html",
                    relation="related",
                    link_description=common_schemas.LocalizableDraftDescription(
                        en="A fake description for the first link",
                        pt="Uma descrição falsa para o primeiro link",
                    ),
                ),
                common_schemas.LinkSchema(
                    url=pydantic.AnyHttpUrl("https://fakeurl2.com"),
                    media_type="text/html",
                    relation="also-related",
                    link_description=common_schemas.LocalizableDraftDescription(
                        en="A fake description for the second link",
                        pt="Uma descrição falsa para o segundo link",
                    ),
                ),
            ],
        ),
        mission_schemas.SurveyMissionCreate(
            id=_my_fourth_survey_mission_id,
            owner_id=identifiers.UserId(owner.id),
            project_id=_my_second_project_id,
            name=common_schemas.LocalizableDraftName(
                en="My fourth survey mission", pt="A minha quarta missão"
            ),
            description=common_schemas.LocalizableDraftDescription(
                en="This is the description for my fourth survey mission",
                pt="Esta é a descrição para a minha quarta missão",
            ),
            relative_path="mission4",
            links=[
                common_schemas.LinkSchema(
                    url=pydantic.AnyHttpUrl("https://fakeurl1.com"),
                    media_type="text/html",
                    relation="related",
                    link_description=common_schemas.LocalizableDraftDescription(
                        en="A fake description for the first link",
                        pt="Uma descrição falsa para o primeiro link",
                    ),
                ),
                common_schemas.LinkSchema(
                    url=pydantic.AnyHttpUrl("https://fakeurl2.com"),
                    media_type="text/html",
                    relation="also-related",
                    link_description=common_schemas.LocalizableDraftDescription(
                        en="A fake description for the second link",
                        pt="Uma descrição falsa para o segundo link",
                    ),
                ),
            ],
        ),
        mission_schemas.SurveyMissionCreate(
            id=_my_fifth_survey_mission_id,
            owner_id=identifiers.UserId(owner.id),
            project_id=_my_second_project_id,
            name=common_schemas.LocalizableDraftName(
                en="My fifth survey mission", pt="A minha quinta missão"
            ),
            description=common_schemas.LocalizableDraftDescription(
                en="This is the description for my fifth survey mission",
                pt="Esta é a descrição para a minha quinta missão",
            ),
            relative_path="mission5",
            links=[
                common_schemas.LinkSchema(
                    url=pydantic.AnyHttpUrl("https://fakeurl1.com"),
                    media_type="text/html",
                    relation="related",
                    link_description=common_schemas.LocalizableDraftDescription(
                        en="A fake description for the first link",
                        pt="Uma descrição falsa para o primeiro link",
                    ),
                ),
                common_schemas.LinkSchema(
                    url=pydantic.AnyHttpUrl("https://fakeurl2.com"),
                    media_type="text/html",
                    relation="also-related",
                    link_description=common_schemas.LocalizableDraftDescription(
                        en="A fake description for the second link",
                        pt="Uma descrição falsa para o segundo link",
                    ),
                ),
            ],
        ),
    ]


def get_survey_related_records_to_create(
    owner: user_schemas.User,
    dataset_categories: dict[str, models.DatasetCategory],
    workflow_stages: dict[str, models.WorkflowStage],
) -> list[record_schemas.SurveyRelatedRecordCreate]:
    return [
        record_schemas.SurveyRelatedRecordCreate(
            id=identifiers.SurveyRelatedRecordId(
                uuid.UUID("f49d678b-f11a-4798-92dc-604883bc8bda")
            ),
            owner_id=identifiers.UserId(owner.id),
            name=common_schemas.LocalizableDraftName(
                en="First record",
                pt="Primeiro registo",
            ),
            description=common_schemas.LocalizableDraftDescription(
                en="Description for first record",
                pt="Descrição do primeiro registo",
            ),
            survey_mission_id=_my_first_survey_mission_id,
            dataset_category_id=identifiers.DatasetCategoryId(
                dataset_categories["bathymetry"].id
            ),
            workflow_stage_id=identifiers.WorkflowStageId(
                workflow_stages["raw data"].id
            ),
            relative_path="first-record",
            links=[],
            assets=[
                record_schemas.DataRecordAssetCreate(
                    id=identifiers.RecordAssetId(
                        uuid.UUID("85f4683c-7d4a-444c-8896-04278bc89e63")
                    ),
                    name=common_schemas.LocalizableDraftName(
                        en="First asset",
                        pt="Primeiro recurso",
                    ),
                    description=common_schemas.LocalizableDraftDescription(
                        en="Description for first asset",
                        pt="Descrição do primeiro recurso",
                    ),
                    relative_path="first-asset",
                    media_type="application/octet-stream",
                    links=[],
                ),
                record_schemas.DataRecordAssetCreate(
                    id=identifiers.RecordAssetId(
                        uuid.UUID("a9eca3df-03ba-4f46-a98d-3e30139eb035")
                    ),
                    name=common_schemas.LocalizableDraftName(
                        en="Second asset",
                        pt="Segundo recurso",
                    ),
                    description=common_schemas.LocalizableDraftDescription(
                        en="Description for second asset",
                        pt="Descrição do segundo recurso",
                    ),
                    relative_path="second-asset",
                    media_type="application/octet-stream",
                    links=[],
                ),
            ],
        ),
        record_schemas.SurveyRelatedRecordCreate(
            id=identifiers.SurveyRelatedRecordId(
                uuid.UUID("c51e0d11-c4c4-4b4f-8d04-2a115196ff04")
            ),
            owner_id=identifiers.UserId(owner.id),
            name=common_schemas.LocalizableDraftName(
                en="Second record",
                pt="Segundo registo",
            ),
            description=common_schemas.LocalizableDraftDescription(
                en="Description for second record",
                pt="Descrição do segundo registo",
            ),
            survey_mission_id=_my_second_survey_mission_id,
            dataset_category_id=identifiers.DatasetCategoryId(
                dataset_categories["bathymetry"].id
            ),
            workflow_stage_id=identifiers.WorkflowStageId(
                workflow_stages["raw data"].id
            ),
            relative_path="second-record",
            links=[],
            assets=[
                record_schemas.DataRecordAssetCreate(
                    id=identifiers.RecordAssetId(
                        uuid.UUID("a53728ed-5422-4f08-806f-3e75bbb1b3e8")
                    ),
                    name=common_schemas.LocalizableDraftName(
                        en="Third asset",
                        pt="Terceiro recurso",
                    ),
                    description=common_schemas.LocalizableDraftDescription(
                        en="Description for third asset",
                        pt="Descrição do terceiro recurso",
                    ),
                    relative_path="third-asset",
                    media_type="application/octet-stream",
                    links=[],
                ),
                record_schemas.DataRecordAssetCreate(
                    id=identifiers.RecordAssetId(
                        uuid.UUID("bd4bed96-43bd-4d5c-a7b2-d04461dfb23c")
                    ),
                    name=common_schemas.LocalizableDraftName(
                        en="Fourth asset",
                        pt="Quarto recurso",
                    ),
                    description=common_schemas.LocalizableDraftDescription(
                        en="Description for fourth asset",
                        pt="Descrição do quarto recurso",
                    ),
                    relative_path="fourth-asset",
                    media_type="application/octet-stream",
                    links=[],
                ),
            ],
        ),
    ]


def generate_sample_projects(
    owners: Sequence[user_schemas.User],
    dataset_categories: Sequence[identifiers.DatasetCategoryId],
    workflow_stages: Sequence[identifiers.WorkflowStageId],
    root_path: str = "/archive",
) -> Iterator[
    tuple[
        project_schemas.ProjectCreate,
        list[
            tuple[
                mission_schemas.SurveyMissionCreate,
                list[record_schemas.SurveyRelatedRecordCreate],
            ]
        ],
    ],
]:
    """Generate large numbers of sample projects, for development and testingpurposes.

    All projects will be generated with a `_sample` suffix in their english name.
    """
    for _ in count():
        links = (
            [
                next(generate_sample_link())
                for _ in range(_FAKE_EN.random_int(0, constants.PROJECT_MAX_LINKS))
            ]
            if _FAKE_EN.random_digit() < 5
            else []
        )
        temporal_extent = _generate_sample_temporal_extent()
        project = project_schemas.ProjectCreate(
            id=identifiers.ProjectId(uuid.uuid4()),
            owner_id=identifiers.UserId(random.choice(owners).id),
            name=common_schemas.LocalizableDraftName(
                en=f"sample_{_FAKE_EN.sentence()}",
                pt=f"amostra_{_FAKE_PT.sentence()}",
            ),
            description=common_schemas.LocalizableDraftDescription(
                en=_FAKE_EN.paragraph(nb_sentences=4),
                pt=_FAKE_PT.paragraph(nb_sentences=4),
            ),
            root_path=f"/{root_path}/{_FAKE_EN.file_path(depth=_FAKE_EN.random_int(0, 3), absolute=False)}",
            bbox_4326=(
                _generate_sample_bbox(
                    float(_FAKE_EN.longitude()), float(_FAKE_EN.latitude())
                )
                if _FAKE_EN.random_digit() >= 1
                else None
            ),
            temporal_extent_begin=temporal_extent[0],
            temporal_extent_end=temporal_extent[1],
            links=links,
        )
        mission_generator = generate_sample_survey_missions(
            owners, project.id, dataset_categories, workflow_stages
        )
        missions = [next(mission_generator) for _ in range(_FAKE_EN.random_int(1, 10))]
        yield project, missions


def generate_sample_survey_missions(
    owners: Sequence[user_schemas.User],
    project_id: identifiers.ProjectId,
    dataset_categories: Sequence[identifiers.DatasetCategoryId],
    workflow_stages: Sequence[identifiers.WorkflowStageId],
) -> Iterator[
    tuple[
        mission_schemas.SurveyMissionCreate,
        list[record_schemas.SurveyRelatedRecordCreate],
    ],
]:
    for _ in count():
        links = (
            [
                next(generate_sample_link())
                for _ in range(
                    _FAKE_EN.random_int(0, constants.SURVEY_MISSION_MAX_LINKS)
                )
            ]
            if _FAKE_EN.random_digit() < 5
            else []
        )
        temporal_extent = _generate_sample_temporal_extent()
        mission = mission_schemas.SurveyMissionCreate(
            id=identifiers.SurveyMissionId(uuid.uuid4()),
            project_id=project_id,
            owner_id=identifiers.UserId(random.choice(owners).id),
            name=common_schemas.LocalizableDraftName(
                en=f"sample_{_FAKE_EN.sentence()}",
                pt=f"amostra_{_FAKE_PT.sentence()}",
            ),
            description=common_schemas.LocalizableDraftDescription(
                en=_FAKE_EN.paragraph(nb_sentences=4),
                pt=_FAKE_PT.paragraph(nb_sentences=4),
            ),
            relative_path=_FAKE_EN.file_path(
                depth=_FAKE_EN.random_int(1, 8), absolute=False
            ),
            bbox_4326=(
                _generate_sample_bbox(
                    float(_FAKE_EN.longitude()), float(_FAKE_EN.latitude())
                )
                if _FAKE_EN.random_digit() >= 1
                else None
            ),
            temporal_extent_begin=temporal_extent[0],
            temporal_extent_end=temporal_extent[1],
            links=links,
        )
        record_generator = generate_sample_survey_related_records(
            owners, mission.id, dataset_categories, workflow_stages
        )
        records = [next(record_generator) for _ in range(_FAKE_EN.random_int(1, 100))]
        yield mission, records


def generate_sample_survey_related_records(
    owners: Sequence[user_schemas.User],
    survey_mission_id: identifiers.SurveyMissionId,
    dataset_categories: Sequence[identifiers.DatasetCategoryId],
    workflow_stages: Sequence[identifiers.WorkflowStageId],
) -> Iterator[record_schemas.SurveyRelatedRecordCreate]:
    temporal_extent = _generate_sample_temporal_extent()
    for _ in count():
        links = (
            [
                next(generate_sample_link())
                for _ in range(
                    _FAKE_EN.random_int(0, constants.SURVEY_RELATED_RECORD_MAX_LINKS)
                )
            ]
            if _FAKE_EN.random_digit() < 5
            else []
        )
        assets = (
            [
                next(generate_sample_asset())
                for _ in range(
                    _FAKE_EN.random_int(0, constants.SURVEY_RELATED_RECORD_MAX_ASSETS)
                )
            ]
            if _FAKE_EN.random_digit() < 5
            else []
        )
        yield record_schemas.SurveyRelatedRecordCreate(
            id=identifiers.SurveyRelatedRecordId(uuid.uuid4()),
            owner_id=identifiers.UserId(random.choice(owners).id),
            name=common_schemas.LocalizableDraftName(
                en=f"sample_{_FAKE_EN.sentence()}",
                pt=f"amostra_{_FAKE_PT.sentence()}",
            ),
            description=common_schemas.LocalizableDraftDescription(
                en=_FAKE_EN.paragraph(nb_sentences=4),
                pt=_FAKE_PT.paragraph(nb_sentences=4),
            ),
            survey_mission_id=survey_mission_id,
            dataset_category_id=random.choice(dataset_categories),
            workflow_stage_id=random.choice(workflow_stages),
            relative_path=_FAKE_EN.file_path(
                depth=_FAKE_EN.random_int(1, 8), absolute=False
            ),
            bbox_4326=(
                _generate_sample_bbox(
                    float(_FAKE_EN.longitude()), float(_FAKE_EN.latitude())
                )
                if _FAKE_EN.random_digit() >= 1
                else None
            ),
            temporal_extent_begin=temporal_extent[0],
            temporal_extent_end=temporal_extent[1],
            links=links,
            assets=assets,
        )


def generate_sample_asset() -> Iterator[record_schemas.DataRecordAssetCreate]:
    for _ in count():
        links = (
            [
                next(generate_sample_link())
                for _ in range(_FAKE_EN.random_int(0, constants.ASSET_MAX_LINKS))
            ]
            if _FAKE_EN.random_digit() < 5
            else []
        )
        yield record_schemas.DataRecordAssetCreate(
            id=identifiers.RecordAssetId(uuid.uuid4()),
            name=common_schemas.LocalizableDraftName(
                en=f"sample_{_FAKE_EN.sentence()}",
                pt=f"amostra_{_FAKE_PT.sentence()}",
            ),
            description=common_schemas.LocalizableDraftDescription(
                en=_FAKE_EN.paragraph(nb_sentences=4),
                pt=_FAKE_PT.paragraph(nb_sentences=4),
            ),
            relative_path=_FAKE_EN.file_path(
                depth=_FAKE_EN.random_int(1, 4), absolute=False
            ),
            links=links,
        )


def generate_sample_link() -> Iterator[common_schemas.LinkSchema]:
    for _ in count():
        yield common_schemas.LinkSchema(
            url=_FAKE_EN.url(),
            media_type=_FAKE_EN.random_element(
                (
                    "application/json",
                    "application/pdf",
                    "application/xml",
                    "text/html",
                    "text/plain",
                )
            ),
            relation=_FAKE_EN.random_element(
                # this is a list of IANA link relations, as gotten from:
                # https://www.iana.org/assignments/link-relations/link-relations.xhtml
                (
                    "about",
                    "acl",
                    "alternate",
                    "amphtml",
                    "api-catalog",
                    "appendix",
                    "apple-touch-icon",
                    "apple-touch-startup-image",
                    "archives",
                    "author",
                    "blocked-by",
                    "bookmark",
                    "c2pa-manifest",
                    "canonical",
                    "chapter",
                    "cite-as",
                    "collection",
                    "compression-dictionary",
                    "contents",
                    "convertedfrom",
                    "copyright",
                    "create-form",
                    "current",
                    "deprecation",
                    "describedby",
                    "describes",
                    "disclosure",
                    "dns-prefetch",
                    "duplicate",
                    "edit",
                    "edit-form",
                    "edit-media",
                    "enclosure",
                    "external",
                    "first",
                    "geofeed",
                    "glossary",
                    "help",
                    "hosts",
                    "hub",
                    "ice-server",
                    "icon",
                    "index",
                    "intervalafter",
                    "intervalbefore",
                    "intervalcontains",
                    "intervaldisjoint",
                    "intervalduring",
                    "intervalequals",
                    "intervalfinishedby",
                    "intervalfinishes",
                    "intervalin",
                    "intervalmeets",
                    "intervalmetby",
                    "intervaloverlappedby",
                    "intervaloverlaps",
                    "intervalstartedby",
                    "intervalstarts",
                    "item",
                    "last",
                    "latest-version",
                    "license",
                    "linkset",
                    "lrdd",
                    "manifest",
                    "mask-icon",
                    "me",
                    "media-feed",
                    "memento",
                    "micropub",
                    "modulepreload",
                    "monitor",
                    "monitor-group",
                    "next",
                    "next-archive",
                    "nofollow",
                    "noopener",
                    "noreferrer",
                    "opener",
                    "openid2.local_id",
                    "openid2.provider",
                    "original",
                    "p3pv1",
                    "payment",
                    "pingback",
                    "preconnect",
                    "predecessor-version",
                    "prefetch",
                    "preload",
                    "prerender",
                    "prev",
                    "preview",
                    "previous",
                    "prev-archive",
                    "privacy-policy",
                    "profile",
                    "publication",
                    "rdap-active",
                    "rdap-bottom",
                    "rdap-down",
                    "rdap-top",
                    "rdap-up",
                    "related",
                    "restconf",
                    "replies",
                    "ruleinput",
                    "search",
                    "section",
                    "self",
                    "service",
                    "service-desc",
                    "service-doc",
                    "service-meta",
                    "sip-trunking-capability",
                    "sponsored",
                    "start",
                    "status",
                    "stylesheet",
                    "subsection",
                    "successor-version",
                    "sunset",
                    "tag",
                    "terms-of-service",
                    "timegate",
                    "timemap",
                    "type",
                    "ugc",
                    "up",
                    "version-history",
                    "via",
                    "webmention",
                    "working-copy",
                    "working-copy-of",
                )
            ),
            link_description=common_schemas.LocalizableDraftDescription(
                en=_FAKE_EN.paragraph(nb_sentences=3),
                pt=_FAKE_PT.paragraph(nb_sentences=3),
            ),
        )


def _generate_sample_bbox(x: float, y: float) -> str:
    width = random.random() * 0.4  # 0 - .4 degrees
    height = random.random() * 0.4  # 0 - .4 degrees
    other_x = (x + width + 180) % 360 - 180
    other_y = (y + height + 90) % 180 - 90
    x_min = min(x, other_x)
    x_max = max(x, other_x)
    y_min = min(y, other_y)
    y_max = max(y, other_y)
    return shapely.box(x_min, y_min, x_max, y_max).wkt


def _generate_sample_temporal_extent() -> tuple[dt.date | None, dt.date | None]:
    end = _FAKE_EN.date_object()
    start = _FAKE_EN.date_object(end_datetime=dt.datetime(end.year, end.month, end.day))
    return random.choice([start, None]), random.choice([end, None])
