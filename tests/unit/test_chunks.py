"""Splitting a finished answer into stream chunks must never change the text."""
from hypothesis import given, strategies as st

from app.agent.graph import TOKEN_CHUNK_CHARS, _chunks


def test_chunks_join_back_to_the_original_text():
    text = "You have 12 days of annual leave available.\n\n- Accrued: 13.5\n- Used: 4.5"

    assert "".join(_chunks(text)) == text


@given(st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=300))
def test_chunks_always_reproduce_any_text(text):
    assert "".join(_chunks(text)) == text


def test_chunks_are_small():
    text = "word " * 100

    pieces = list(_chunks(text))

    assert len(pieces) > 5
    assert all(len(p) <= TOKEN_CHUNK_CHARS + 20 for p in pieces)


def test_an_empty_answer_produces_no_chunks():
    assert list(_chunks("")) == []
