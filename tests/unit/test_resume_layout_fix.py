"""Judging and fixing the layout of a finished resume.

The model that judges may only choose from a short list of formatting changes, none of which can touch the words; a change is kept
only if the pages measure better afterwards; and nothing here can stop a download.
"""
import io

import pytest
from docx import Document

from app.rmg.resume.layout_check import Measured
from app.rmg.resume.layout_fix import (
    ALLOWED_FIXES, Fix, LayoutPolisher, Verdict, apply_fixes, build_prompt, default_fixes, polish,
)
from app.rmg.resume.template import W, paragraph_text
from tests.unit.resume_templates import make_template


def sectioned(blank_before_headings: int = 0) -> bytes:
    doc = make_template(highlights_subheading="Professional summary and Key highlights", blanks_before_projects=blank_before_headings)
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def paragraphs(docx: bytes) -> list:
    return list(Document(io.BytesIO(docx)).element.body.iter(W + "p"))


def texts(docx: bytes) -> list[str]:
    return [paragraph_text(p) for p in paragraphs(docx)]


def spacing_lines(docx: bytes) -> list[str | None]:
    return [p.find(f"{W}pPr/{W}spacing").get(W + "line") if p.find(f"{W}pPr/{W}spacing") is not None else None for p in paragraphs(docx)]


# --- the fixes: formatting only ---------------------------------------------------------------------------------------------

def test_tightening_lowers_the_line_spacing_and_never_changes_a_word():
    before = sectioned()

    after = apply_fixes(before, [Fix(op="tighten", level=2)])

    assert after is not None and texts(after) == texts(before)
    assert any(v is not None and int(v) < 240 for v in spacing_lines(after))


def test_keep_with_next_can_be_switched_off_everywhere():
    after = apply_fixes(sectioned(), [Fix(op="keep_next_off")])

    flags = [p.find(f"{W}pPr/{W}keepNext") for p in paragraphs(after)]
    assert all(f is not None and f.get(W + "val") == "0" for f in flags)


def test_blank_lines_before_headings_can_be_removed_and_the_words_stay():
    before = sectioned(blank_before_headings=3)

    after = apply_fixes(before, [Fix(op="remove_blank_lines")])

    assert [t for t in texts(after) if t] == [t for t in texts(before) if t]
    assert len(texts(after)) < len(texts(before))


def banner_docx() -> bytes:
    """A document whose top is a table (a banner) with a row of a set minimum height, then ordinary paragraphs."""
    doc = Document()
    table = doc.add_table(rows=2, cols=1)
    table.cell(0, 0).paragraphs[0].text = "Name"
    table.cell(1, 0).paragraphs[0].text = "A summary under the name in the banner."
    height = table.rows[1]._tr.get_or_add_trPr().makeelement(W + "trHeight", {W + "val": "1000", W + "hRule": "atLeast"})
    table.rows[1]._tr.get_or_add_trPr().append(height)
    doc.add_paragraph("SKILLS")
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def banner_row_height(docx: bytes) -> int:
    table = next(Document(io.BytesIO(docx)).element.body.iter(W + "tbl"))
    return int(table.findall(W + "tr")[-1].find(f"{W}trPr/{W}trHeight").get(W + "val"))


def test_the_header_block_can_be_made_taller_by_level_and_the_words_stay():
    before = banner_docx()

    small, big = apply_fixes(before, [Fix(op="grow_header", level=1)]), apply_fixes(before, [Fix(op="grow_header", level=3)])

    assert banner_row_height(before) == 1000 < banner_row_height(small) < banner_row_height(big)
    assert texts(small) == texts(before) == texts(big)


def test_growing_the_header_of_a_document_with_no_banner_table_changes_nothing():
    before = sectioned()

    assert texts(apply_fixes(before, [Fix(op="grow_header", level=2)])) == texts(before)


def test_a_page_break_can_be_put_before_a_heading_and_taken_away_again():
    added = apply_fixes(sectioned(), [Fix(op="break_before", heading="education")])
    heading = next(p for p in paragraphs(added) if paragraph_text(p) == "EDUCATION")
    assert heading.find(f"{W}pPr/{W}pageBreakBefore") is not None

    removed = apply_fixes(added, [Fix(op="no_break_before", heading="EDUCATION")])
    heading = next(p for p in paragraphs(removed) if paragraph_text(p) == "EDUCATION")
    assert heading.find(f"{W}pPr/{W}pageBreakBefore") is None


def test_a_fix_for_a_heading_that_is_not_there_changes_nothing():
    before = sectioned()

    assert texts(apply_fixes(before, [Fix(op="break_before", heading="NO SUCH HEADING")])) == texts(before)


def test_the_model_can_only_name_fixes_from_the_list():
    assert set(ALLOWED_FIXES) == {"tighten", "keep_next_off", "remove_blank_lines", "break_before", "no_break_before", "grow_header"}
    with pytest.raises(ValueError):
        Fix(op="rewrite_text")  # not a fix there is


def test_a_change_that_would_alter_the_words_is_refused(monkeypatch):
    def sabotage(doc, fix):
        for t in doc.element.body.iter(W + "t"):
            t.text = (t.text or "") + " changed"
            break

    monkeypatch.setattr("app.rmg.resume.layout_fix._OPS", {"tighten": sabotage})

    assert apply_fixes(sectioned(), [Fix(op="tighten", level=1)]) is None


# --- the loop --------------------------------------------------------------------------------------------------------------------

GOOD, BAD, WORSE, BADDER = b"good", b"bad", b"worse", b"badder"


def fake_render(docx):
    return b"pdf:" + docx


def fake_measure(pdf, docx, **kw):
    problems = {GOOD: (), BAD: ("page 2 is blank or nearly blank", "page 1: heading 'SKILLS' has nothing under it"),
                WORSE: ("a",) * 3, BADDER: ("a",) * 3}[docx]
    return Measured(pages=2, problems=problems, images=(b"png",))


class FakeJudge:
    def __init__(self, *verdicts, error=None):
        self.verdicts, self.error, self.calls = list(verdicts), error, []

    def __call__(self, images, problems, template_image):
        self.calls.append((list(images), list(problems), template_image))
        if self.error:
            raise self.error
        return self.verdicts.pop(0) if len(self.verdicts) > 1 else self.verdicts[0]


def fixer(mapping):
    def apply(docx, fixes):
        return mapping.get(docx)

    return apply


OK = Verdict(ok=True)
NOT_OK = Verdict(ok=False, issues=["a heading is alone"], fixes=[Fix(op="tighten", level=1)])


def run(docx, judge=None, apply=fixer({BAD: GOOD}), render=fake_render, rounds=2):
    return polish(docx, render, judge=judge, measure_fn=fake_measure, apply=apply, rounds=rounds)


def test_a_resume_that_measures_clean_and_the_judge_likes_is_returned_untouched():
    judge = FakeJudge(OK)

    result = run(GOOD, judge)

    assert (result.status, result.docx, result.rounds) == ("ok", GOOD, 0) and len(judge.calls) == 1


def test_a_complaint_from_the_judge_alone_that_measuring_does_not_confirm_does_not_fail_the_file():
    judge = FakeJudge(NOT_OK)

    result = run(GOOD, judge, apply=fixer({}))

    assert result.status == "ok" and result.docx == GOOD and result.issues == ()
    assert any("did not confirm" in note for note in result.notes)


def test_a_resume_with_problems_is_fixed_with_the_judges_choice_and_comes_back_better():
    judge = FakeJudge(NOT_OK, OK)

    result = run(BAD, judge)

    assert result.status == "fixed" and result.docx == GOOD and result.issues == () and result.rounds == 1
    assert judge.calls[0][1] == ["page 2 is blank or nearly blank", "page 1: heading 'SKILLS' has nothing under it"]  # it is told what code measured


def test_the_judge_is_shown_the_pages_and_the_templates_own_sample_page():
    judge = FakeJudge(OK)
    polisher = LayoutPolisher(fake_render, judge, measure_fn=lambda pdf, docx, **kw: Measured(2, (), (b"page1", b"page2")),
                              template_image=lambda template: b"template-page")

    polisher(GOOD, b"template")

    images, _, template_image = judge.calls[0]
    assert images == [b"page1", b"page2"] and template_image == b"template-page"


def test_a_fix_that_does_not_make_it_better_is_thrown_away_and_the_original_is_kept():
    judge = FakeJudge(NOT_OK)

    result = run(BAD, judge, apply=fixer({BAD: WORSE}))

    assert result.status == "unfixed" and result.docx == BAD and result.issues


def test_a_fix_that_would_change_the_words_is_never_used():
    result = run(BAD, FakeJudge(NOT_OK), apply=fixer({}))  # the fixer returns None, as it does when the words would change

    assert result.status == "unfixed" and result.docx == BAD


def test_it_tries_again_once_more_and_then_stops():
    judge = FakeJudge(NOT_OK)
    calls = []

    def apply(docx, fixes):
        calls.append(docx)
        return {BAD: BADDER, BADDER: BADDER}.get(docx)

    run(BAD, judge, apply=apply, rounds=2)

    assert len(calls) <= 2


def test_if_the_judge_fails_the_measured_problems_are_still_fixed_by_the_default_fixes():
    judge = FakeJudge(error=RuntimeError("model down"))

    result = run(BAD, judge)

    assert result.status == "fixed" and result.docx == GOOD and any("judge" in n.lower() for n in result.notes)


def test_without_a_judge_the_measuring_alone_decides():
    assert run(GOOD).status == "ok" and run(BAD).status == "fixed"


def test_with_no_renderer_the_file_is_returned_as_it_is_and_marked_not_checked():
    result = polish(BAD, lambda docx: None, judge=FakeJudge(OK), measure_fn=fake_measure, apply=fixer({BAD: GOOD}))

    assert (result.status, result.docx) == ("not_checked", BAD)


def test_a_renderer_that_raises_cannot_stop_the_download():
    def explode(docx):
        raise RuntimeError("office crashed")

    result = polish(BAD, explode, judge=None, measure_fn=fake_measure, apply=fixer({}))

    assert (result.status, result.docx) == ("not_checked", BAD)


def test_the_same_file_is_not_judged_twice():
    judge = FakeJudge(OK)
    polisher = LayoutPolisher(fake_render, judge, measure_fn=fake_measure, template_image=lambda t: None)

    first, second = polisher(GOOD, b"t"), polisher(GOOD, b"t")

    assert first == second and len(judge.calls) == 1


def test_the_default_fixes_are_formatting_only_and_get_stronger_each_round():
    first, second = default_fixes(["x"], 0), default_fixes(["x"], 1)

    assert {f.op for f in first + second} <= set(ALLOWED_FIXES)
    assert max(f.level or 0 for f in second) > max(f.level or 0 for f in first)


def test_the_prompt_lists_what_was_measured_the_allowed_fixes_and_says_not_to_touch_the_words():
    prompt = build_prompt(["page 2 is blank or nearly blank"], has_template_image=True)

    assert "page 2 is blank" in prompt and "tighten" in prompt and "keep_next_off" in prompt and "grow_header" in prompt
    assert "never" in prompt.lower() and "words" in prompt.lower() and "sample page" in prompt.lower()

