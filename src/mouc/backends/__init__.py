"""Document generation backends."""

from mouc.backends.base import (
    AnchorFunction,
    DocumentBackend,
    EntityReference,
    SectionStructure,
)
from mouc.backends.docx import DocxBackend
from mouc.backends.markdown import MarkdownBackend

__all__ = [
    "AnchorFunction",
    "DocumentBackend",
    "DocxBackend",
    "EntityReference",
    "MarkdownBackend",
    "SectionStructure",
]
