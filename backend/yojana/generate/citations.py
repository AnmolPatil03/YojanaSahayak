"""Inline `[n]` citations: validation after the fact and filtering while streaming."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

CITATION = re.compile(r"\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]")
_MAX_PENDING = 16


@dataclass(slots=True)
class CitationCheck:
    text: str
    cited: list[int] = field(default_factory=list)
    invalid: list[int] = field(default_factory=list)


def _rewrite(match: re.Match[str], max_index: int, cited: list[int], invalid: list[int]) -> str:
    numbers = [int(n) for n in match.group(1).split(",")]
    good = []
    for number in numbers:
        if 1 <= number <= max_index:
            if number not in good:
                good.append(number)
            if number not in cited:
                cited.append(number)
        else:
            invalid.append(number)
    return "".join(f"[{n}]" for n in good)


def validate_citations(text: str, max_index: int) -> CitationCheck:
    """Strip citations that point at no source; normalise `[1, 2]` to `[1][2]`."""
    cited: list[int] = []
    invalid: list[int] = []
    cleaned = CITATION.sub(lambda m: _rewrite(m, max_index, cited, invalid), text)
    cleaned = re.sub(r"[ \t]+([.,;:!?।])", r"\1", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"[ \t]+$", "", cleaned, flags=re.MULTILINE)
    return CitationCheck(text=cleaned, cited=cited, invalid=invalid)


class CitationStreamFilter:
    """Applies `validate_citations` to a token stream without delaying normal text.

    Text is passed through immediately except from an opening bracket until it
    either closes as a citation (which is then checked) or clearly is not one.
    """

    def __init__(self, max_index: int) -> None:
        self.max_index = max_index
        self.cited: list[int] = []
        self.invalid: list[int] = []
        self._pending = ""

    def _resolve(self, chunk: str) -> str:
        cited: list[int] = []
        invalid: list[int] = []
        out = CITATION.sub(lambda m: _rewrite(m, self.max_index, cited, invalid), chunk)
        self.cited.extend(n for n in cited if n not in self.cited)
        self.invalid.extend(invalid)
        return out

    def feed(self, token: str) -> str:
        """Return the text that can be shown now.

        Spaces are held back briefly so that an invalid citation can be dropped
        together with the space in front of it.
        """
        out: list[str] = []
        for char in token:
            if self._pending and "[" in self._pending:
                self._pending += char
                if char == "]":
                    spaces, _, bracket = self._pending.partition("[")
                    resolved = self._resolve("[" + bracket)
                    out.append(spaces + resolved if resolved else "")
                    self._pending = ""
                elif not (char.isdigit() or char in ", ") or len(self._pending) > _MAX_PENDING:
                    out.append(self._pending)
                    self._pending = ""
            elif char == "[" or char in " \t":
                self._pending += char
            else:
                out.append(self._pending + char)
                self._pending = ""
        return "".join(out)

    def flush(self) -> str:
        rest, self._pending = self._pending, ""
        return rest
