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
