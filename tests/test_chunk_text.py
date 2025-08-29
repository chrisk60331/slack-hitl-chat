from typing import List

from src.completion_notifier import _chunk_text


def collect_chunks(text: str, max_len: int) -> List[str]:
    return list(_chunk_text(text, max_len))


def test_sentence_first_chunking_prefers_smaller_chunks() -> None:
    text = (
        "This is sentence one. This is sentence two! "
        "And here is sentence three? Finally, sentence four."
    )
    chunks = collect_chunks(text, max_len=40)
    # Should split at sentence boundaries and keep chunks under max_len
    assert all(len(c) <= 40 for c in chunks)
    # Expect at least 3 chunks given short max_len and preference for smaller chunks
    assert len(chunks) >= 3
    # Chunks should end with sentence punctuation where possible
    assert any(c.strip().endswith((".", "!", "?")) for c in chunks)


def test_long_sentence_word_split_then_hard_slice() -> None:
    long_sentence = "ThisIsAnExtremelyLongSingleWordThatExceedsTheLimitByItselfWithoutSpaces"
    # Add some surrounding text to ensure flushing behavior
    text = f"Intro. {long_sentence} Outro."
    chunks = collect_chunks(text, max_len=20)
    assert all(len(c) <= 20 for c in chunks)
    # Ensure the very long word was broken into multiple pieces
    assert any("ExtremelyLong"[:5] in c for c in chunks)


def test_newlines_are_respected_as_boundaries() -> None:
    text = "Line one.\n\nLine two continues here.\nAnd line three."
    chunks = collect_chunks(text, max_len=50)
    assert all(len(c) <= 50 for c in chunks)
    # Expect multiple chunks due to newlines and sentences
    assert len(chunks) >= 2


def test_zero_or_negative_max_len_returns_empty() -> None:
    assert collect_chunks("anything", 0) == []
    assert collect_chunks("anything", -5) == []
