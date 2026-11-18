"""The platform admin in a real browser: sign in as admin, choose the modules, and see what other people then get."""
import re

from playwright.sync_api import expect


def sign_in_as(page, server, who, password):
    page.goto(server.url)
    page.locator("#login-email").fill(who)
    page.locator("#login-password").fill(password)
    page.get_by_role("button", name="Sign in").click()


def choose_modules(page, server, hr, rmg):
    sign_in_as(page, server, "admin", "admin123")
    expect(page).to_have_url(re.compile(r"/admin\.html$"))
    expect(page.locator("#who")).to_have_text("Platform Admin")
    expect(page.locator("#module-hr")).to_be_checked()  # both are on until the admin chooses
    page.locator("#module-hr").set_checked(hr)
    page.locator("#module-rmg").set_checked(rmg)
    page.get_by_role("button", name="Save").click()
    expect(page.locator("#admin-message")).to_contain_text("Saved")
    page.get_by_role("button", name="Sign out").click()
    expect(page.locator("#login-screen")).to_be_visible()


def test_the_admin_signs_in_with_just_admin_and_lands_on_the_admin_page(page, start_server):
    server = start_server([], rmg_responses=[], resume=True)

    sign_in_as(page, server, "admin", "admin123")

    expect(page).to_have_url(re.compile(r"/admin\.html$"))
    expect(page.locator("#module-hr")).to_be_checked()
    expect(page.locator("#module-rmg")).to_be_checked()


def test_the_admin_cannot_save_with_no_module_ticked(page, start_server):
    server = start_server([], rmg_responses=[], resume=True)
    sign_in_as(page, server, "admin", "admin123")
    expect(page.locator("#module-hr")).to_be_checked()

    page.locator("#module-hr").uncheck()
    page.locator("#module-rmg").uncheck()
    page.get_by_role("button", name="Save").click()

    expect(page.locator("#admin-message")).to_contain_text("at least one")


def test_with_only_rmg_ticked_people_see_the_rmg_module_and_no_hr(page, start_server):
    server = start_server([], rmg_responses=[], resume=True)
    choose_modules(page, server, hr=False, rmg=True)

    sign_in_as(page, server, "ravi.kumar@example-ideas2it.invalid", "Welcome@123")

    expect(page.locator("#chat-screen")).to_be_visible()
    expect(page.locator("#mode-toggle")).to_be_hidden()
    expect(page.locator("#leave-panel")).to_be_hidden()
    expect(page.locator("#chat-title")).to_have_text("Resource management")
    expect(page.locator("#resume-link")).to_be_visible()


def test_with_only_hr_ticked_people_see_the_hr_module_and_no_rmg(page, start_server):
    server = start_server([], rmg_responses=[], resume=True)
    choose_modules(page, server, hr=True, rmg=False)

    sign_in_as(page, server, "ravi.kumar@example-ideas2it.invalid", "Welcome@123")

    expect(page.locator("#chat-screen")).to_be_visible()
    expect(page.locator("#mode-toggle")).to_be_hidden()
    expect(page.locator("#leave-panel")).to_be_visible()
    expect(page.locator("#balances .balance")).to_have_count(3)
    expect(page.locator("#resume-link")).to_be_hidden()


def test_with_both_ticked_people_see_both_modules(page, start_server):
    server = start_server([], rmg_responses=[], resume=True)
    choose_modules(page, server, hr=True, rmg=True)

    sign_in_as(page, server, "ravi.kumar@example-ideas2it.invalid", "Welcome@123")

    expect(page.locator("#chat-screen")).to_be_visible()
    expect(page.locator("#mode-toggle")).to_be_visible()
    expect(page.locator("#leave-panel")).to_be_visible()
    expect(page.locator("#resume-link")).to_be_visible()
