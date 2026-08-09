import re
import uuid

import pytest
from playwright.sync_api import (
    expect,
    Page,
)


def _fill_project_form_minimal(page: Page, english_name: str):
    page.get_by_role("textbox", name="field-name-en").fill(english_name)


def _fill_survey_mission_form_minimal(page: Page, english_name: str):
    page.get_by_role("textbox", name="field-name-en").fill(english_name)


def _fill_survey_related_record_form(page: Page, english_name: str):
    page.get_by_role("textbox", name="field-name-en").fill(english_name)
    page.get_by_role("textbox", name="field-name-pt").fill("Registo de teste e2e")
    page.get_by_role("textbox", name="field-description-en").fill(
        "e2e survey-related record description"
    )
    page.get_by_role("textbox", name="field-description-pt").fill(
        "descrição do registo de teste"
    )


@pytest.mark.e2e
def test_survey_related_record_lifecycle(authenticated_page: Page):
    # NOTE: this test is perhaps overly long, but for now it covers the full creation
    # and deletion lifecycle of survey-related records. Let's revise later once
    # search functionality has been implemented.

    authenticated_page.goto("/")
    authenticated_page.get_by_role("link", name="list-projects").click()
    authenticated_page.get_by_role("link", name="new-project").click()

    project_name = f"e2e test project {uuid.uuid4().hex[:8]}"
    _fill_project_form_minimal(authenticated_page, project_name)
    authenticated_page.get_by_role("button", name="submit-create-form").click()
    expect(authenticated_page).to_have_url(
        re.compile(r"/projects/[0-9a-f-]{36}$"), timeout=10_000
    )

    # create the survey mission
    authenticated_page.get_by_role("link", name="new-item").click()
    mission_name = f"e2e test survey mission {uuid.uuid4().hex[:8]}"
    _fill_survey_mission_form_minimal(authenticated_page, mission_name)
    authenticated_page.get_by_role("button", name="submit-create-form").click()
    expect(authenticated_page).to_have_url(
        re.compile(r"/survey-missions/[0-9a-f-]{36}$"), timeout=10_000
    )

    # create the survey-related record
    record_name_id = uuid.uuid4().hex[:8]
    authenticated_page.get_by_role("link", name="new-item").click()
    record_name = f"e2e test survey-related record {record_name_id}"
    _fill_survey_related_record_form(authenticated_page, record_name)

    authenticated_page.get_by_role(
        "button", name="add-another-link", exact=True
    ).click()
    authenticated_page.get_by_role("textbox", name="field-link-links-0-url").fill(
        "http://fakelink.com/for/record"
    )
    authenticated_page.get_by_role(
        "textbox", name="field-link-links-0-media_type"
    ).fill("text/html")
    authenticated_page.get_by_role("textbox", name="field-link-links-0-relation").fill(
        "fake-relation"
    )
    authenticated_page.get_by_role(
        "textbox", name="field-link-links-0-link_description-en"
    ).fill("some link description")
    authenticated_page.get_by_role(
        "textbox", name="field-link-links-0-link_description-pt"
    ).fill("uma descrição do link")

    authenticated_page.get_by_role(
        "button", name="add-another-link", exact=True
    ).click()
    authenticated_page.get_by_role("textbox", name="field-link-links-1-url").fill(
        "http://fakelink2.com"
    )
    authenticated_page.get_by_role(
        "textbox", name="field-link-links-1-media_type"
    ).fill("text/html")
    authenticated_page.get_by_role("textbox", name="field-link-links-1-relation").fill(
        "fake-relation2"
    )
    authenticated_page.get_by_role(
        "textbox", name="field-link-links-1-link_description-en"
    ).fill("some description for link 2")
    authenticated_page.get_by_role(
        "textbox", name="field-link-links-1-link_description-pt"
    ).fill("uma descrição do segundo link")

    authenticated_page.get_by_role(
        "button", name="add-another-asset", exact=True
    ).click()
    authenticated_page.get_by_role("textbox", name="field-asset-assets-0-name-en").fill(
        "Sample e2e asset"
    )
    authenticated_page.get_by_role("textbox", name="field-asset-assets-0-name-pt").fill(
        "Recurso de teste e2e"
    )
    authenticated_page.get_by_role(
        "textbox", name="field-asset-assets-0-description-en"
    ).fill("This is a sample asset used in e2e tests")
    authenticated_page.get_by_role(
        "textbox", name="field-asset-assets-0-description-pt"
    ).fill("Este é um recurso de test usado em testes e2e")
    authenticated_page.get_by_role(
        "textbox", name="field-asset-assets-0-relative_path"
    ).fill("/asset/relative/path.tif")
    authenticated_page.get_by_role("button", name="asset-0-add-another-link").click()
    authenticated_page.get_by_role(
        "textbox", name="field-asset-0-link-assets-0-links-0-url"
    ).fill("http://fakelink.com/for/record")
    authenticated_page.get_by_role(
        "textbox", name="field-asset-0-link-assets-0-links-0-media_type"
    ).fill("text/html")
    authenticated_page.get_by_role(
        "textbox", name="field-asset-0-link-assets-0-links-0-relation"
    ).fill("fake-relation")
    authenticated_page.get_by_role(
        "textbox", name="field-link-assets-0-links-0-link_description-en"
    ).fill("some link description")
    authenticated_page.get_by_role(
        "textbox", name="field-link-assets-0-links-0-link_description-pt"
    ).fill("uma descrição do link")

    authenticated_page.get_by_role("button", name="add-another-asset").click()
    authenticated_page.get_by_role("textbox", name="field-asset-assets-1-name-en").fill(
        "Sample e2e second asset"
    )
    authenticated_page.get_by_role("textbox", name="field-asset-assets-1-name-pt").fill(
        "Segundo recurso de teste e2e"
    )
    authenticated_page.get_by_role(
        "textbox", name="field-asset-assets-1-description-en"
    ).fill("This the second sample asset used in e2e tests")
    authenticated_page.get_by_role(
        "textbox", name="field-asset-assets-1-description-pt"
    ).fill("Este é um segundo recurso de test usado em testes e2e")
    authenticated_page.get_by_role(
        "textbox", name="field-asset-assets-1-relative_path"
    ).fill("/asset/relative/second-path.tif")
    authenticated_page.get_by_role("button", name="asset-1-add-another-link").click()
    authenticated_page.get_by_role(
        "textbox", name="field-asset-1-link-assets-1-links-0-url"
    ).fill("http://fakelink.com/for/record")
    authenticated_page.get_by_role(
        "textbox", name="field-asset-1-link-assets-1-links-0-media_type"
    ).fill("text/html")
    authenticated_page.get_by_role(
        "textbox", name="field-asset-1-link-assets-1-links-0-relation"
    ).fill("fake-relation")
    authenticated_page.get_by_role(
        "textbox", name="field-link-assets-1-links-0-link_description-en"
    ).fill("some link description")
    authenticated_page.get_by_role(
        "textbox", name="field-link-assets-1-links-0-link_description-pt"
    ).fill("uma descrição do link")

    authenticated_page.get_by_role("button", name="submit-create-form").click()
    expect(authenticated_page).to_have_url(
        re.compile(r"/survey-related-records/[0-9a-f-]{36}$"), timeout=10_000
    )

    # now try to modify the record but cancel
    authenticated_page.get_by_role("link", name="update-item").click()
    authenticated_page.get_by_role("link", name="cancel-update").click()

    # and now actually modify it
    authenticated_page.get_by_role("link", name="update-item").click()
    authenticated_page.get_by_role("textbox", name="field-name-en").fill(
        f"The modified name {record_name_id}"
    )
    authenticated_page.get_by_role("button", name="submit-update-form").click()

    # clean up: delete record → mission → project
    authenticated_page.get_by_role(
        "button", name="show-delete-confirmation-modal"
    ).click()
    authenticated_page.get_by_role("button", name="delete-item").click()
    expect(authenticated_page.get_by_role("link", name="new-item")).to_be_visible()

    authenticated_page.get_by_role(
        "button", name="show-delete-confirmation-modal"
    ).click()
    authenticated_page.get_by_role("button", name="delete-item").click()
    expect(authenticated_page).to_have_url(
        re.compile(r"/projects/[0-9a-f-]{36}$"), timeout=15_000
    )

    authenticated_page.get_by_role(
        "button", name="show-delete-confirmation-modal"
    ).click()
    authenticated_page.get_by_role("button", name="delete-item").click()
    expect(authenticated_page).to_have_url(re.compile(r"/projects/?$"))


@pytest.mark.e2e
def test_survey_related_record_bulk_selection(authenticated_page: Page):
    # NOTE: this only exercises the selection primitives (checkboxes, count,
    # clear, auto-clear-on-filter-change) on the mission-scoped listing, where
    # the record count is fully controlled by the test. The top-level listing
    # pools records system-wide, so a deterministic "select all N matching"
    # assertion there would depend on how much other data exists in the DB.

    authenticated_page.goto("/")
    authenticated_page.get_by_role("link", name="list-projects").click()
    authenticated_page.get_by_role("link", name="new-project").click()

    project_name = f"e2e test project {uuid.uuid4().hex[:8]}"
    _fill_project_form_minimal(authenticated_page, project_name)
    authenticated_page.get_by_role("button", name="submit-create-form").click()
    expect(authenticated_page).to_have_url(
        re.compile(r"/projects/[0-9a-f-]{36}$"), timeout=10_000
    )

    authenticated_page.get_by_role("link", name="new-item").click()
    mission_name = f"e2e test survey mission {uuid.uuid4().hex[:8]}"
    _fill_survey_mission_form_minimal(authenticated_page, mission_name)
    authenticated_page.get_by_role("button", name="submit-create-form").click()
    expect(authenticated_page).to_have_url(
        re.compile(r"/survey-missions/[0-9a-f-]{36}$"), timeout=10_000
    )
    mission_detail_url = authenticated_page.url

    record_urls = []
    for i in range(2):
        authenticated_page.get_by_role("link", name="new-item").click()
        record_name = f"e2e bulk selection record {i} {uuid.uuid4().hex[:8]}"
        _fill_survey_related_record_form(authenticated_page, record_name)
        authenticated_page.get_by_role("button", name="submit-create-form").click()
        expect(authenticated_page).to_have_url(
            re.compile(r"/survey-related-records/[0-9a-f-]{36}$"), timeout=10_000
        )
        record_urls.append(authenticated_page.url)
        authenticated_page.goto(mission_detail_url)

    checkboxes = authenticated_page.get_by_role("checkbox", name="select-item")
    expect(checkboxes).to_have_count(2)
    selected_count = authenticated_page.locator("[aria-label='selected-count']")
    clear_selection_button = authenticated_page.get_by_role(
        "button", name="clear-selection"
    )

    checkboxes.nth(0).check()
    expect(selected_count).to_contain_text("1 selected")
    expect(clear_selection_button).to_be_visible()

    checkboxes.nth(1).check()
    expect(selected_count).to_contain_text("2 selected")

    clear_selection_button.click()
    expect(selected_count).to_be_hidden()
    expect(clear_selection_button).to_be_hidden()

    # selecting again, then changing the search filter should clear it back out. NOTE:
    # we assert on the checkboxes disappearing rather than on the translated
    # "no records found" message, since the e2e suite runs against whatever the
    # default locale is (currently portuguese) and that message text is not stable
    # across locales.
    checkboxes.nth(0).check()
    expect(selected_count).to_contain_text("1 selected")
    authenticated_page.get_by_placeholder("search").fill("something not matching")
    expect(checkboxes).to_have_count(0)
    authenticated_page.get_by_placeholder("search").fill("")
    expect(selected_count).to_be_hidden()

    # clean up: delete both records, then mission, then project
    for record_url in record_urls:
        authenticated_page.goto(record_url)
        authenticated_page.get_by_role(
            "button", name="show-delete-confirmation-modal"
        ).click()
        authenticated_page.get_by_role("button", name="delete-item").click()
        expect(authenticated_page.get_by_role("link", name="new-item")).to_be_visible()

    authenticated_page.get_by_role(
        "button", name="show-delete-confirmation-modal"
    ).click()
    authenticated_page.get_by_role("button", name="delete-item").click()
    expect(authenticated_page).to_have_url(
        re.compile(r"/projects/[0-9a-f-]{36}$"), timeout=15_000
    )

    authenticated_page.get_by_role(
        "button", name="show-delete-confirmation-modal"
    ).click()
    authenticated_page.get_by_role("button", name="delete-item").click()
    expect(authenticated_page).to_have_url(re.compile(r"/projects/?$"))


@pytest.mark.e2e
def test_bulk_update_survey_related_records(authenticated_page: Page):
    # NOTE: only exercises the "manually selected" mode - "select all matching"
    # only becomes available when more records match than fit on one page,
    # which a small deterministic fixture like this one won't trigger (same
    # reasoning as test_survey_related_record_bulk_selection above). The
    # filtered/select-all-matching path is already covered at the
    # operation/command layer by integration tests.

    authenticated_page.goto("/")
    authenticated_page.get_by_role("link", name="list-projects").click()
    authenticated_page.get_by_role("link", name="new-project").click()

    project_name = f"e2e test project {uuid.uuid4().hex[:8]}"
    _fill_project_form_minimal(authenticated_page, project_name)
    authenticated_page.get_by_role("button", name="submit-create-form").click()
    expect(authenticated_page).to_have_url(
        re.compile(r"/projects/[0-9a-f-]{36}$"), timeout=10_000
    )

    authenticated_page.get_by_role("link", name="new-item").click()
    mission_name = f"e2e test survey mission {uuid.uuid4().hex[:8]}"
    _fill_survey_mission_form_minimal(authenticated_page, mission_name)
    authenticated_page.get_by_role("button", name="submit-create-form").click()
    expect(authenticated_page).to_have_url(
        re.compile(r"/survey-missions/[0-9a-f-]{36}$"), timeout=10_000
    )
    mission_detail_url = authenticated_page.url

    record_urls = []
    for i in range(2):
        authenticated_page.get_by_role("link", name="new-item").click()
        record_name = f"e2e bulk update record {i} {uuid.uuid4().hex[:8]}"
        _fill_survey_related_record_form(authenticated_page, record_name)
        authenticated_page.get_by_role("button", name="submit-create-form").click()
        expect(authenticated_page).to_have_url(
            re.compile(r"/survey-related-records/[0-9a-f-]{36}$"), timeout=10_000
        )
        record_urls.append(authenticated_page.url)
        authenticated_page.goto(mission_detail_url)

    checkboxes = authenticated_page.get_by_role("checkbox", name="select-item")
    expect(checkboxes).to_have_count(2)
    checkboxes.nth(0).check()
    checkboxes.nth(1).check()

    authenticated_page.get_by_role("link", name="bulk-update").click()
    expect(authenticated_page).to_have_url(
        re.compile(r"/survey-missions/[0-9a-f-]{36}/records/bulk-update\?"),
        timeout=10_000,
    )
    expect(
        authenticated_page.locator("[aria-label='bulk-update-matched-count']")
    ).to_contain_text("2")

    # submitting with nothing checked should fail validation, not silently no-op
    authenticated_page.get_by_role("button", name="submit-bulk-update-form").click()
    expect(
        authenticated_page.locator(
            "#backend-validation-update_dataset_category-feedback"
        )
    ).to_be_visible()

    authenticated_page.get_by_role(
        "checkbox", name="field-update_workflow_stage"
    ).check()
    workflow_stage_select = authenticated_page.get_by_role(
        "combobox", name="field-workflow_stage_id"
    )
    # picked by index rather than by (locale-dependent) label text - new records
    # default to whichever stage sorts first, so index 1 is guaranteed different
    target_workflow_stage_id = (
        workflow_stage_select.locator("option").nth(1).get_attribute("value")
    )
    workflow_stage_select.select_option(index=1)
    authenticated_page.get_by_role("button", name="submit-bulk-update-form").click()

    expect(authenticated_page).to_have_url(mission_detail_url, timeout=15_000)
    expect(authenticated_page.locator(".toast.text-bg-info")).to_be_visible()

    for record_url in record_urls:
        authenticated_page.goto(record_url)
        authenticated_page.get_by_role("link", name="update-item").click()
        expect(
            authenticated_page.get_by_role("combobox", name="field-workflow_stage_id")
        ).to_have_value(target_workflow_stage_id)

    # clean up: delete both records, then mission, then project
    for record_url in record_urls:
        authenticated_page.goto(record_url)
        authenticated_page.get_by_role(
            "button", name="show-delete-confirmation-modal"
        ).click()
        authenticated_page.get_by_role("button", name="delete-item").click()
        expect(authenticated_page.get_by_role("link", name="new-item")).to_be_visible()

    authenticated_page.get_by_role(
        "button", name="show-delete-confirmation-modal"
    ).click()
    authenticated_page.get_by_role("button", name="delete-item").click()
    expect(authenticated_page).to_have_url(
        re.compile(r"/projects/[0-9a-f-]{36}$"), timeout=15_000
    )

    authenticated_page.get_by_role(
        "button", name="show-delete-confirmation-modal"
    ).click()
    authenticated_page.get_by_role("button", name="delete-item").click()
    expect(authenticated_page).to_have_url(re.compile(r"/projects/?$"))


@pytest.mark.e2e
def test_survey_related_record_creation_rejects_duplicate_english_name(
    authenticated_page: Page,
):
    authenticated_page.goto("/")
    authenticated_page.get_by_role("link", name="list-projects").click()
    authenticated_page.get_by_role("link", name="new-project").click()

    project_name = f"e2e test project {uuid.uuid4().hex[:8]}"
    _fill_project_form_minimal(authenticated_page, project_name)
    authenticated_page.get_by_role("button", name="submit-create-form").click()
    expect(authenticated_page).to_have_url(
        re.compile(r"/projects/[0-9a-f-]{36}$"), timeout=10_000
    )

    # create the survey mission
    authenticated_page.get_by_role("link", name="new-item").click()
    mission_name = f"e2e test survey mission {uuid.uuid4().hex[:8]}"
    _fill_survey_mission_form_minimal(authenticated_page, mission_name)
    authenticated_page.get_by_role("button", name="submit-create-form").click()
    expect(authenticated_page).to_have_url(
        re.compile(r"/survey-missions/[0-9a-f-]{36}$"), timeout=10_000
    )
    mission_detail_url = authenticated_page.url

    # create the initial survey-related record
    authenticated_page.get_by_role("link", name="new-item").click()
    record_name = f"e2e duplicate record {uuid.uuid4().hex[:8]}"
    _fill_survey_related_record_form(authenticated_page, record_name)
    authenticated_page.get_by_role("button", name="submit-create-form").click()
    expect(authenticated_page).to_have_url(
        re.compile(r"/survey-related-records/[0-9a-f-]{36}$"), timeout=10_000
    )
    record_detail_url = authenticated_page.url

    # try to create another record with the same english name under the same mission
    authenticated_page.goto(mission_detail_url)
    authenticated_page.get_by_role("link", name="new-item").click()
    _fill_survey_related_record_form(authenticated_page, record_name)
    authenticated_page.get_by_role("button", name="submit-create-form").click()
    expect(
        authenticated_page.locator("#backend-validation-name-en-feedback")
    ).to_be_visible()

    # clean up: navigate to the record detail page and delete it, then mission, then project
    authenticated_page.goto(record_detail_url)
    authenticated_page.get_by_role(
        "button", name="show-delete-confirmation-modal"
    ).click()
    authenticated_page.get_by_role("button", name="delete-item").click()
    expect(authenticated_page.get_by_role("link", name="new-item")).to_be_visible()

    authenticated_page.get_by_role(
        "button", name="show-delete-confirmation-modal"
    ).click()
    authenticated_page.get_by_role("button", name="delete-item").click()
    expect(authenticated_page).to_have_url(
        re.compile(r"/projects/[0-9a-f-]{36}$"), timeout=15_000
    )

    authenticated_page.get_by_role(
        "button", name="show-delete-confirmation-modal"
    ).click()
    authenticated_page.get_by_role("button", name="delete-item").click()
    expect(authenticated_page.get_by_role("link", name="new-project")).to_be_visible()
