"""The RMG skill (skills/rmg): its file follows Anthropic's rules, its scripts do what the instructions rely on, and it packs and
installs cleanly. The skill is self-contained on purpose (it must work without the app), so these tests load its scripts by path.
"""
import importlib.util
import re
import zipfile
from pathlib import Path

import pytest
from docx import Document

ROOT = Path(__file__).resolve().parents[2] / "skills"
SKILL = ROOT / "rmg"
EXAMPLES = SKILL / "examples"
REQUIRED = "Java, Spring Boot, REST, Kafka, SQL"
NICE = "AWS, Docker, Kubernetes"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def checker():
    import sys

    sys.path.insert(0, str(SKILL / "scripts"))  # coverage.py imports its sibling
    return load(SKILL / "scripts" / "check_claims.py", "skill_check_claims")


@pytest.fixture(scope="module")
def cover():
    return load(SKILL / "scripts" / "coverage.py", "skill_coverage")


def frontmatter_and_body():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    assert match, "SKILL.md must start with a --- frontmatter block"
    fields = dict(line.split(": ", 1) for line in match.group(1).splitlines() if ": " in line)
    return fields, match.group(2)


# --- the file follows the rules ------------------------------------------------------------------------------------

def test_the_name_follows_the_rules():
    name = frontmatter_and_body()[0]["name"]

    assert re.fullmatch(r"[a-z0-9-]{1,64}", name)
    assert "claude" not in name and "anthropic" not in name


def test_the_description_is_present_short_enough_and_says_when_to_use_it():
    description = frontmatter_and_body()[0]["description"]

    assert 0 < len(description) <= 1024
    assert "<" not in description and ">" not in description  # no XML tags
    assert "Use when" in description


def test_the_body_stays_small_enough_to_be_cheap_to_load():
    body = frontmatter_and_body()[1]

    assert len(body.split()) < 1500  # a few thousand tokens at most


def test_every_file_the_instructions_point_to_exists():
    body = frontmatter_and_body()[1]
    named = set(re.findall(r"(?:scripts|reference|examples)/[\w./-]+\.\w+", body))

    assert {"scripts/coverage.py", "scripts/check_claims.py", "scripts/inspect_template.py", "reference/playbook.md",
            "reference/output-format.md"} <= named
    assert [p for p in named if not (SKILL / p).exists()] == []


def test_the_skill_does_not_depend_on_the_app():
    for script in (SKILL / "scripts").glob("*.py"):
        source = script.read_text(encoding="utf-8")
        assert not re.search(r"^\s*(from|import)\s+app\b", source, re.MULTILINE), script.name


# --- matching ----------------------------------------------------------------------------------------------------------

def test_a_skill_matches_as_a_whole_word_only(checker):
    assert checker.mentions("Built it in Java and Kafka", "Java")
    assert not checker.mentions("Built it in JavaScript", "Java")
    assert not checker.mentions("Wrote C++ code", "C")
    assert checker.mentions("used spring   boot daily", "Spring Boot")


def test_the_coverage_counts_the_must_haves_and_lists_the_gaps(cover):
    text = (EXAMPLES / "sample_resume.txt").read_text(encoding="utf-8")

    result = cover.coverage(text, [s.strip() for s in REQUIRED.split(",")], [s.strip() for s in NICE.split(",")])

    assert result["required_shown"] == ["Java", "Spring Boot", "REST", "Kafka"]
    assert result["required_gaps"] == ["SQL"]  # the resume says PostgreSQL: the match is literal on purpose
    assert result["required_percent"] == 80
    assert result["nice_shown"] == ["Docker"] and result["nice_gaps"] == ["AWS", "Kubernetes"]


def test_coverage_with_no_must_haves_has_no_percentage(cover):
    assert cover.coverage("anything", [], [])["required_percent"] is None


# --- the guardrail -----------------------------------------------------------------------------------------------------

def run_check(checker, tailored: str, **extra):
    original = (EXAMPLES / "sample_resume.txt").read_text(encoding="utf-8")
    text = (EXAMPLES / tailored).read_text(encoding="utf-8")
    return checker.check(original, text, [s.strip() for s in REQUIRED.split(",")], [s.strip() for s in NICE.split(",")], **extra)


def test_an_honest_rewrite_passes(checker):
    assert run_check(checker, "sample_tailored_ok.txt") == []


def test_a_cheating_rewrite_is_caught_for_every_kind_of_claim(checker):
    problems = run_check(checker, "sample_tailored_bad.txt")

    found = {(p["kind"], p["detail"]) for p in problems}
    assert ("missing_skill", "Kubernetes") in found  # a skill the JD wants and the resume lacks
    assert ("new_number", "200") in found  # 14 became 200
    assert ("new_term", "TerraformCloud") in found  # a tool that is nowhere in the resume
    assert [p["line"] for p in problems if p["detail"] == "Kubernetes"] == [5, 8]  # reported per line


def test_a_skill_the_candidate_confirmed_is_not_reported(checker):
    problems = run_check(checker, "sample_tailored_bad.txt", confirmed=["Kubernetes"])

    assert not any(p["detail"] == "Kubernetes" for p in problems)
    assert any(p["detail"] == "200" for p in problems)  # everything else is still checked


def test_a_capital_letter_that_only_starts_a_sentence_is_not_a_technology(checker):
    original = "Built payment APIs in Java. Cut report time."
    tailored = "Built payment APIs in Java. Redesigned nothing else."

    assert checker.check(original, tailored, [], []) == []
    assert any(p["detail"] == "FooBarDB" for p in checker.check(original, "Built payment APIs in Java. Used FooBarDB too.", [], []))


def test_a_word_or_number_that_a_person_checked_can_be_allowed(checker):
    problems = checker.check("Built APIs in Java.", "Built APIs in Java for 8 years.", [], [], allow=["8"])

    assert problems == []


# --- reading Word files ----------------------------------------------------------------------------------------------

def make_docx(path: Path) -> Path:
    doc = Document()
    doc.add_paragraph("Anil Verma")
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Skills"
    table.cell(0, 1).text = "Java, Kafka"
    doc.save(path)
    return path


def test_the_text_of_a_word_file_includes_its_tables(checker, tmp_path):
    text = checker.read_text(str(make_docx(tmp_path / "r.docx")))

    assert "Anil Verma" in text and "Java, Kafka" in text


def test_the_command_line_exit_codes_say_clean_failed_or_unreadable(checker, capsys):
    base = ["--original", str(EXAMPLES / "sample_resume.txt"), "--required", REQUIRED, "--nice", NICE]

    assert checker.main([*base, "--tailored", str(EXAMPLES / "sample_tailored_ok.txt")]) == 0
    assert "CHECK PASSED" in capsys.readouterr().out
    assert checker.main([*base, "--tailored", str(EXAMPLES / "sample_tailored_bad.txt")]) == 1
    assert "CHECK FAILED" in capsys.readouterr().out
    assert checker.main([*base, "--tailored", str(EXAMPLES / "missing.txt")]) == 2


def test_the_template_inspector_shows_styles_lists_and_tables(tmp_path):
    inspector = load(SKILL / "scripts" / "inspect_template.py", "skill_inspect")
    doc = Document()
    doc.add_heading("SKILLS", level=1)
    doc.add_paragraph("Java", style="List Bullet")
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Name"
    path = tmp_path / "t.docx"
    doc.save(path)

    lines = inspector.describe(str(path))

    assert any("Heading 1" in line and "SKILLS" in line for line in lines)
    assert any(line.startswith("list item") and "Java" in line for line in lines)
    assert any(line.startswith("table") and "1 row(s) x 2 column(s)" in line for line in lines)


# --- packing and installing ----------------------------------------------------------------------------------------

def test_the_zip_has_the_skill_folder_at_its_top_with_skill_md_inside(tmp_path):
    builder = load(ROOT / "build_zip.py", "skill_build_zip")

    target = builder.build(tmp_path)

    names = zipfile.ZipFile(target).namelist()
    assert target.name == "rmg-resume-tailor.zip"
    assert "rmg-resume-tailor/SKILL.md" in names
    assert "rmg-resume-tailor/scripts/check_claims.py" in names and "rmg-resume-tailor/reference/playbook.md" in names
    assert not any("__pycache__" in n or n.endswith(".pyc") for n in names)


def test_installing_copies_the_skill_under_its_real_name_and_replaces_an_old_copy(tmp_path):
    installer = load(ROOT / "install.py", "skill_install")
    stale = tmp_path / "rmg-resume-tailor"
    stale.mkdir()
    (stale / "old.txt").write_text("from an older version")

    target = installer.install(tmp_path)

    assert target == stale
    assert (target / "SKILL.md").exists() and (target / "scripts" / "coverage.py").exists()
    assert not (target / "old.txt").exists()


def test_the_company_template_is_never_committed():
    ignore = (ROOT.parent / ".gitignore").read_text(encoding="utf-8")

    assert "skills/rmg/assets/*.docx" in ignore and "skills/dist/" in ignore
    assert not list((SKILL / "assets").glob("*.docx")) or "skills/rmg/assets/*.docx" in ignore
