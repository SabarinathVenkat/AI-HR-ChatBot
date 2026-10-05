"""The web UI in a real browser. The agent is scripted, so no API calls are made."""
import re

from langchain_core.messages import AIMessage
from playwright.sync_api import expect

from tests.support import tool_call


def sign_in(page, server, name="Ravi Kumar"):
    page.goto(server.url)
    page.get_by_role("button", name=re.compile(rf"^{name}")).click()
    page.get_by_role("button", name="Sign in").click()
    expect(page.locator("#chat-screen")).to_be_visible()


def ask(page, text):
    page.locator("#composer-input").fill(text)
    page.locator("#composer-input").press("Enter")


def test_the_login_page_lists_the_demo_accounts_and_fills_the_form(page, start_server):
    server = start_server([])
    page.goto(server.url)

    expect(page.locator("#login-screen")).to_be_visible()
    expect(page.locator("#demo-list button")).to_have_count(10)
    page.get_by_role("button", name=re.compile(r"^Ravi Kumar")).click()

    assert page.locator("#login-email").input_value() == "ravi.kumar@example-ideas2it.invalid"
    assert page.locator("#login-password").input_value() == "Welcome@123"


def test_signing_in_shows_the_chat_the_user_and_their_balances(page, start_server):
    server = start_server([])
    sign_in(page, server)

    expect(page.locator("#who")).to_have_text("Ravi Kumar · Employee")
    expect(page.locator(".msg.assistant").first).to_contain_text("Hi Ravi!")
    expect(page.locator("#balances .balance")).to_have_count(3)
    expect(page.locator("#balances .balance").first.locator(".num")).to_have_text("12")
    expect(page.locator("#requests .request")).to_have_count(1)
    expect(page.locator(".banner")).to_contain_text("Sample policies")
    assert page.console_errors == []


def test_a_wrong_password_shows_an_error_and_stays_on_the_login_page(page, start_server):
    server = start_server([])
    page.goto(server.url)
    page.locator("#login-email").fill("ravi.kumar@example-ideas2it.invalid")
    page.locator("#login-password").fill("wrong")
    page.get_by_role("button", name="Sign in").click()

    expect(page.locator("#login-error")).to_have_text("Invalid email or password.")
    expect(page.locator("#chat-screen")).to_be_hidden()


def test_an_answer_streams_in_with_its_steps_and_meta(page, start_server):
    server = start_server(
        [tool_call("get_leave_balance"), AIMessage("You have 12 days of annual leave available.")],
        intent="data_question",
    )
    sign_in(page, server)

    ask(page, "How many leave days do I have?")

    expect(page.locator(".msg.user").last).to_have_text("How many leave days do I have?")
    answer = page.locator(".msg.assistant").last
    expect(answer.locator(".bubble")).to_contain_text("You have 12 days of annual leave available.")
    expect(answer.locator("details.steps summary")).to_have_text("How I got this (1 step)")
    expect(answer.locator(".meta")).to_contain_text("Your leave data")
    expect(page.locator("#starters")).to_be_hidden()
    assert page.console_errors == []


def test_citations_become_chips_that_open_the_policy_text(page, start_server):
    server = start_server(
        [tool_call("search_policy", {"query": "notice period after confirmation"}),
         AIMessage("The notice period is 60 days for individual contributors [POL-05 §3.1].")],
        intent="policy_question",
    )
    sign_in(page, server)

    ask(page, "What is the notice period?")
    chip = page.locator(".msg.assistant").last.locator("button.chip")
    expect(chip).to_have_text("POL-05 §3.1")
    chip.click()

    dialog = page.locator("#policy-dialog")
    expect(dialog).to_be_visible()
    expect(dialog.locator("#policy-title")).to_contain_text("Notice Period")
    expect(dialog.locator("#policy-text")).to_contain_text("60 days")
    expect(dialog.locator("#policy-meta")).to_contain_text("Sample policy")


def test_a_leave_request_shows_a_confirm_card_that_submits_when_confirmed(page, start_server):
    server = start_server(
        [tool_call("prepare_leave_request",
                   {"leave_type": "AL", "start_date": "2026-11-02", "end_date": "2026-11-06"}),
         AIMessage("Your request for 5 days of AL from 2026-11-02 to 2026-11-06 is ready. "
                   "It has not been submitted: please confirm.")],
        intent="leave_request",
    )
    sign_in(page, server)

    ask(page, "Apply annual leave 2 to 6 November")
    card = page.locator(".confirm-card")
    expect(card).to_be_visible()
    expect(card).to_contain_text("Annual leave")
    expect(card).to_contain_text("5")
    card.get_by_role("button", name="Confirm and submit").click()

    expect(card.locator(".confirm-status")).to_contain_text("Submitted")
    expect(page.locator("#requests .request")).to_have_count(2)
    expect(page.locator("#requests")).to_contain_text("pending")


def test_cancelling_the_confirm_card_submits_nothing(page, start_server):
    server = start_server(
        [tool_call("prepare_leave_request",
                   {"leave_type": "AL", "start_date": "2026-11-02", "end_date": "2026-11-06"}),
         AIMessage("Your request for 5 days of AL is ready. It has not been submitted: please confirm.")],
        intent="leave_request",
    )
    sign_in(page, server)
    ask(page, "Apply annual leave 2 to 6 November")

    page.locator(".confirm-card").get_by_role("button", name="Cancel").click()

    expect(page.locator(".confirm-status")).to_contain_text("Nothing was submitted")
    expect(page.locator("#requests .request")).to_have_count(1)


def test_an_employee_can_cancel_a_pending_request_from_the_panel(page, start_server):
    server = start_server([])
    sign_in(page, server, "Divya Menon")
    page.on("dialog", lambda dialog: dialog.accept())

    page.get_by_role("button", name="Cancel request").click()

    expect(page.locator("#requests .pill").first).to_have_text("cancelled")


def test_a_manager_sees_and_approves_pending_requests(page, start_server):
    server = start_server([])
    sign_in(page, server, "Arjun Rao")

    expect(page.locator("#approvals-section")).to_be_visible()
    expect(page.locator("#approvals .request")).to_have_count(2)  # Divya and Sanjay
    page.locator("#approvals .request").first.get_by_role("button", name="Approve").click()

    expect(page.locator("#approvals .request")).to_have_count(1)


def test_employees_do_not_see_the_manager_panel(page, start_server):
    server = start_server([])
    sign_in(page, server)

    expect(page.locator("#approvals-section")).to_be_hidden()


def test_markup_in_answers_and_messages_is_shown_as_text_not_run(page, start_server):
    # No digits in the payloads: the answer verifier would (rightly) reject unexplained figures.
    evil = '<img src=x onerror="window.__pwned=true"> <script>window.__pwned=true</script> **bold**'
    server = start_server([AIMessage(evil)])
    sign_in(page, server)

    ask(page, "<b>hello</b> <img src=x onerror=window.__pwned=true>")

    expect(page.locator(".msg.user .bubble").last).to_have_text("<b>hello</b> <img src=x onerror=window.__pwned=true>")
    bubble = page.locator(".msg.assistant").last.locator(".bubble")
    expect(bubble).to_contain_text("<img src=x")
    assert page.locator(".msg.assistant").last.locator("img, script").count() == 0
    assert page.evaluate("window.__pwned") is None
    expect(bubble.locator("strong")).to_have_text("bold")


def test_enter_sends_and_shift_enter_adds_a_line(page, start_server):
    server = start_server([AIMessage("Hi there!")])
    sign_in(page, server)
    box = page.locator("#composer-input")

    box.fill("first")
    box.press("Shift+Enter")
    box.type("second")
    assert box.input_value() == "first\nsecond"
    assert page.locator(".msg.user").count() == 0
    box.press("Enter")

    expect(page.locator(".msg.user").last).to_have_text("first\nsecond")


def test_new_chat_clears_the_conversation_and_restores_the_starters(page, start_server):
    server = start_server([AIMessage("Hi there!")])
    sign_in(page, server)
    ask(page, "hello")
    expect(page.locator(".msg.assistant").last).to_contain_text("Hi there!")

    page.get_by_role("button", name="New chat").click()

    expect(page.locator(".msg.user")).to_have_count(0)
    expect(page.locator("#starters")).to_be_visible()
    expect(page.locator("#starters button").first).to_be_visible()


def test_a_starter_question_is_sent_when_clicked(page, start_server):
    server = start_server([tool_call("get_leave_balance"), AIMessage("You have 12 days of annual leave.")],
                          intent="data_question")
    sign_in(page, server)

    page.get_by_role("button", name="How many annual leave days do I have left?").click()

    expect(page.locator(".msg.user").last).to_have_text("How many annual leave days do I have left?")
    expect(page.locator(".msg.assistant").last).to_contain_text("12 days")


def test_a_model_failure_is_shown_as_a_friendly_error(page, start_server):
    server = start_server([])  # the scripted model runs out and raises
    sign_in(page, server)

    ask(page, "hello")

    bubble = page.locator(".msg.assistant").last.locator(".bubble")
    expect(bubble).to_contain_text("try again")
    expect(bubble).to_have_attribute("role", "alert")


def test_the_rate_limit_is_explained_to_the_user(page, start_server):
    server = start_server([AIMessage("One.")], rate_limit=1)
    sign_in(page, server)
    ask(page, "first")
    expect(page.locator(".msg.assistant").last).to_contain_text("One.")

    ask(page, "second")

    expect(page.locator(".msg.assistant").last).to_contain_text("sending messages quickly")


def test_signing_out_returns_to_the_login_page_and_forgets_the_session(page, start_server):
    server = start_server([])
    sign_in(page, server)

    page.get_by_role("button", name="Sign out").click()

    expect(page.locator("#login-screen")).to_be_visible()
    assert page.evaluate("sessionStorage.getItem('hr_token')") is None
    page.reload()
    expect(page.locator("#login-screen")).to_be_visible()


def test_reloading_keeps_the_user_signed_in_for_the_tab(page, start_server):
    server = start_server([])
    sign_in(page, server)

    page.reload()

    expect(page.locator("#chat-screen")).to_be_visible()
    expect(page.locator("#who")).to_contain_text("Ravi Kumar")


def test_an_expired_session_sends_the_user_back_to_sign_in(page, start_server):
    server = start_server([AIMessage("Hi!")])
    sign_in(page, server)
    # Let the side panel finish loading first, so no background request is in flight when the
    # session expires (otherwise the page could sign out before the message is typed).
    expect(page.locator("#balances .balance")).to_have_count(3)
    expect(page.locator("#requests .request")).to_have_count(1)
    server.clock.advance(minutes=61)

    ask(page, "hello")

    expect(page.locator("#login-screen")).to_be_visible()
    expect(page.locator("#login-error")).to_contain_text("session has ended")


def test_the_page_is_usable_by_keyboard_and_screen_reader_basics(page, start_server):
    server = start_server([])
    sign_in(page, server)

    assert page.locator("#messages").get_attribute("role") == "log"
    assert page.locator("#messages").get_attribute("aria-live") == "polite"
    expect(page.get_by_label("Message")).to_be_visible()
    expect(page.locator("html")).to_have_attribute("lang", "en")
    expect(page.locator("#composer-input")).to_be_focused()


def test_the_layout_fits_a_phone_without_sideways_scrolling(browser, start_server):
    server = start_server([])
    context = browser.new_context(viewport={"width": 390, "height": 800})
    page = context.new_page()
    sign_in(page, server)

    overflow = page.evaluate("document.scrollingElement.scrollWidth - document.scrollingElement.clientWidth")

    assert overflow <= 0
    expect(page.locator("#composer-input")).to_be_visible()
    context.close()
