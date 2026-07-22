"""
Document Chunker Tool
----------------------
Single Responsibility: split long document text into overlapping chunks that
fit inside an LLM context window without losing inter-sentence context.

Used by the parsing pipeline when a requirement document is too large to pass
to an LLM agent in one shot.  Small documents (≤ chunk_size chars) are returned
as a single-element list so callers need no special-case logic.

Two public helpers are exposed:
  - chunk_text()                 — generic, fully configurable
  - chunk_document_for_requirements() — tuned defaults for FR-style docs
"""
from __future__ import annotations


def chunk_text(
    text: str,
    chunk_size: int = 1500,
    overlap: int = 200,
) -> list[str]:
    """
    Split *text* into overlapping fixed-size chunks.

    Boundary preference (highest to lowest):
      1. Double-newline paragraph break within the last half of the window.
      2. Sentence-ending punctuation (. ! ?) followed by a space.
      3. Any newline.
      4. Hard cut at *chunk_size* (never produces an empty chunk).

    Args:
        text:       Source document text.
        chunk_size: Maximum characters per chunk (default 1 500).
        overlap:    Characters of overlap between consecutive chunks (default 200).
                    Overlap preserves context at chunk boundaries so requirements
                    that span a hard cut are not silently truncated.

    Returns:
        List of non-empty strings.  Returns ``[text]`` when the document fits
        in one chunk, and ``[]`` when *text* is empty.
    """
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = min(start + chunk_size, text_len)

        if end < text_len:
            # 1. Paragraph break in the back half of the window
            para = text.rfind("\n\n", start + chunk_size // 2, end)
            if para != -1:
                end = para + 2
            else:
                # 2. Sentence boundary
                sent = max(
                    text.rfind(". ", start + chunk_size // 4, end),
                    text.rfind("! ", start + chunk_size // 4, end),
                    text.rfind("? ", start + chunk_size // 4, end),
                )
                if sent != -1:
                    end = sent + 1
                else:
                    # 3. Any newline
                    nl = text.rfind("\n", start + chunk_size // 4, end)
                    if nl != -1:
                        end = nl + 1
                    # 4. Hard cut — end stays as-is

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        # Advance with overlap; guard against infinite loop on tiny inputs
        advance = max(1, end - start - overlap)
        start += advance

    return chunks


def chunk_document_for_requirements(text: str) -> list[str]:
    """
    Chunker preset optimised for FR-style requirement documents.

    Uses larger chunks (3 000 chars) so that multi-line ``FR-N: Title … sub-
    fields`` blocks are kept together, and a 300-char overlap so a requirement
    whose header lands right at a boundary is captured in both the preceding
    and following chunk.

    Args:
        text: Parsed document text (from ``parse_document``).

    Returns:
        List of text chunks ready for per-chunk requirement extraction.
    """
    return chunk_text(text, chunk_size=3000, overlap=300)
