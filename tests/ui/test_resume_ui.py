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
    expect(page.locator("#chat-screen")).to_be_visible()


def open_builder(page, server, name):
    sign_in(page, server, name)
    page.get_by_role("link", name="Resume builder").click()
    expect(page.locator("#who")).to_have_text(name)


def sign_out(page):
    page.locator("#sign-out").click()
    expect(page.locator("#login-screen")).to_be_visible()


def test_the_resume_link_is_hidden_when_the_builder_is_not_configured(page, start_server):
    server = start_server([])

    sign_in(page, server, "Ravi Kumar")

    expect(page.locator("#resume-link")).to_be_hidden()


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

    # RMG tags Ravi (who has a lead) and sees that Sanjay cannot be tagged.
    open_builder(page, server, "Shadrach")
    expect(page.locator("#blocked-people")).to_contain_text("Sanjay Patel")  # no Lead, so not offered for tagging
    expect(page.locator("#tag-people input")).to_have_count(5)  # four older demo associates and Sabari
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
    assert seen["Ravi Kumar"] == ["My requests"]


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


def test_the_lead_sees_the_skills_the_associate_added_marked_as_theirs(page, start_server):
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

    expect(page.locator("#skills-section .skill-chip", has_text="Terraform")).to_contain_text("added by you")
    expect(page.locator("#skills-section .skill-edit")).to_have_count(0)  # the Lead cannot edit the associate's skills


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
    page.get_by_role("link", name="Resume builder").click()

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

    assert page.evaluate("getComputedStyle(document.documentElement).zoom") == "0.72"
    chat = page.locator("#chat-screen").bounding_box()
    assert abs(chat["height"] - 800) <= 2 and abs(chat["width"] - 1600) <= 2  # as big as the window, not 75% of it
    assert page.evaluate("parseFloat(getComputedStyle(document.body).fontSize)") == 16  # the design size is unchanged; the zoom does the scaling
