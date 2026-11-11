"""A live check of how the chat editor reads requests, with the real model (a few cents). Each request is tried three times.

    .venv\\Scripts\\python.exe scripts\\resume_chat_probe.py

The important lines: a request that only names a skill ("Add Kubernetes to my skills") must NOT become an added fact,
while a statement of real experience ("I also ran Kubernetes clusters at Finwave") must. Needs ANTHROPIC_API_KEY.
"""
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
load_dotenv(ROOT / ".env")

from app.rmg.resume.chat import LLMEditInterpreter  # noqa: E402
from app.rmg.resume.extract import anthropic_factory  # noqa: E402
from resume_ui_shots import rich_resume  # noqa: E402

CASES = [
    ("Mention Kubernetes in the Payment Gateway description.", "none"),
    ("Add Kubernetes to my skills.", "none"),
    ("Please include Terraform somewhere in the resume.", "none"),
    ("I also ran Kubernetes clusters at Finwave.", "add_fact"),
    ("Add that I led the Docker migration for the Fraud Alerts Platform.", "add_fact"),
    ("Make the first bullet of the Payment Gateway project shorter.", "set_text"),
]


def main() -> int:
    interpreter = LLMEditInterpreter(anthropic_factory())
    resume = rich_resume()
    mismatches = 0
    for message, wanted in CASES:
        got = [interpreter(message, resume).action for _ in range(3)]
        ok = all(action == wanted for action in got)
        mismatches += not ok
        print(("OK  " if ok else "BAD ") + f"{message!r}: wanted {wanted}, got {got}")
    print("mismatches:", mismatches)
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
