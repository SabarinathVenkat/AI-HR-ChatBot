"""Fixtures for browser tests: a live server on a scripted agent, and a Chromium browser."""
import socket
import threading
import time
from contextlib import closing
from pathlib import Path

import pytest
import uvicorn
from langgraph.checkpoint.memory import MemorySaver
from playwright.sync_api import sync_playwright

from app.agent.graph import AgentDeps, build_agent
from app.agent.router import RouteDecision
from app.api.main import create_app
from app.bootstrap import bootstrap
from app.config import Settings
from app.db.connection import connect
from app.rag.search import Retrieval
from tests.integration.conftest import SECRET, FakeClock, clock  # noqa: F401
from tests.support import BagOfWordsEmbedder, FixedRouter, ScriptedChatModel

POLICIES = Path(__file__).resolve().parents[2] / "data" / "policies"


class LiveServer:
    def __init__(self, url: str, model: ScriptedChatModel, router: FixedRouter, clock: FakeClock) -> None:  # noqa: F811
        self.url = url
        self.model = model
        self.router = router
        self.clock = clock


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def start_server(tmp_path, clock):  # noqa: F811 (clock is a fixture imported above)
    """Returns a function that starts a server with the given scripted responses and intent.

    Each request opens its own connection to a temporary database file, as in production.
    """
    started: list[tuple[uvicorn.Server, threading.Thread]] = []
    db_path = tmp_path / "ui.db"
    bootstrap(db_path, BagOfWordsEmbedder())

    def start(responses, intent="chitchat", rate_limit=30) -> LiveServer:
        model = ScriptedChatModel(responses=list(responses))
        router = FixedRouter(RouteDecision(intent=intent))
        agent = build_agent(AgentDeps(model, router), MemorySaver())
        app = create_app(
            Settings(jwt_secret=SECRET, demo_mode=True, chat_rate_limit_per_minute=rate_limit),
            connection=lambda: closing(connect(str(db_path))),
            clock=clock,
            agent=agent,
            retrieval=Retrieval(BagOfWordsEmbedder(), 0.2),
        )
        port = _free_port()
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        deadline = time.time() + 10
        while not server.started and time.time() < deadline:
            time.sleep(0.02)
        assert server.started, "test server did not start"
        started.append((server, thread))
        return LiveServer(f"http://127.0.0.1:{port}", model, router, clock)

    yield start
    for server, thread in started:
        server.should_exit = True
        thread.join(timeout=5)


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture
def page(browser):
    context = browser.new_context(viewport={"width": 1280, "height": 860})
    page = context.new_page()
    page.console_errors = []
    page.on("console", lambda msg: page.console_errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda err: page.console_errors.append(str(err)))
    yield page
    context.close()
