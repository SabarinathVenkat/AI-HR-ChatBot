"""Production entry point:  uvicorn app.server:app

Reads settings from the environment (JWT_SECRET and ANTHROPIC_API_KEY are required; a .env file is
loaded if present). Creates and fills the database on first start.
"""
import logging
import os
import sqlite3
from contextlib import closing
from datetime import date, datetime, time, timezone

from dotenv import load_dotenv
from fastapi import FastAPI
from langgraph.checkpoint.sqlite import SqliteSaver

from app.agent.factory import build_live_agent
from app.api.main import create_app
from app.bootstrap import bootstrap
from app.config import Settings
from app.db.connection import connect
from app.rag.embeddings import FastEmbedder
from app.rag.search import Retrieval

log = logging.getLogger("hr_chat")


def create_production_app(settings: Settings | None = None) -> FastAPI:
    load_dotenv()
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    settings = settings or Settings.from_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")

    embedder = FastEmbedder()
    bootstrap(
        settings.db_path,
        embedder,
        demo_data=os.environ.get("DEMO_DATA", "true").lower() != "false",
        reindex=os.environ.get("REINDEX", "false").lower() == "true",
    )
    embedder.embed(["warm up"])  # load the model now, so the first question is not slow

    checkpoints = sqlite3.connect(settings.db_path, check_same_thread=False)
    agent = build_live_agent(settings, SqliteSaver(checkpoints))
    log.info("HR chat agent ready (models: %s / %s)", settings.answer_model, settings.router_model)
    return create_app(
        settings,
        connection=lambda: closing(connect(settings.db_path)),
        clock=_clock_from_env(),
        agent=agent,
        retrieval=Retrieval(embedder),
    )


def _clock_from_env():
    """FIXED_DATE=2026-10-02 pins 'today' so a demo behaves the same on any day."""
    fixed = os.environ.get("FIXED_DATE")
    if not fixed:
        return None
    pinned = datetime.combine(date.fromisoformat(fixed), time(9, 0), tzinfo=timezone.utc)
    log.warning("FIXED_DATE is set: the app believes today is %s", fixed)
    return lambda: pinned


app = create_production_app() if os.environ.get("HR_CHAT_AUTOSTART", "true") == "true" else None
