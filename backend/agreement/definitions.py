"""The definitions graph.

The EBITDA definition is written in terms of other defined terms, and those in
terms of more. Resolving them deterministically to depth 2 means the draft
request carries only the definitions it actually needs, which cuts tokens and
removes the temptation for the model to guess what a term means.

A term that is used but has no definition anywhere becomes
``unresolved_reference``, which blocks approval. That is the right outcome: a
formula built on a term nobody can find is not reviewable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.agreement.locate import definition_index
from backend.evaluator.schema import DefinitionNode, Span

MAX_DEPTH = 2

#: Terms every agreement uses that add nothing to an EBITDA formula. Sending
#: them would cost tokens and crowd out the definitions that matter.
NOISE_TERMS = frozenset(
    {
        "Administrative Agent",
        "Agreement",
        "Borrower",
        "Business Day",
        "Closing Date",
        "Dollars",
        "Effective Date",
        "GAAP",
        "Lender",
        "Lenders",
        "Loan",
        "Loan Documents",
        "Loan Parties",
        "Loan Party",
        "Person",
        "Required Lenders",
        "Responsible Officer",
        "Restricted Subsidiaries",
        "Restricted Subsidiary",
        "Subsidiaries",
        "Subsidiary",
    }
)


@dataclass
class DefinitionGraph:
    """Resolved definitions plus the terms that could not be found."""

    nodes: dict[str, DefinitionNode] = field(default_factory=dict)

    @property
    def unresolved(self) -> list[str]:
        return sorted(term for term, node in self.nodes.items() if not node.resolved)

    def as_schema(self) -> dict[str, DefinitionNode]:
        return dict(self.nodes)

    def prompt_text(self, *, limit: int = 2_000) -> str:
        """The resolved definitions, formatted for the draft request."""
        lines: list[str] = []
        for term in sorted(self.nodes):
            node = self.nodes[term]
            if not node.resolved or node.depth == 0 or not node.text:
                continue
            body = re.sub(r"\s+", " ", node.text).strip()
            if len(body) > limit:
                body = body[:limit] + " [...]"
            lines.append(body)
        return "\n\n".join(lines)


def referenced_terms(body: str, index: dict[str, tuple[int, int]]) -> list[str]:
    """Defined terms used inside ``body``, longest match first.

    Only terms the agreement actually defines are returned, so this never
    invents a reference: it is a lookup against the definition index, not an
    attempt to parse legal English.
    """
    found: list[str] = []
    for term in sorted(index, key=len, reverse=True):
        if term in NOISE_TERMS or len(term.split()) < 2:
            continue
        pattern = re.compile(r"\b" + re.escape(term) + r"\b")
        for match in pattern.finditer(body):
            # Skip the definition's own quoted headword.
            if body[max(0, match.start() - 1) : match.start()] == '"':
                continue
            found.append(term)
            break
    return found


def build_graph(
    text: str,
    root_term: str,
    *,
    max_depth: int = MAX_DEPTH,
    extra_terms: tuple[str, ...] = (),
) -> DefinitionGraph:
    """Resolve ``root_term`` and the terms it uses, to ``max_depth``."""
    index = definition_index(text)
    graph = DefinitionGraph()
    queue: list[tuple[str, int]] = [(root_term, 0)]
    for term in extra_terms:
        queue.append((term, 1))

    while queue:
        term, depth = queue.pop(0)
        if term in graph.nodes:
            # Keep the shallowest depth a term was reached at.
            if depth < graph.nodes[term].depth:
                graph.nodes[term].depth = depth
            continue
        span = index.get(term)
        if span is None:
            graph.nodes[term] = DefinitionNode(term=term, depth=depth, resolved=False)
            continue
        start, end = span
        body = text[start:end]
        children = referenced_terms(body, index) if depth < max_depth else []
        children = [child for child in children if child != term]
        graph.nodes[term] = DefinitionNode(
            term=term,
            depth=depth,
            span=Span(start=start, end=end, quote=body[:200]),
            text=body,
            resolved=True,
            references=children,
        )
        if depth < max_depth:
            for child in children:
                queue.append((child, depth + 1))
    return graph
