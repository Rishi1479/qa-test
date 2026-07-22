"""
Document Parsing Tool
----------------------
Single responsibility: turn a PDF/DOCX/Markdown file into structured text
(headings + paragraphs + list items), nothing else. It does not know what
a "requirement" is -- that is the RequirementExtractionTool's job.

Docling is the preferred backend because it gives layout-aware structure
(headings, bullet lists, tables) instead of a flat text blob, which makes
the downstream extraction tool far more reliable on real requirement
documents that use "FR-1:", bullet sub-fields, etc.

If Docling isn't installed/available in the runtime, we fall back to
PyMuPDF (already a project dependency) for plain text extraction, and to
a plain read for Markdown. This keeps the tool usable in constrained
environments without silently producing an empty result.
"""
from __future__ import annotations
import os


def _parse_with_docling(path: str) -> str:
    from docling.document_converter import DocumentConverter  # heavy import, kept local

    converter = DocumentConverter()
    result = converter.convert(path)
    return result.document.export_to_markdown()


def _parse_pdf_with_pymupdf(path: str) -> str:
    import fitz  # PyMuPDF

    text_parts = []
    with fitz.open(path) as doc:
        for page in doc:
            text_parts.append(page.get_text("text"))
    return "\n".join(text_parts)


def _parse_docx_fallback(path: str) -> str:
    import docx  # python-docx

    document = docx.Document(path)
    return "\n".join(p.text for p in document.paragraphs)


def parse_document(path: str) -> str:
    """
    Returns markdown-ish/plain structured text for the given document.
    Raises ValueError for unsupported extensions.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".pdf", ".docx", ".md", ".markdown", ".txt"):
        raise ValueError(f"Unsupported document type: {ext}")

    try:
        return _parse_with_docling(path)
    except Exception:
        # Docling not installed, or failed on this file -> deterministic fallback.
        pass

    if ext == ".pdf":
        return _parse_pdf_with_pymupdf(path)
    if ext == ".docx":
        return _parse_docx_fallback(path)
    # markdown / txt
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()
