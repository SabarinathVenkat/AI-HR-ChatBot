"""Pack the RMG skill into a zip, for claude.ai or for the API.

Both want a zip whose top folder is named after the skill and holds SKILL.md:

  rmg-resume-tailor/
    SKILL.md
    reference/...  scripts/...  examples/...  assets/template.docx (if you put it there)

  python skills/build_zip.py                  writes skills/dist/rmg-resume-tailor.zip (with the template, if you added one)
  python skills/build_zip.py --no-template    writes skills/dist/rmg-resume-tailor-without-template.zip, a small file that is easy
                                              to email; whoever installs it adds assets/template.docx afterwards

claude.ai: Settings > Capabilities > Skills > upload the zip (needs a paid plan with code execution on).
API: upload it once to /v1/skills, then list the returned skill id in `container.skills` of a Messages request (see skills/README.md).
"""
import argparse
import sys
import zipfile
from pathlib import Path

SKILL_NAME = "rmg-resume-tailor"
SOURCE = Path(__file__).resolve().parent / "rmg"
DIST = Path(__file__).resolve().parent / "dist"
SKIP = {"__pycache__"}


def build(out_dir: Path = DIST, with_template: bool = True) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / (f"{SKILL_NAME}.zip" if with_template else f"{SKILL_NAME}-without-template.zip")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(SOURCE.rglob("*")):
            if path.is_dir() or any(part in SKIP for part in path.parts) or path.suffix == ".pyc":
                continue
            if not with_template and path.parent.name == "assets" and path.suffix == ".docx":
                continue
            zf.write(path, f"{SKILL_NAME}/{path.relative_to(SOURCE).as_posix()}")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", help="write the zip into this folder instead (for testing)")
    parser.add_argument("--no-template", action="store_true", help="leave the company template out (a small zip, easy to email)")
    args = parser.parse_args(argv)
    target = build(Path(args.out) if args.out else DIST, with_template=not args.no_template)
    size_kb = target.stat().st_size / 1024
    print(f"Wrote {target} ({size_kb:.0f} KB)")
    if not args.no_template and not (SOURCE / "assets" / "template.docx").exists():
        print("Note: assets/template.docx is not there, so the zip has no company template. Add it and run this again.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
