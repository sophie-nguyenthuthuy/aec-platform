"""CODEGUARD regulation ingestion pipeline.

Parses PDF / plain text / structured JSON of a Vietnamese building code,
splits it by heading hierarchy into sections, embeds each section with
text-embedding-3-large, upserts into `regulations` + `regulation_chunks`,
and (optionally) mirrors the chunks into an Elasticsearch index for BM25.

CLI usage (from repo root):
    python -m apps.ml.pipelines.codeguard_ingest \\
        --source /path/to/QCVN_06_2022.pdf \\
        --code "QCVN 06:2022/BXD" \\
        --country VN --jurisdiction "national" \\
        --category fire_safety --effective 2022-10-25 \\
        --language vi
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import UUID, uuid4

from langchain_openai import OpenAIEmbeddings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_EMBED_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-large")
_EMBED_BATCH = 64
_CHUNK_TARGET_CHARS = 1200
_CHUNK_MAX_CHARS = 1800
_CHUNK_MIN_CHARS = 50

# Matches Vietnamese code section headings like:
#   "3", "3.2", "3.2.1", "Điều 12.", "Article 3.1", "Mục 2"
_HEADING_RE = re.compile(
    r"^\s*(?:(?:Điều|Article|Mục|Chương|Phụ lục)\s+)?"
    r"(\d+(?:\.\d+){0,4})\.?\s+(.{3,200})$",
    re.IGNORECASE,
)


# ---------- Data classes ----------

@dataclass
class Section:
    section_ref: str
    title: str
    content: str
    level: int = field(init=False)

    def __post_init__(self) -> None:
        self.level = self.section_ref.count(".") + 1


@dataclass
class IngestResult:
    regulation_id: UUID
    sections_written: int
    chunks_written: int
    es_indexed: int


# ---------- Parsing ----------

def _load_source_text(source: Path) -> str:
    """Load source as plain text. Supports .pdf via pdfplumber, .txt / .md direct."""
    suffix = source.suffix.lower()
    if suffix in {".txt", ".md"}:
        return source.read_text(encoding="utf-8")
    if suffix == ".pdf":
        try:
            import pdfplumber  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "pdfplumber is required for PDF ingestion. "
                "Install with: pip install pdfplumber"
            ) from exc
        pages: list[str] = []
        with pdfplumber.open(str(source)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                pages.append(page_text)
        return "\n\n".join(pages)
    raise ValueError(f"Unsupported source type: {suffix}")


def split_into_sections(raw_text: str) -> list[Section]:
    """Section splitter driven by numeric heading hierarchy.

    The splitter walks lines, detects heading lines (e.g. "3.2.1 Title"),
    and accumulates text under the last seen heading. Paragraphs preceding
    the first heading are discarded (usually TOC/cover).
    """
    sections: list[Section] = []
    current_ref: str | None = None
    current_title = ""
    buffer: list[str] = []

    def flush() -> None:
        if current_ref is None:
            return
        body = "\n".join(buffer).strip()
        if len(body) < _CHUNK_MIN_CHARS:
            return
        sections.append(Section(section_ref=current_ref, title=current_title, content=body))

    for raw_line in raw_text.splitlines():
        line = raw_line.rstrip()
        m = _HEADING_RE.match(line)
        if m and _looks_like_heading(line):
            flush()
            current_ref = m.group(1)
            current_title = m.group(2).strip()
            buffer = []
        else:
            if current_ref is not None:
                buffer.append(line)

    flush()
    return sections


def _looks_like_heading(line: str) -> bool:
    """Heuristic: headings are short, title-cased, and have no mid-sentence punctuation.

    Body lines like "200 m², cho phép bố trí..." match the raw regex but are not
    headings — reject them via terminal-punctuation, comma, and leading-letter checks.
    """
    stripped = line.strip()
    if len(stripped) > 220:
        return False
    if len(stripped.split()) > 30:
        return False
    m = _HEADING_RE.match(stripped)
    if not m:
        return False
    title = m.group(2).strip()
    # Headings don't end with sentence terminators.
    if title.endswith((".", ",", ";", ":")):
        return False
    # Headings don't contain mid-sentence commas (body text often does).
    if "," in title:
        return False
    # First char of the title should be a letter (not a unit symbol or digit).
    first = title[:1]
    if not first.isalpha() or not first[0].isupper():
        return False
    return True


def chunk_section(section: Section) -> list[str]:
    """Split a long section into ~1200-char chunks along paragraph boundaries."""
    text = section.content
    if len(text) <= _CHUNK_MAX_CHARS:
        return [text]

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for para in paragraphs:
        if current_len + len(para) + 1 > _CHUNK_TARGET_CHARS and current:
            chunks.append("\n\n".join(current))
            current = [para]
            current_len = len(para)
        else:
            current.append(para)
            current_len += len(para) + 2
    if current:
        chunks.append("\n\n".join(current))
    return chunks


# ---------- Embedding ----------

async def _embed_batched(texts: list[str]) -> list[list[float]]:
    embedder = OpenAIEmbeddings(model=_EMBED_MODEL)
    out: list[list[float]] = []
    for i in range(0, len(texts), _EMBED_BATCH):
        batch = texts[i : i + _EMBED_BATCH]
        vectors = await embedder.aembed_documents(batch)
        out.extend(vectors)
    return out


# ---------- Persistence ----------

async def _upsert_regulation(
    db: AsyncSession,
    *,
    country_code: str,
    jurisdiction: str | None,
    code_name: str,
    category: str | None,
    effective_date: date | None,
    source_url: str | None,
    raw_text: str,
    language: str,
) -> UUID:
    """Upsert by (code_name) — each regulation is identified by its canonical name."""
    existing = (
        await db.execute(
            text("SELECT id FROM regulations WHERE code_name = :code"),
            {"code": code_name},
        )
    ).scalar_one_or_none()

    if existing is not None:
        reg_id = UUID(str(existing))
        await db.execute(
            text(
                """
                UPDATE regulations
                SET country_code=:cc, jurisdiction=:j, category=:cat,
                    effective_date=:eff, source_url=:url, raw_text=:raw, language=:lang
                WHERE id=:id
                """
            ),
            {
                "cc": country_code, "j": jurisdiction, "cat": category,
                "eff": effective_date, "url": source_url, "raw": raw_text,
                "lang": language, "id": str(reg_id),
            },
        )
        await db.execute(
            text("DELETE FROM regulation_chunks WHERE regulation_id = :id"),
            {"id": str(reg_id)},
        )
        return reg_id

    reg_id = uuid4()
    await db.execute(
        text(
            """
            INSERT INTO regulations
                (id, country_code, jurisdiction, code_name, category,
                 effective_date, source_url, raw_text, language)
            VALUES (:id, :cc, :j, :code, :cat, :eff, :url, :raw, :lang)
            """
        ),
        {
            "id": str(reg_id), "cc": country_code, "j": jurisdiction,
            "code": code_name, "cat": category, "eff": effective_date,
            "url": source_url, "raw": raw_text, "lang": language,
        },
    )
    return reg_id


async def _insert_chunks(
    db: AsyncSession,
    regulation_id: UUID,
    items: list[tuple[Section, str, list[float]]],
) -> int:
    inserted = 0
    for section, chunk_text, embedding in items:
        vec_literal = "[" + ",".join(f"{x:.7f}" for x in embedding) + "]"
        await db.execute(
            text(
                """
                INSERT INTO regulation_chunks (id, regulation_id, section_ref, content, embedding)
                VALUES (gen_random_uuid(), :rid, :ref, :content, CAST(:vec AS vector))
                """
            ),
            {
                "rid": str(regulation_id),
                "ref": section.section_ref,
                "content": chunk_text,
                "vec": vec_literal,
            },
        )
        inserted += 1
    return inserted


# ---------- Elasticsearch mirror ----------

async def _index_to_elasticsearch(
    regulation_id: UUID,
    code_name: str,
    category: str | None,
    jurisdiction: str | None,
    items: list[tuple[Section, str]],
) -> int:
    """Mirror chunks to Elasticsearch. Silent no-op if ES unavailable."""
    es_url = os.getenv("ELASTICSEARCH_URL")
    if not es_url:
        return 0
    try:
        from elasticsearch import AsyncElasticsearch  # type: ignore[import-not-found]
    except ImportError:
        return 0

    es = AsyncElasticsearch(es_url)
    indexed = 0
    try:
        for section, chunk_text in items:
            await es.index(
                index="regulation_chunks",
                document={
                    "regulation_id": str(regulation_id),
                    "code_name": code_name,
                    "section_ref": section.section_ref,
                    "category": category,
                    "jurisdiction": jurisdiction,
                    "content": chunk_text,
                },
            )
            indexed += 1
    except Exception as exc:
        logger.warning("Elasticsearch indexing failed: %s", exc)
    finally:
        await es.close()
    return indexed


# ---------- Public entry point ----------

async def ingest_regulation(
    db: AsyncSession,
    *,
    source: Path,
    code_name: str,
    country_code: str,
    jurisdiction: str | None,
    category: str | None,
    effective_date: date | None,
    source_url: str | None,
    language: str = "vi",
) -> IngestResult:
    raw_text = _load_source_text(source)
    if not raw_text.strip():
        raise ValueError(f"Source produced empty text: {source}")

    sections = split_into_sections(raw_text)
    if not sections:
        raise ValueError(
            "Section splitter produced no sections — check heading format of the source."
        )

    regulation_id = await _upsert_regulation(
        db,
        country_code=country_code.upper(),
        jurisdiction=jurisdiction,
        code_name=code_name,
        category=category,
        effective_date=effective_date,
        source_url=source_url,
        raw_text=raw_text,
        language=language,
    )

    # Build (section, chunk_text) list, then embed in batches.
    pairs: list[tuple[Section, str]] = []
    for section in sections:
        for piece in chunk_section(section):
            pairs.append((section, piece))

    logger.info("Embedding %d chunks for %s", len(pairs), code_name)
    embeddings = await _embed_batched([p[1] for p in pairs])
    triples = [(s, txt, emb) for (s, txt), emb in zip(pairs, embeddings, strict=True)]

    chunks_written = await _insert_chunks(db, regulation_id, triples)
    await db.commit()

    es_indexed = await _index_to_elasticsearch(
        regulation_id=regulation_id,
        code_name=code_name,
        category=category,
        jurisdiction=jurisdiction,
        items=pairs,
    )

    logger.info(
        "Ingested %s: %d sections, %d chunks, %d ES docs",
        code_name, len(sections), chunks_written, es_indexed,
    )
    return IngestResult(
        regulation_id=regulation_id,
        sections_written=len(sections),
        chunks_written=chunks_written,
        es_indexed=es_indexed,
    )


# ---------- CLI ----------

def _parse_args(argv: Iterable[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Ingest a regulation into CODEGUARD.")
    p.add_argument("--source", type=Path, required=True, help="Path to PDF / TXT / MD")
    p.add_argument("--code", dest="code_name", required=True, help="Canonical code name, e.g. QCVN 06:2022/BXD")
    p.add_argument("--country", dest="country_code", default="VN")
    p.add_argument("--jurisdiction", default=None)
    p.add_argument(
        "--category",
        choices=["fire_safety", "accessibility", "structure", "zoning", "energy"],
        default=None,
    )
    p.add_argument("--effective", dest="effective_date", default=None, help="YYYY-MM-DD")
    p.add_argument("--source-url", default=None)
    p.add_argument("--language", default="vi")
    return p.parse_args(list(argv))


async def _cli_main(args: argparse.Namespace) -> None:
    # Imports here to keep `python -m` startup fast when the CLI isn't used.
    from db.session import SessionFactory  # type: ignore[import-not-found]

    effective = (
        datetime.strptime(args.effective_date, "%Y-%m-%d").date()
        if args.effective_date else None
    )
    async with SessionFactory() as session:
        result = await ingest_regulation(
            session,
            source=args.source,
            code_name=args.code_name,
            country_code=args.country_code,
            jurisdiction=args.jurisdiction,
            category=args.category,
            effective_date=effective,
            source_url=args.source_url,
            language=args.language,
        )
    print(
        f"OK regulation_id={result.regulation_id} "
        f"sections={result.sections_written} chunks={result.chunks_written} "
        f"es={result.es_indexed}"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(_cli_main(_parse_args(sys.argv[1:])))
