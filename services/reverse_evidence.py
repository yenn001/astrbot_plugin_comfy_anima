"""Capability-declared evidence returned by reverse-prompt backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final


CAP_FLAT_TAGS: Final[str] = "flat_tags"
CAP_SUBJECTS: Final[str] = "subjects"
CAP_COMPOSITION: Final[str] = "composition"
CAP_OCR: Final[str] = "ocr"
CAP_SPATIAL_BINDING: Final[str] = "spatial_binding"
CAP_CONFIDENCE: Final[str] = "confidence"


@dataclass(frozen=True, slots=True)
class ReverseEvidence:
    """Observed reverse evidence and the capabilities that produced it."""

    source_backend: str
    flat_tags: str = ""
    subjects: tuple[str, ...] = ()
    composition: str = ""
    ocr: tuple[str, ...] = ()
    spatial_binding: tuple[str, ...] = ()
    confidence_available: bool = False
    capabilities: frozenset[str] = field(default_factory=frozenset)

    def supports(self, capability: str) -> bool:
        return str(capability or "").strip() in self.capabilities

    @classmethod
    def flat_tagger(cls, tags: str, *, backend: str = "workflow") -> "ReverseEvidence":
        return cls(
            source_backend=backend,
            flat_tags=str(tags or "").strip(),
            capabilities=frozenset({CAP_FLAT_TAGS}),
        )


__all__ = [
    "CAP_COMPOSITION",
    "CAP_CONFIDENCE",
    "CAP_FLAT_TAGS",
    "CAP_OCR",
    "CAP_SPATIAL_BINDING",
    "CAP_SUBJECTS",
    "ReverseEvidence",
]
