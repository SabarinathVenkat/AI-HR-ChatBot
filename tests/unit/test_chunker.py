"""Policy chunking: one chunk per '##' section, with clause ids for citation checks."""
from pathlib import Path

import pytest

from app.rag.chunker import chunk_policy_text, load_policy_dir

SAMPLE = """---
policy_id: POL-99
title: Sample Policy
version: "2.1"
effective_date: 2026-01-01
source_status: illustrative sample
---

> Banner that is not part of any section.

## 1. First Section
1.1 The first clause says alpha.
1.2 The second clause says beta.

## 2. Table Section
| Type | Days |
|---|---|
| AL | 18 |

## 3. Plain Section
Just a paragraph with no numbered clauses.
"""

POLICIES = Path(__file__).resolve().parents[2] / "data" / "policies"


def test_each_section_becomes_one_chunk_with_a_citable_section_id():
    chunks = chunk_policy_text(SAMPLE)

    assert [c.section_id for c in chunks] == ["POL-99 §1", "POL-99 §2", "POL-99 §3"]
    assert [c.title for c in chunks] == ["First Section", "Table Section", "Plain Section"]


def test_front_matter_is_carried_onto_every_chunk():
    chunks = chunk_policy_text(SAMPLE)

    assert {(c.policy_id, c.version, c.effective_date, c.policy_title) for c in chunks} == {
        ("POL-99", "2.1", "2026-01-01", "Sample Policy")
    }


def test_clause_ids_are_collected_for_the_citation_checker():
    first, table, plain = chunk_policy_text(SAMPLE)

    assert first.clause_ids == ("POL-99 §1.1", "POL-99 §1.2")
    assert table.clause_ids == ()
    assert plain.clause_ids == ()


def test_the_banner_before_the_first_heading_is_not_a_chunk():
    chunks = chunk_policy_text(SAMPLE)

    assert not any("Banner" in c.text for c in chunks)


def test_tables_stay_inside_their_section():
    table = chunk_policy_text(SAMPLE)[1]

    assert "| AL | 18 |" in table.text


def test_a_file_without_front_matter_is_not_a_policy():
    with pytest.raises(ValueError):
        chunk_policy_text("# Just a readme\n\n## Section\ntext")


def test_the_real_policy_library_loads_with_unique_section_ids():
    chunks = load_policy_dir(POLICIES)

    section_ids = [c.section_id for c in chunks]
    assert len(section_ids) == len(set(section_ids))
    assert {c.policy_id for c in chunks} == {f"POL-0{i}" for i in range(1, 9)}


def test_the_notice_period_section_is_present_in_the_real_library():
    by_id = {c.section_id: c for c in load_policy_dir(POLICIES)}

    assert "60 days" in by_id["POL-05 §3"].text
    assert "POL-05 §3.1" in by_id["POL-05 §3"].clause_ids
