from __future__ import annotations

import pytest

from yojana.generate.citations import CitationStreamFilter, validate_citations


def test_invalid_citations_are_stripped_and_lists_normalised() -> None:
    check = validate_citations("Grant of 100 [1]. Age limit [2, 7]. Income [9] .", 3)
    assert check.text == "Grant of 100 [1]. Age limit [2]. Income."
    assert check.cited == [1, 2]
    assert check.invalid == [7, 9]


def test_zero_is_not_a_valid_citation() -> None:
    assert validate_citations("x [0]", 2).text == "x"


def test_non_citation_brackets_are_left_alone() -> None:
    text = "See [the portal](https://example.org) and [note]."
    assert validate_citations(text, 2).text == text


def test_duplicate_numbers_in_one_group_collapse() -> None:
    assert validate_citations("a [1,1]", 1).text == "a [1]"


@pytest.mark.parametrize(
    "pieces",
    [
        ["Grant [1]. Age [", "2]. Bad [", "5] end"],
        ["Grant [", "1", "]. Age [2]. Bad [5", "] end"],
        list("Grant [1]. Age [2]. Bad [5] end"),
    ],
)
def test_stream_filter_matches_batch_validation(pieces: list[str]) -> None:
    stream = CitationStreamFilter(max_index=3)
    out = "".join(stream.feed(p) for p in pieces) + stream.flush()
    assert out == "Grant [1]. Age [2]. Bad end"
    assert stream.cited == [1, 2]
    assert stream.invalid == [5]


def test_stream_filter_releases_non_citations_quickly() -> None:
    stream = CitationStreamFilter(max_index=3)
    assert stream.feed("[l") == "[l"
    assert stream.feed("[12345678901234567") == "[12345678901234567"
    assert stream.feed(" [") == ""
    assert stream.flush() == " ["
