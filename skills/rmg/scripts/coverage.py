"""How well does a resume show the skills a job description asks for?

Counts a skill as shown when it appears in the resume as a whole word (case ignored), so "Java" is not found in "JavaScript".
The percentage is of the must-have skills. Skills the resume does not show are the gaps: they become questions for the candidate.

Usage:
  python coverage.py --resume resume.txt --required "Java, Kafka, SQL" --nice "AWS, Docker" [--json]
The resume may be .txt, .md or .docx. Needs only the standard library, plus python-docx for .docx files.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_claims import mentions, read_text, split_skills  # noqa: E402  (the same matching rule as the checker)


def coverage(resume_text: str, required: list[str], nice: list[str]) -> dict:
    shown_required = [s for s in required if mentions(resume_text, s)]
    shown_nice = [s for s in nice if mentions(resume_text, s)]
    return {
        "required_total": len(required),
        "required_shown": shown_required,
        "required_gaps": [s for s in required if s not in shown_required],
        "required_percent": round(100 * len(shown_required) / len(required)) if required else None,
        "nice_shown": shown_nice,
        "nice_gaps": [s for s in nice if s not in shown_nice],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--resume", required=True, help="the candidate's resume (.txt, .md or .docx)")
    parser.add_argument("--required", default="", help="must-have JD skills, comma separated")
    parser.add_argument("--nice", default="", help="nice-to-have JD skills, comma separated")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    args = parser.parse_args(argv)
    try:
        text = read_text(args.resume)
    except (OSError, ImportError) as error:
        print(f"Could not read the resume: {error}", file=sys.stderr)
        return 2
    result = coverage(text, split_skills(args.required), split_skills(args.nice))
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    if result["required_percent"] is None:
        print("No must-have skills were given.")
    else:
        print(f"Must-have skills shown: {len(result['required_shown'])} of {result['required_total']} ({result['required_percent']} percent)")
    print("  shown:", ", ".join(result["required_shown"]) or "none")
    print("  gaps (ask the candidate):", ", ".join(result["required_gaps"]) or "none")
    print("Nice-to-have shown:", ", ".join(result["nice_shown"]) or "none")
    print("Nice-to-have gaps:", ", ".join(result["nice_gaps"]) or "none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
