"""Timestamp every server-sent event of a real chat turn, to see what the user sees and when.

    python scripts/stream_timing.py "your question"
Uses a temporary database and the live models. Costs a few cents.
"""
import json
import os
import secrets
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

os.environ["HR_CHAT_AUTOSTART"] = "false"
os.environ["FIXED_DATE"] = "2026-10-02"
os.environ.setdefault("JWT_SECRET", secrets.token_urlsafe(48))

import httpx  # noqa: E402
import uvicorn  # noqa: E402

from app.config import Settings  # noqa: E402
from app.db.seed import DEMO_PASSWORD, email_for  # noqa: E402
from app.server import create_production_app  # noqa: E402

QUESTION = (
    "How could I use my annual leave to get the longest break in late December with the fewest "
    "leave days? Please compare a couple of options."
)


def main() -> None:
    question = " ".join(sys.argv[1:]) or QUESTION
    db = Path(tempfile.mkdtemp()) / "t.db"
    app = create_production_app(Settings(jwt_secret=os.environ["JWT_SECRET"], db_path=str(db), demo_mode=True))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)

    base = f"http://127.0.0.1:{port}"
    token = httpx.post(f"{base}/auth/login", json={"email": email_for("Ravi Kumar"), "password": DEMO_PASSWORD}).json()["access_token"]
    started = time.perf_counter()
    answer = ""
    with httpx.stream("POST", f"{base}/chat", json={"message": question},
                      headers={"Authorization": f"Bearer {token}"}, timeout=120) as response:
        event = None
        for line in response.iter_lines():
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
                at = time.perf_counter() - started
                if event == "token":
                    answer += data["text"]
                    if len(answer) == len(data["text"]):
                        print(f"{at:6.1f}s  token (answer starts arriving)")
                elif event == "step":
                    print(f"{at:6.1f}s  step   {data['tool']} {json.dumps(data['arguments'])[:60]}")
                else:
                    print(f"{at:6.1f}s  {event}  {json.dumps(data)[:90]}")
    print("\nANSWER:\n" + answer)
    server.should_exit = True


if __name__ == "__main__":
    main()
