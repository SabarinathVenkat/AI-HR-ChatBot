"""Install the RMG skill where Claude Code looks for skills.

Claude Code finds a skill in a folder named after it, under `.claude/skills/` (this project only) or `~/.claude/skills/` (every
project on this computer). The source lives in `skills/rmg/`, so this script copies it there under the skill's real name.

  python skills/install.py              install for this project  (.claude/skills/rmg-resume-tailor)
  python skills/install.py --personal   install for you, in every project (~/.claude/skills/rmg-resume-tailor)

Run it again after you change the skill: it replaces the installed copy.
"""
import argparse
import shutil
import sys
from pathlib import Path

SKILL_NAME = "rmg-resume-tailor"
SOURCE = Path(__file__).resolve().parent / "rmg"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc")


def install(destination_root: Path) -> Path:
    target = destination_root / SKILL_NAME
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(SOURCE, target, ignore=IGNORE)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--personal", action="store_true", help="install for every project, in your home folder")
    parser.add_argument("--dest", help="install under this folder instead (for testing)")
    args = parser.parse_args(argv)
    root = Path(args.dest) if args.dest else (Path.home() / ".claude" / "skills" if args.personal else PROJECT_ROOT / ".claude" / "skills")
    target = install(root)
    print(f"Installed {SKILL_NAME} to {target}")
    print("Start Claude Code in this project (or restart it) and ask: 'Tailor this resume to this job description'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
