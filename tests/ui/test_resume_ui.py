"""The resume builder in a real browser: the whole journey, one signed-in person at a time. Models are fakes."""
import io
import re

from playwright.sync_api import expect

from tests.unit.resume_templates import make_template


def template_bytes() -> bytes:
    buf = io.BytesIO()
    make_template().save(buf)
    return buf.getvalue()


def sign_in(page, server, name):
    page.goto(server.url)
    page.get_by_role("button", name=re.compile(rf"^{name}")).click()
    page.get_by_role("button", name="Sign in").click()
    expect(page.locator("#portal-screen:visible, #chat-screen:visible")).to_be_visible()  # the portal when there are several apps


WORK_TAB = {"Nancy": "Requests", "Shadrach": "Requests", "Veera": "Review"}  # everyone else works in "My requests"


def open_builder(page, server, name, tab=True):
    """Opens the builder, which lands on the Dashboard, and goes to the tab this person works in."""
    sign_in(page, server, name)
    page.locator('[data-app="rmg"]').click()  # the portal shows one card per app
    expect(page.locator("#who")).to_have_text(name)
    expect(page.locator(".rb-hero")).to_be_visible()
    if tab:
        page.get_by_role("button", name=WORK_TAB.get(name, "My requests"), exact=True).click()
        expect(page.locator(".rb-hero")).to_have_count(0)  # the tab has loaded: the Dashboard is gone


def sign_out(page):
    page.locator("#portal-sign-out:visible, #sign-out:visible").click()  # on the portal, in the chat or in the builder
    expect(page.locator("#login-screen")).to_be_visible()


def test_the_resume_app_is_not_offered_when_the_builder_is_not_configured(page, start_server):
    server = start_server([])

    sign_in(page, server, "Ravi Kumar")  # only HR is installed, so there is nothing to choose: straight into it

    expect(page.locator("#chat-screen")).to_be_visible()
    expect(page.locator("#portal-screen")).to_be_hidden()


def test_a_resume_goes_from_request_to_approved_download(page, start_server):
    server = start_server([], resume=True)

    # The RMG Head sets up the template.
    open_builder(page, server, "Nancy")
    page.get_by_role("button", name="Setup").click()
    page.locator("#tpl-file").set_input_files({"name": "template.docx", "mimeType": "application/octet-stream", "buffer": template_bytes()})
    page.locator("#tpl-go").click()
    expect(page.locator("#message")).to_contain_text("Template uploaded")
    expect(page.locator("#tpl-current")).to_contain_text("template.docx")
    page.goto(server.url)
    sign_out(page)

    # RMG tags Ravi (who has a lead); Sanjay has no lead and can be tagged too, and RMG reviews his resume.
    open_builder(page, server, "Shadrach")
    expect(page.locator("#tag-people label", has_text="Sanjay Patel")).to_contain_text("Reviewed by RMG")
    expect(page.locator("#tag-people input")).to_have_count(11)  # everyone who is not in RMG
    page.get_by_label(re.compile("Ravi Kumar")).check()
    page.locator("#tag-go").click()
    expect(page.locator("#message")).to_contain_text("Tagged 1")
    expect(page.locator(".rb-table tbody tr")).to_have_count(1)
    page.goto(server.url)
    sign_out(page)

    # The associate uploads, builds, edits, asks a question and submits.
    open_builder(page, server, "Ravi Kumar")
    page.get_by_role("button", name="Open").first.click()
    page.locator("#resume-file").set_input_files({"name": "cv.txt", "mimeType": "text/plain", "buffer": b"Ravi Kumar, backend engineer"})
    page.locator("#upload-resume").click()
    expect(page.locator("#message")).to_contain_text("Resume uploaded")
    page.locator("#build").click()
    expect(page.locator("#resume")).to_contain_text("Anil Verma")
    expect(page.locator("#coverage")).to_contain_text("Required skills covered")
    expect(page.locator("#coverage")).to_contain_text("not in your resume")
    expect(page.locator("#template-check-status")).to_contain_text("template")  # the Word file is checked against the setup template
    expect(page.locator("#template-check")).to_contain_text("All checks")
    page.locator("#resume .rb-project .edit").first.click()
    page.get_by_label("New wording").fill("Wrote Java services for payments.")
    page.locator(".save-edit").click()
    expect(page.locator("#resume")).to_contain_text("Wrote Java services for payments.")
    expect(page.locator("#changes")).to_contain_text("Emphasised")
    page.locator("#chat-input").fill("what did you change?")
    page.locator("#chat-send").click()
    expect(page.locator("#chat")).to_contain_text("Changes:")
    page.locator("#submit").click()
    expect(page.locator("#message")).to_contain_text("Submitted")
    expect(page.locator(".rb-bar .badge")).to_have_text("Waiting for review")
    page.goto(server.url)
    sign_out(page)

    # The Competency Lead approves.
    open_builder(page, server, "Veera")
    expect(page.locator("#view .rb-item")).to_have_count(1)
    page.get_by_role("button", name="Open").click()
    expect(page.locator("#changes")).to_contain_text("Emphasised")
    page.locator("#approve").click()
    expect(page.locator("#message")).to_contain_text("Approved")
    page.goto(server.url)
    sign_out(page)

    # RMG downloads the approved resume.
    open_builder(page, server, "Shadrach")
    page.get_by_role("button", name="Open").click()
    with page.expect_download() as info:
        page.locator("#download").click()
    assert info.value.suggested_filename.endswith("_FINAL.docx")
    assert page.console_errors == []


def test_the_lead_can_send_a_resume_back_and_the_associate_sees_why(page, start_server):
    server = start_server([], resume=True)
    open_builder(page, server, "Nancy")
    page.get_by_role("button", name="Setup").click()
    page.locator("#tpl-file").set_input_files({"name": "template.docx", "mimeType": "application/octet-stream", "buffer": template_bytes()})
    page.locator("#tpl-go").click()
    expect(page.locator("#message")).to_contain_text("Template uploaded")
    page.goto(server.url)
    sign_out(page)
    open_builder(page, server, "Shadrach")
    page.get_by_label(re.compile("Ravi Kumar")).check()
    page.locator("#tag-go").click()
    expect(page.locator("#message")).to_contain_text("Tagged 1")
    page.goto(server.url)
    sign_out(page)
    open_builder(page, server, "Ravi Kumar")
    page.get_by_role("button", name="Open").first.click()
    page.locator("#resume-file").set_input_files({"name": "cv.txt", "mimeType": "text/plain", "buffer": b"Ravi"})
    page.locator("#upload-resume").click()
    page.locator("#build").click()
    expect(page.locator("#resume")).to_contain_text("Anil Verma")
    page.locator("#submit").click()
    expect(page.locator("#message")).to_contain_text("Submitted")
    page.goto(server.url)
    sign_out(page)

    open_builder(page, server, "Veera")
    page.get_by_role("button", name="Open").click()
    page.locator("#send-back").click()
    expect(page.locator("#message")).to_contain_text("Please say what needs to change")
    page.locator("#decision-note").fill("Please add more on Kafka")
    page.locator("#send-back").click()
    expect(page.locator("#message")).to_contain_text("Sent back")
    page.goto(server.url)
    sign_out(page)

    open_builder(page, server, "Ravi Kumar")
    page.get_by_role("button", name="Open").first.click()
    expect(page.locator(".rb-bar .badge")).to_have_text("Changes requested")
    expect(page.locator("body")).to_contain_text("Please add more on Kafka")
    page.locator("#bell").click()
    expect(page.locator("#notes")).to_contain_text("sent back")
    assert [e for e in page.console_errors if "422" not in e] == []  # the one deliberate 422 is the empty note


def test_the_job_description_can_be_downloaded_from_the_board_and_from_the_associates_request(page, start_server):
    server = start_server([], resume=True)
    open_builder(page, server, "Shadrach")

    with page.expect_download() as board_download:
        page.locator("#board-jd-download").click()
    assert board_download.value.suggested_filename.endswith(".docx")

    page.get_by_label(re.compile("Ravi Kumar")).check()
    page.locator("#tag-go").click()
    expect(page.locator("#message")).to_contain_text("Tagged 1")
    page.goto(server.url)
    sign_out(page)
    open_builder(page, server, "Ravi Kumar")
    page.get_by_role("button", name="Open").first.click()
    with page.expect_download() as request_download:
        page.locator("#download-jd").click()
    assert request_download.value.suggested_filename.endswith(".docx")
    expect(page.locator("#message")).to_contain_text("Downloaded the job description")
    assert page.console_errors == []


def test_long_requirement_text_stays_inside_its_card_at_common_window_sizes(page, start_server):
    """Found from a screenshot: requirement chips written as long sentences ran out of the narrow left card."""
    server = start_server([], resume=True)
    open_builder(page, server, "Shadrach")
    page.get_by_label(re.compile("Ravi Kumar")).check()
    page.locator("#tag-go").click()
    expect(page.locator("#message")).to_contain_text("Tagged 1")
    page.goto(server.url)
    sign_out(page)
    open_builder(page, server, "Ravi Kumar")
    page.get_by_role("button", name="Open").first.click()
    expect(page.locator(".rb-chips").first).to_be_visible()
    page.evaluate("""() => {
        const chips = document.querySelector('.rb-chips');
        for (let i = 0; i < 3; i++) {
          const chip = document.createElement('span'); chip.className = 'chip';
          chip.textContent = 'Experience designing and consuming REST APIs at scale with a very long explanation of what is wanted';
          chips.append(chip);
        }
    }""")
    for width in (1572, 1366, 1100, 900):
        page.set_viewport_size({"width": width, "height": 800})
        sticking_out = page.evaluate(
            "() => [...document.querySelectorAll('.chip')].filter(c => c.getBoundingClientRect().right > c.closest('.rb-card').getBoundingClientRect().right + 1).length")
        overflow = page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
        assert (width, sticking_out, overflow) == (width, 0, 0)


def test_only_the_rmg_head_sees_the_setup_tab(page, start_server):
    server = start_server([], resume=True)
    seen = {}
    for name in ("Nancy", "Shadrach", "Ravi Kumar"):
        open_builder(page, server, name)
        seen[name] = page.locator("#tabs .rb-tab").all_inner_texts()
        page.goto(server.url)
        sign_out(page)

    assert "Setup" in seen["Nancy"]
    assert "Setup" not in seen["Shadrach"] and "Requests" in seen["Shadrach"]
    assert seen["Ravi Kumar"] == ["Dashboard", "My requests"]  # the Dashboard is everyone's landing page


def test_a_job_description_can_be_pasted_instead_of_uploaded(page, start_server):
    server = start_server([], resume=True)
    open_builder(page, server, "Shadrach")

    page.locator("#jd-paste-go").click()
    expect(page.locator("#message")).to_contain_text("Paste the job description")  # nothing pasted yet

    page.locator("#jd-title").fill("Quick skills request")
    page.locator("#jd-paste").fill("Java, Spring Boot, Kafka, SQL")
    page.locator("#jd-paste-go").click()

    expect(page.locator("#message")).to_contain_text("Job description added")
    expect(page.locator("#tag-jd option").first).to_have_text("Quick skills request")


def build_as_ravi(page, server):
    """The template is uploaded, Ravi is tagged and has built a draft. Leaves Ravi on his request screen."""
    open_builder(page, server, "Nancy")
    page.get_by_role("button", name="Setup").click()
    page.locator("#tpl-file").set_input_files({"name": "template.docx", "mimeType": "application/octet-stream", "buffer": template_bytes()})
    page.locator("#tpl-go").click()
    expect(page.locator("#message")).to_contain_text("Template uploaded")
    page.goto(server.url)
    sign_out(page)
    open_builder(page, server, "Shadrach")
    page.get_by_label(re.compile("Ravi Kumar")).check()
    page.locator("#tag-go").click()
    expect(page.locator("#message")).to_contain_text("Tagged 1")
    page.goto(server.url)
    sign_out(page)
    open_builder(page, server, "Ravi Kumar")
    page.get_by_role("button", name="Open").first.click()
    page.locator("#resume-file").set_input_files({"name": "cv.txt", "mimeType": "text/plain", "buffer": b"Ravi"})
    page.locator("#upload-resume").click()
    page.locator("#build").click()
    expect(page.locator("#skills-section")).to_be_visible()


def test_the_associate_can_add_edit_and_remove_skills_and_the_score_follows(page, start_server):
    server = start_server([], resume=True)
    build_as_ravi(page, server)
    score = page.locator("#coverage h3")
    expect(score).to_contain_text("60%")  # the demo job wants five skills; the sample resume shows three of them

    # add a skill the job wants: it is marked as theirs and the score goes up
    page.locator("#skills-section .skill-add").first.click()
    page.get_by_label("New skill").fill("Spring Boot")
    page.get_by_label("New skill").press("Enter")
    expect(page.locator("#skills-section .skill-chip", has_text="Spring Boot")).to_contain_text("added by you")
    expect(score).to_contain_text("80%")

    # edit it: click the skill, change the text
    page.locator("#skills-section .skill-edit", has_text="Spring Boot").click()
    box = page.get_by_label("Skill", exact=True)
    box.fill("Spring Boot 3")
    box.press("Enter")
    expect(page.locator("#skills-section .skill-chip", has_text="Spring Boot 3")).to_be_visible()

    # remove it again: the chip goes and the score drops back
    page.get_by_label("Remove skill Spring Boot 3").click()
    expect(page.locator("#skills-section .skill-chip", has_text="Spring Boot")).to_have_count(0)
    expect(score).to_contain_text("60%")

    # a whole new group
    page.locator("#skills-section .skill-new-group").click()
    page.get_by_label("Group name").fill("Infrastructure")
    page.get_by_label("First skill").fill("Ansible")
    page.locator("#skills-section .new-group .skill-save").click()
    expect(page.locator("#skills-section .rb-skillgroup", has_text="Infrastructure:")).to_contain_text("Ansible")

    # a duplicate gets a clear message
    page.locator("#skills-section .skill-add").first.click()
    page.get_by_label("New skill").fill("java")
    page.get_by_label("New skill").press("Enter")
    expect(page.locator("#message")).to_contain_text("already listed")
    assert [e for e in page.console_errors if "422" not in e] == []


def test_the_lead_sees_the_skills_the_associate_added_marked_as_the_associates(page, start_server):
    server = start_server([], resume=True)
    build_as_ravi(page, server)
    page.locator("#skills-section .skill-add").first.click()
    page.get_by_label("New skill").fill("Terraform")
    page.get_by_label("New skill").press("Enter")
    expect(page.locator("#changes")).to_contain_text("Skill 'Terraform'")
    page.locator("#submit").click()
    expect(page.locator("#message")).to_contain_text("Submitted")
    page.goto(server.url)
    sign_out(page)

    open_builder(page, server, "Veera")
    page.get_by_role("button", name="Open").click()

    expect(page.locator("#skills-section .skill-chip", has_text="Terraform")).to_contain_text("added by the associate")
    expect(page.locator("#skills-section .skill-edit").first).to_be_visible()  # the Lead may edit a resume that is waiting for review


def test_one_prominent_score_follows_every_change_and_says_how_far_it_moved(page, start_server):
    server = start_server([], resume=True)
    build_as_ravi(page, server)
    score = page.locator("#score")
    expect(score).to_contain_text("60%")
    expect(score).to_contain_text("3 of 5 required skills")
    assert page.locator("#score .delta").count() == 0  # nothing has changed since the draft was built

    page.locator("#skills-section .skill-add").first.click()
    page.get_by_label("New skill").fill("Spring Boot")
    page.get_by_label("New skill").press("Enter")
    expect(score).to_contain_text("80%")
    expect(score).to_contain_text("4 of 5 required skills")
    expect(score.locator(".delta")).to_have_text("+20 pts")

    page.get_by_label("Remove skill Spring Boot").click()
    expect(score).to_contain_text("60%")
    expect(score.locator(".delta")).to_have_text("-20 pts")

    page.locator("#skills-section .skill-edit").first.click()
    box = page.get_by_label("Skill", exact=True)
    box.fill("Python 3")
    box.press("Enter")
    expect(score.locator(".delta")).to_have_text("no change")  # a change that does not touch the job's skills


def test_each_change_can_be_matched_to_its_line_in_the_resume(page, start_server):
    server = start_server([], resume=True)
    build_as_ravi(page, server)
    page.locator("#resume .rb-project .edit").first.click()
    page.get_by_label("New wording").fill("Wrote the Java services for payments.")
    page.locator(".save-edit").click()

    entry = page.locator("#changes .entry.linked", has_text="Wrote the Java services for payments.")
    expect(entry).to_be_visible()
    path = entry.get_attribute("data-path")
    line = page.locator(f'#resume [data-path="{path}"]')

    entry.hover()
    expect(line).to_have_class(re.compile("rb-linked"))  # hovering the change highlights its line
    entry.get_by_role("button", name="Show in resume").click()
    expect(line).to_have_class(re.compile("rb-flash"))  # and the button flashes it
    line.hover()
    expect(entry).to_have_class(re.compile("rb-linked"))  # hovering the line highlights its change

    page.locator("#resume .rb-project .remove").last.click()  # something removed has no line to point at
    gone = page.locator("#changes .entry", has_text="No longer in the resume")
    expect(gone.first).to_be_visible()
    assert gone.first.get_by_role("button", name="Show in resume").count() == 0


def test_a_tab_clicked_while_the_first_screen_is_still_loading_is_not_lost(page, start_server):
    """A click on a tab while the page was loading used to be thrown away, leaving the person on the wrong tab. The
    click is now remembered and applied when loading finishes."""
    server = start_server([], resume=True)
    sign_in(page, server, "Nancy")
    page.locator('[data-app="rmg"]').click()  # the portal shows one card per app

    page.get_by_role("button", name="Setup").click()  # clicked straight away, while the board is still loading

    expect(page.locator("#tpl-file")).to_be_visible()
    expect(page.locator("#tabs .rb-tab[aria-current='page']")).to_have_text("Setup")


def test_removing_a_listed_skill_moves_the_listed_figure_even_when_the_resume_text_still_shows_the_skill(page, start_server):
    """A person removed every skill from the Skills section and the score stayed at 100%, because the resume text still
    proved each skill. The score now also says how many required skills are listed in the Skills section itself."""
    server = start_server([], resume=True)
    build_as_ravi(page, server)
    score, listed = page.locator("#score"), page.locator("#score-listed")
    expect(score).to_contain_text("60%")
    expect(listed).to_have_text("2 of 5 listed in Skills")  # Java and Kafka are in the Skills section

    page.get_by_label("Remove skill Java", exact=True).click()

    expect(listed).to_contain_text("1 of 5 listed in Skills")
    expect(listed).to_contain_text("-1")
    expect(score).to_contain_text("60%")  # "Wrote Java services" still proves Java, so the main score is unchanged

    page.locator("#skills-section .skill-add").first.click()
    page.get_by_label("New skill").fill("Spring Boot")
    page.get_by_label("New skill").press("Enter")

    expect(listed).to_contain_text("2 of 5 listed in Skills")
    expect(listed).to_contain_text("+1")
    expect(score).to_contain_text("80%")


def test_the_content_uses_the_full_width_of_the_page_at_every_screen_size(page, start_server):
    """On a wide screen the content stopped at 1500 pixels and floated in the middle, with a wide empty margin on each
    side while the top bar used the whole width. The content now reaches the same edges as the top bar."""
    server = start_server([], resume=True)
    build_as_ravi(page, server)

    for width in (2560, 1873, 1440, 1280, 1100, 900):
        page.set_viewport_size({"width": width, "height": 900})
        page.wait_for_timeout(250)
        edges = page.evaluate("""() => {
            const header = document.querySelector('.rb-head').getBoundingClientRect();
            const grid = document.querySelector('.rb-work').getBoundingClientRect();
            return { left: Math.round(grid.left), right: Math.round(window.innerWidth - grid.right),
                     headerPad: Math.round(header.left), overflow: document.documentElement.scrollWidth - window.innerWidth };
        }""")
        assert edges["left"] <= 40 and edges["right"] <= 40, (width, edges)  # the same small margin as the top bar
        assert edges["overflow"] == 0, (width, edges)


def test_the_three_columns_share_a_wide_screen_instead_of_leaving_the_middle_cramped(page, start_server):
    server = start_server([], resume=True)
    build_as_ravi(page, server)
    page.set_viewport_size({"width": 1873, "height": 900})
    page.wait_for_timeout(250)

    widths = page.evaluate("() => [...document.querySelector('.rb-work').children].map(c => Math.round(c.getBoundingClientRect().width))")

    left, middle, right = widths
    assert middle > left and middle > right  # the resume itself gets the most room
    assert left >= 300 and right >= 340  # and the side panels use the extra width too


def test_the_app_is_drawn_smaller_and_still_fills_the_screen(page, start_server):
    """The whole app is drawn at 72% of its design size, and screen-height units are corrected so nothing ends up short."""
    server = start_server([], resume=True)
    page.set_viewport_size({"width": 1600, "height": 800})

    sign_in(page, server, "Ravi Kumar")
    page.locator('[data-app="hr"]').click()  # past the portal, into the chat

    assert page.evaluate("getComputedStyle(document.documentElement).zoom") == "0.72"
    chat = page.locator("#chat-screen").bounding_box()
    assert abs(chat["height"] - 800) <= 2 and abs(chat["width"] - 1600) <= 2  # as big as the window, not 75% of it
    assert page.evaluate("parseFloat(getComputedStyle(document.body).fontSize)") == 16  # the design size is unchanged; the zoom does the scaling


def test_the_job_description_can_be_previewed_from_the_board_and_from_the_associates_request(page, start_server):
    server = start_server([], resume=True)
    open_builder(page, server, "Shadrach")

    page.locator("#board-jd-preview").click()
    expect(page.locator("#jd-preview")).to_be_visible()
    expect(page.locator("#jd-preview-title")).to_contain_text("Senior Java Developer")
    expect(page.locator("#jd-preview-body")).to_contain_text("Must have")
    expect(page.locator("#jd-preview-body .chip").first).to_be_visible()
    page.locator("#jd-preview-close").click()
    expect(page.locator("#jd-preview")).to_be_hidden()

    page.get_by_label(re.compile("Ravi Kumar")).check()
    page.locator("#tag-go").click()
    expect(page.locator("#message")).to_contain_text("Tagged 1")
    page.goto(server.url)
    sign_out(page)
    open_builder(page, server, "Ravi Kumar")
    page.get_by_role("button", name="Open").first.click()
    page.locator("#preview-jd").click()
    expect(page.locator("#jd-preview-body")).to_contain_text("Must have")
    page.keyboard.press("Escape")
    expect(page.locator("#jd-preview")).to_be_hidden()
    assert page.console_errors == []


def test_a_pasted_job_description_previews_with_its_own_text(page, start_server):
    server = start_server([], resume=True)
    open_builder(page, server, "Shadrach")
    page.locator("#jd-title").fill("Quick skills request")
    page.locator("#jd-paste").fill("Java, Spring Boot, Kafka, SQL")
    page.locator("#jd-paste-go").click()
    expect(page.locator("#tag-jd option").first).to_have_text("Quick skills request")

    page.locator("#board-jd-preview").click()

    expect(page.locator("#jd-preview-title")).to_have_text("Quick skills request")
    expect(page.locator("#jd-preview-text")).to_contain_text("Java, Spring Boot, Kafka, SQL")


def test_the_role_choice_is_hidden_for_a_single_role_job_description_and_shown_for_several(page, start_server):
    server = start_server([], resume=True)
    open_builder(page, server, "Shadrach")
    expect(page.locator("#tag-role-field")).to_be_hidden()  # the demo job description has one role

    page.locator("#jd-file").set_input_files({"name": "jd.txt", "mimeType": "text/plain", "buffer": b"Two roles are described in this one."})
    page.locator("#jd-go").click()
    expect(page.locator("#message")).to_contain_text("Job description added")

    expect(page.locator("#tag-role-field")).to_be_visible()  # the fake reader finds two roles in a file
    expect(page.locator("#tag-role option")).to_have_count(2)


def test_the_associate_can_add_dates_to_a_project_that_has_none(page, start_server):
    server = start_server([], resume=True)
    build_as_ravi(page, server)

    expect(page.locator("#resume .rb-project .add-dates").first).to_be_visible()  # the sample resume gives no project dates
    page.locator("#resume .rb-project .add-dates").first.click()
    page.get_by_label("Project dates").fill("Jan 2022 – Mar 2023")
    page.locator(".save-dates").click()

    expect(page.locator("#resume .rb-project .rb-dates").first).to_contain_text("Jan 2022 – Mar 2023")
    expect(page.locator("#resume .rb-project .rb-dates .badge").first).to_contain_text("added by you")
    expect(page.locator("#resume .rb-project .add-dates")).to_have_count(1)  # only the other project still offers it
    assert page.console_errors == []


def test_the_associate_can_add_and_remove_a_certification_and_it_is_marked_as_theirs(page, start_server):
    server = start_server([], resume=True)
    build_as_ravi(page, server)

    expect(page.locator("#certifications-section")).to_contain_text("None listed")
    page.locator("#certifications-section .add-certification").click()
    page.get_by_label("Certification", exact=True).fill("AWS Certified Developer")
    page.locator(".save-certification").click()

    expect(page.locator("#certifications-section .rb-bullet").first).to_contain_text("AWS Certified Developer")
    expect(page.locator("#certifications-section .badge").first).to_contain_text("added by you")

    page.locator("#certifications-section .rb-bullet .remove").first.click()
    expect(page.locator("#certifications-section")).to_contain_text("None listed")
    assert page.console_errors == []


def test_the_lead_can_edit_the_resume_and_send_it_back_with_a_note_and_the_associate_sees_what_changed(page, start_server):
    server = start_server([], resume=True)
    build_as_ravi(page, server)
    page.locator("#submit").click()
    expect(page.locator("#message")).to_contain_text("Submitted")
    page.goto(server.url)
    sign_out(page)

    open_builder(page, server, "Veera")
    page.get_by_role("button", name="Open").click()
    expect(page.locator("#chat")).to_have_count(0)  # the assistant is the associate's, not a reviewer's
    page.locator("#certifications-section .add-certification").click()
    page.get_by_label("Certification", exact=True).fill("Scrum Master")
    page.locator(".save-certification").click()
    expect(page.locator("#certifications-section .badge").first).to_contain_text("added by Veera")
    page.locator("#decision-note").fill("I added Scrum Master; please check your project dates")
    page.locator("#send-back").click()
    expect(page.locator("#message")).to_contain_text("Sent back")
    page.goto(server.url)
    sign_out(page)

    open_builder(page, server, "Ravi Kumar")
    page.get_by_role("button", name="Open").first.click()
    expect(page.locator("#decision-note-shown")).to_contain_text("please check your project dates")
    expect(page.locator("#certifications-section .badge").first).to_contain_text("added by Veera")
    assert page.console_errors == []


def test_rmg_has_a_review_tab_and_can_approve_a_submitted_resume(page, start_server):
    server = start_server([], resume=True)
    build_as_ravi(page, server)
    page.locator("#submit").click()
    expect(page.locator("#message")).to_contain_text("Submitted")
    page.goto(server.url)
    sign_out(page)

    open_builder(page, server, "Shadrach")
    page.get_by_role("button", name="Review", exact=True).click()
    expect(page.locator("#view")).to_contain_text("1 waiting for your decision")
    page.get_by_role("button", name="Open").click()
    page.locator("#approve").click()

    expect(page.locator("#message")).to_contain_text("Approved")
    assert page.console_errors == []


def test_a_person_with_no_lead_can_be_tagged_and_rmg_reviews_their_resume(page, start_server):
    server = start_server([], resume=True)
    open_builder(page, server, "Shadrach")

    page.get_by_label(re.compile("Sanjay Patel")).check()
    page.locator("#tag-go").click()
    expect(page.locator("#message")).to_contain_text("Tagged 1")
    page.get_by_role("button", name="Open").click()

    expect(page.locator(".rb-titleblock")).to_contain_text("Reviewed by the RMG team")
    assert page.console_errors == []


def test_a_skill_the_job_wants_but_the_resume_lacks_is_a_suggestion_one_click_adds_as_the_associates_own(page, start_server):
    server = start_server([], resume=True)
    build_as_ravi(page, server)

    suggestion = page.locator("#coverage button.suggest", has_text="Kubernetes")
    expect(suggestion).to_be_visible()  # the job wants it and the sample resume does not have it
    expect(page.locator("#skills-section .skill-chip", has_text="Kubernetes")).to_have_count(0)  # nothing is claimed until the click
    suggestion.click()

    expect(page.locator("#skills-section .skill-chip", has_text="Kubernetes")).to_contain_text("added by you")
    expect(page.locator("#coverage button.suggest", has_text="Kubernetes")).to_have_count(0)  # no longer missing
    assert page.console_errors == []


def test_the_download_message_never_says_undefined_whatever_the_layout_check_reported(page, start_server):
    server = start_server([], resume=True)
    build_as_ravi(page, server)

    with page.expect_download():
        page.locator("#download").click()

    expect(page.locator("#message")).to_contain_text("Downloaded a DRAFT copy")
    expect(page.locator("#message")).not_to_contain_text("undefined")


def test_the_associate_chooses_polish_or_deep_match_before_building(page, start_server):
    server = start_server([], resume=True)
    build_as_ravi(page, server)  # leaves Ravi on a request that is already built with the default

    expect(page.locator("#built-with")).to_have_text("Built with: Polish")
    expect(page.locator(".rb-mode")).to_have_count(2)
    expect(page.locator("#mode-polish")).to_be_checked()  # polish is the default

    page.locator("label[for=mode-deep]").click()
    expect(page.locator("#mode-deep")).to_be_checked()
    expect(page.locator(".rb-mode").nth(1)).to_contain_text("Skills you do not have are never added")
    page.locator("#build").click()

    # This test server has no deep drafter, so it says so and polishes instead: a build never fails because of the mode.
    expect(page.locator("#message")).to_contain_text("Your tailored draft is ready")
    expect(page.locator("#built-with")).to_have_text("Built with: Polish")
    expect(page.locator(".rb-warn").first).to_contain_text("Deep match is not available")
