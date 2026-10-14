"""Turn a filed exhibit into one normalised text with stable offsets.

Every span in a formula is a character offset into the text this module
produces, so normalisation has to be deterministic and has to be the only
normalisation in the system. Two rules do the work:

* inline tags are removed without adding anything, because filers wrap single
  words in ``<font>`` tags and inserting a space there would split words;
* block-level tags become a single newline, because without one the last word
  of a paragraph would join the first word of the next.

The source hash is taken over the normalised text, not the raw HTML, so a
reformatted-but-identical filing does not invalidate an approved formula.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass

from bs4 import BeautifulSoup, NavigableString, Tag

#: Tags that end a line of text.
BLOCK_TAGS = frozenset(
    {
        "p", "div", "br", "tr", "td", "th", "table", "tbody", "thead",
        "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6",
        "section", "article", "blockquote", "hr", "caption", "center",
    }
)

#: Tags whose contents are not part of the document text.
DROP_TAGS = frozenset({"script", "style", "head", "title", "ix:header"})

#: Typographic characters filers use that have plain equivalents. Normalising
#: them means a quote drafted from the text matches the text.
#:
#: The C1 block (U+0080-U+009F) is in here because filers really do serve it.
#: Those code points are control characters that never occur in prose: when a
#: filing contains them, cp1252 punctuation has been decoded as Latin-1
#: somewhere upstream, and U+0093 is a left double quote that lost its way.
#: Leaving them alone is not neutral - every defined term in the agreement is
#: announced by a quotation mark, so a document full of U+0093 has, as far as
#: the definition locator is concerned, no definitions at all. Found on
#: Lantheus Holdings' 2024 credit agreement, where it reduced the definition
#: index from several hundred terms to zero. See docs/evaluation/generalisation.md.
TRANSLATIONS = {
    "": "'",
    "": "'",
    "": '"',
    "": '"',
    "": "-",
    "": "-",
    "": "-",
    "": "...",
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    "​": "",
    "﻿": "",
    "‘": "'",
    "’": "'",
    "‚": "'",
    "“": '"',
    "”": '"',
    "„": '"',
    "–": "-",
    "—": "-",
    "―": "-",
    "−": "-",
    "…": "...",
}

_TRANSLATE_TABLE = {ord(key): value for key, value in TRANSLATIONS.items()}


@dataclass(frozen=True)
class NormalisedAgreement:
    """The agreement as one text, plus what it was made from."""

    text: str
    source_url: str
    source_hash: str
    raw_bytes: int

    def slice(self, start: int, end: int) -> str:
        return self.text[start:end]

    def find(self, needle: str, start: int = 0) -> int:
        return self.text.find(needle, start)


def normalise_text(raw: str) -> str:
    """Normalise already-plain text the same way the HTML path does."""
    text = unicodedata.normalize("NFKC", raw)
    text = text.translate(_TRANSLATE_TABLE)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def html_to_text(raw_html: str) -> str:
    """Extract the document text from a filed HTML exhibit."""
    soup = BeautifulSoup(raw_html, "lxml")
    for tag in soup.find_all(list(DROP_TAGS)):
        tag.decompose()

    pieces: list[str] = []
    for node in soup.descendants:
        if isinstance(node, Tag):
            if node.name in BLOCK_TAGS:
                pieces.append("\n")
            continue
        if isinstance(node, NavigableString):
            pieces.append(str(node))
    return normalise_text("".join(pieces))


#: An opening tag of a kind a filed exhibit is built from. EDGAR wraps even a
#: plain-text exhibit in SGML headers, so the test looks for real markup rather
#: than for any angle bracket.
_HTML_TAG_RE = re.compile(
    r"<(?:html|body|div|p|font|span|table|tr|td|br|h[1-6]|ul|ol|li)[\s>/]", re.I
)


def looks_like_html(raw: str) -> bool:
    return _HTML_TAG_RE.search(raw[:8000]) is not None


def normalise(raw: str, *, source_url: str = "") -> NormalisedAgreement:
    """Normalise a filed exhibit, HTML or plain text."""
    body = html_to_text(raw) if looks_like_html(raw) else normalise_text(raw)
    return NormalisedAgreement(
        text=body,
        source_url=source_url,
        source_hash=text_hash(body),
        raw_bytes=len(raw.encode("utf-8")),
    )


def text_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalise_for_comparison(text: str) -> str:
    """Collapse all whitespace, for comparing a quote against the source.

    Span verification compares a drafted quote to the text at its offsets after
    this transformation, so a difference in line breaks is not treated as a
    fabricated span while a difference in words still is.
    """
    return re.sub(r"\s+", " ", text).strip()
