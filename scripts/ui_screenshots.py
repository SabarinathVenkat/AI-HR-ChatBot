"""Drive the real app (real models) in a browser and save screenshots for review and the deck.

    python scripts/ui_screenshots.py
Uses a temporary database and ANTHROPIC_API_KEY from .env. Costs a few cents.
"""
import os
import secrets
import socket
import tempfile
import threading
import time
from pathlib import Path

os.environ["HR_CHAT_AUTOSTART"] = "false"
os.environ["FIXED_DATE"] = "2026-10-02"
os.environ.setdefault("JWT_SECRET", secrets.token_urlsafe(48))

import uvicorn  # noqa: E402
from playwright.sync_api import expect, sync_playwright  # noqa: E402

from app.config import Settings  # noqa: E402
from app.server import create_production_app  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "docs" / "screenshots"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def sign_in(page, name):
    page.get_by_role("button", name=name).first.click()
    page.get_by_role("button", name="Sign in").click()
    expect(page.locator("#chat-screen")).to_be_visible()


def ask(page, text):
    page.locator("#composer-input").fill(text)
    page.locator("#composer-input").press("Enter")
    # Wait for the answer to finish: the send button re-enables when the stream ends.
    expect(page.locator("#send")).to_be_enabled(timeout=90000)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    db = Path(tempfile.mkdtemp()) / "shots.db"
    app = create_production_app(Settings(jwt_secret=os.environ["JWT_SECRET"], db_path=str(db), demo_mode=True))
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    url = f"http://127.0.0.1:{port}"

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1360, "height": 900})
        page.goto(url)
        expect(page.locator("#demo-list button")).to_have_count(10)
        page.screenshot(path=str(OUT / "01-login.png"))

        sign_in(page, "Ravi Kumar")
        page.wait_for_timeout(600)
        page.screenshot(path=str(OUT / "02-home.png"))

        ask(page, "What is the notice period after I resign?")
        page.screenshot(path=str(OUT / "03-policy-answer.png"))
        page.locator("button.chip").first.click()
        page.wait_for_timeout(500)
        page.screenshot(path=str(OUT / "04-citation.png"))
        page.keyboard.press("Escape")

        ask(page, "I'd like to take annual leave from 2 November to 6 November.")
        page.wait_for_timeout(500)
        page.screenshot(path=str(OUT / "05-confirm-card.png"))
        page.get_by_role("button", name="Confirm and submit").click()
        page.wait_for_timeout(1200)
        page.screenshot(path=str(OUT / "06-submitted.png"))

        manager = browser.new_page(viewport={"width": 1360, "height": 900})
        manager.goto(url)
        sign_in(manager, "Arjun Rao")
        manager.wait_for_timeout(800)
        manager.screenshot(path=str(OUT / "07-manager.png"))

        phone = browser.new_page(viewport={"width": 390, "height": 844})
        phone.goto(url)
        sign_in(phone, "Ravi Kumar")
        phone.wait_for_timeout(600)
        phone.screenshot(path=str(OUT / "08-phone.png"))
        browser.close()
    server.should_exit = True
    print("saved to", OUT)


if __name__ == "__main__":
    main()
