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


def test_the_templates_own_words_are_not_claims_but_the_template_never_excuses_a_missing_skill(checker):
    original = "Built payment APIs in Java."
    tailored = "KEY HIGHLIGHTS\nBuilt payment APIs in Java and Kubernetes."
    template = "KEY HIGHLIGHTS\nSample highlight\nKubernetes"

    without = {(p["kind"], p["detail"]) for p in checker.check(original, tailored, [], ["Kubernetes"])}
    with_template = {(p["kind"], p["detail"]) for p in checker.check(original, tailored, [], ["Kubernetes"], template=template)}

    assert ("new_term", "KEY") in without and ("new_term", "HIGHLIGHTS") in without
    assert not any(kind == "new_term" for kind, _ in with_template)  # the heading is the template's
    assert ("missing_skill", "Kubernetes") in with_template  # but a skill the resume lacks is still reported


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


def test_the_light_zip_leaves_the_company_template_out_but_keeps_everything_else(tmp_path, monkeypatch):
    builder = load(ROOT / "build_zip.py", "skill_build_zip_light")
    source = tmp_path / "rmg"
    (source / "assets").mkdir(parents=True)
    (source / "SKILL.md").write_text(chr(10).join(["---", "name: x", "description: y", "---", ""]))
    (source / "assets" / "template.docx").write_bytes(b"company document")
    (source / "assets" / "README.md").write_text("where the template goes")
    monkeypatch.setattr(builder, "SOURCE", source)

    full = zipfile.ZipFile(builder.build(tmp_path / "out", with_template=True)).namelist()
    light_path = builder.build(tmp_path / "out", with_template=False)
    light = zipfile.ZipFile(light_path).namelist()

    assert light_path.name == "rmg-resume-tailor-without-template.zip"
    assert "rmg-resume-tailor/assets/template.docx" in full
    assert "rmg-resume-tailor/assets/template.docx" not in light
    assert "rmg-resume-tailor/SKILL.md" in light and "rmg-resume-tailor/assets/README.md" in light


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


# --- match levels (Mirror, Bridge, Summit) ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def levels():
    import sys

    sys.path.insert(0, str(SKILL / "scripts"))
    return load(SKILL / "scripts" / "match_level.py", "skill_match_level")


def test_the_three_levels_have_their_own_names_and_targets(levels):
    assert levels.LEVELS == {"mirror": None, "bridge": 50, "summit": 80}


def test_mirror_has_no_target_and_still_lists_what_is_evidenced_and_what_to_ask(levels):
    result = levels.plan("Java, PostgreSQL, Jenkins", ["Java", "SQL", "Kafka"], ["AWS"], "mirror")

    assert result["target_percent"] is None and result["needed_more"] == 0 and result["reached_with_evidence"] is True
    assert list(result["evidence"]) == ["SQL"] and result["ask_the_candidate"] == ["Kafka", "AWS"]


def test_summit_counts_how_many_more_must_haves_are_needed(levels):
    result = levels.plan("Java, Spring Boot", ["Java", "Spring Boot", "Kafka", "SQL", "REST"], [], "summit")

    assert result["required_percent"] == 40 and result["needed_more"] == 2  # 4 of 5 are needed


def test_evidence_can_reach_a_level_but_a_gap_with_no_evidence_never_counts(levels):
    reachable = levels.plan("Java, Spring Boot, PostgreSQL", ["Java", "Spring", "SQL", "Kafka"], [], "bridge")
    stuck = levels.plan("Java", ["Java", "Kafka", "Terraform", "FHIR", "AWS"], [], "summit")

    assert reachable["reached_with_evidence"] is True and reachable["percent_with_evidence"] == 75
    assert stuck["reached_with_evidence"] is False and stuck["percent_with_evidence"] == 20
    assert stuck["must_haves_the_candidate_would_have_to_confirm"] == 3 and set(stuck["ask_the_candidate"]) == {"Kafka", "Terraform", "FHIR", "AWS"}


def test_a_skill_the_candidate_confirmed_counts_as_shown(levels):
    result = levels.plan("Java", ["Java", "Kafka"], [], "bridge", confirmed=["Kafka"])

    assert result["required_percent"] == 100 and result["needed_more"] == 0


def test_an_inferred_skill_is_accepted_only_when_the_resume_really_shows_something_that_implies_it(checker):
    original = "Built services with Spring Boot and PostgreSQL. Used Jenkins for builds."
    tailored = "Built Spring services with PostgreSQL; ran CI/CD in Jenkins."

    assert checker.check(original, tailored, ["Spring", "CI/CD"], [], inferred=["Spring", "CI/CD"]) == []

    refused = checker.check(original, "Built services on Kubernetes.", ["Kubernetes"], [], inferred=["Kubernetes"])
    assert {p["kind"] for p in refused} >= {"inferred_without_evidence"}


def test_inferring_does_not_excuse_a_skill_that_was_not_listed_as_inferred(checker):
    problems = checker.check("Built services with Spring Boot.", "Built Spring services and CI/CD pipelines.", ["Spring", "CI/CD"], [],
                             inferred=["Spring"])

    assert [p["detail"] for p in problems if p["kind"] == "missing_skill"] == ["CI/CD"]


def test_the_evidence_list_is_strict_about_what_it_implies(levels):
    import related

    assert related.evidence_for("Spring", "Spring Boot") == ["Spring Boot"]
    assert related.evidence_for("Kubernetes", "Docker, AWS, Terraform") == []  # same field is not evidence
    assert related.evidence_for("Spring", "Java developer") == []  # knowing the language is not knowing the framework
    assert related.evidence_for("Kafka", "RabbitMQ") == []


def test_the_level_instructions_say_what_to_do_when_the_target_cannot_be_reached_honestly():
    text = (SKILL / "reference" / "match-levels.md").read_text(encoding="utf-8")

    assert all(name in text for name in ("Mirror", "Bridge", "Summit"))
    assert "do not add the skills" in text.lower() and "not reached" in text.lower()
