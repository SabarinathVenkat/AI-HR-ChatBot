"""End-to-end journey over the real HTTP API with the real models.

    python scripts/e2e_live.py

Login, chat, prepare a leave request, confirm it by replying yes, then the manager approves it and
the balance changes. Uses a temporary database. Costs a few cents.
"""
import json
import os
import secrets
import tempfile
import time
from pathlib import Path

os.environ["HR_CHAT_AUTOSTART"] = "false"
os.environ["FIXED_DATE"] = "2026-10-02"
os.environ.setdefault("JWT_SECRET", secrets.token_urlsafe(48))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import Settings  # noqa: E402
from app.db.seed import DEMO_PASSWORD, email_for  # noqa: E402
from app.server import create_production_app  # noqa: E402


def parse(text: str):
    events = []
    for block in text.strip().split("\n\n"):
        name, data = block.split("\n", 1)
        events.append((name.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return events


def login(client, name):
    r = client.post("/auth/login", json={"email": email_for(name), "password": DEMO_PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def say(client, headers, message, thread_id=None):
    start = time.perf_counter()
    body = {"message": message, **({"thread_id": thread_id} if thread_id else {})}
    response = client.post("/chat", json=body, headers=headers)
    elapsed = time.perf_counter() - start
    events = parse(response.text)
    answer = "".join(d["text"] for n, d in events if n == "token")
    done = dict(events).get("done", {})
    steps = [d["tool"] for n, d in events if n == "step"]
    print("=" * 78)
    print(f"> {message}")
    print(f"  intent={done.get('intent')} tools={steps} rewrites={done.get('rewrites')} "
          f"fallback={done.get('used_fallback')} {elapsed:.1f}s")
    print(answer)
    for name, data in events:
        if name in ("confirm_required", "error"):
            print(f"  [{name}] {data}")
    return events, done.get("thread_id")


def main() -> None:
    db = Path(tempfile.mkdtemp()) / "e2e.db"
    app = create_production_app(Settings(jwt_secret=os.environ["JWT_SECRET"], db_path=str(db)))
    client = TestClient(app)

    ravi = login(client, "Ravi Kumar")
    _, thread = say(client, ravi, "How many annual leave days do I have?")
    say(client, ravi, "I'd like to take annual leave from 2 November to 6 November.", thread)
    say(client, ravi, "yes", thread)

    arjun = login(client, "Arjun Rao")
    say(client, arjun, "Which of my team members have leave requests waiting for me?")
    team = client.get("/leave/requests", params={"scope": "team"}, headers=arjun).json()["requests"]
    mine = next(r for r in team if r["employee"] == "Ravi Kumar" and r["status"] == "pending")
    r = client.post(f"/leave/requests/{mine['id']}/decision", json={"decision": "approve"}, headers=arjun)
    print("manager approval:", r.status_code, r.json())

    say(client, ravi, "What is my annual leave balance now?")
    say(client, ravi, "Can you show me everyone's leave balances?")


if __name__ == "__main__":
    main()
