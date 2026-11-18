"""Fixtures for browser tests: a live server on a scripted agent, and a Chromium browser."""
import socket
import threading
import time
from contextlib import closing
from pathlib import Path

import pytest
import uvicorn
from langgraph.checkpoint.memory import MemorySaver
from playwright.sync_api import expect, sync_playwright

from app.agent.graph import AgentDeps, build_agent
from app.agent.router import RouteDecision
from app.api.main import create_app
from app.bootstrap import bootstrap
from app.config import Settings
from app.db.connection import connect
from app.platform_admin import set_modules
from app.rag.search import Retrieval
from app.rmg.agent import build_rmg_agent
from app.rmg.resume.chat import EditCommand
from app.rmg.resume.draft import TailoringSettings
from app.rmg.resume.filestore import FileStore
from app.rmg.resume.pipeline import PipelineDeps
from app.rmg.resume.service import ResumeEngine
from tests.integration.conftest import SECRET, FakeClock, clock  # noqa: F401
from tests.support import BagOfWordsEmbedder, FixedRouter, ScriptedChatModel
from tests.unit.resume_fakes import FakeJDExtractor, FakeResumeExtractor, keep_as_written

POLICIES = Path(__file__).resolve().parents[2] / "data" / "policies"

# Browser tests wait for the real server and, in the journey tests, for several people to sign in in turn. Five seconds
# was enough on a quiet machine and produced rare false failures on a busy one, so every expectation waits longer.
expect.set_options(timeout=15_000)


class LiveServer:
    def __init__(self, url: str, model: ScriptedChatModel, router: FixedRouter, clock: FakeClock,  # noqa: F811
                 rmg_model: ScriptedChatModel | None = None) -> None:
        self.url = url
        self.model = model
        self.router = router
        self.clock = clock
        self.rmg_model = rmg_model


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
    with closing(connect(str(db_path))) as setup:  # a new platform starts with HR off; these tests need both modules on
        set_modules(setup, {"hr": True, "rmg": True}, by=1, when="2026-10-02T09:00:00")

    def start(responses, intent="chitchat", rate_limit=30, rmg_responses=None, resume=False) -> LiveServer:
        model = ScriptedChatModel(responses=list(responses))
        router = FixedRouter(RouteDecision(intent=intent))
        agent = build_agent(AgentDeps(model, router), MemorySaver())
        rmg_model = ScriptedChatModel(responses=list(rmg_responses)) if rmg_responses is not None else None
        engine = ResumeEngine(
            PipelineDeps(FakeResumeExtractor(), FakeJDExtractor(), keep_as_written, TailoringSettings()),
            lambda message, resume_: EditCommand(action="explain"),
        ) if resume else None
        app = create_app(
            Settings(jwt_secret=SECRET, demo_mode=True, chat_rate_limit_per_minute=rate_limit),
            connection=lambda: closing(connect(str(db_path))),
            clock=clock,
            agent=agent,
            retrieval=Retrieval(BagOfWordsEmbedder(), 0.2),
            rmg_agent=build_rmg_agent(rmg_model, MemorySaver()) if rmg_model else None,
            resume_engine=engine,
            resume_files=FileStore(tmp_path / f"files{len(started)}") if resume else None,
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
        return LiveServer(f"http://127.0.0.1:{port}", model, router, clock, rmg_model)

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
