import asyncio
import json
import logging
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv(Path(__file__).parent.parent / ".env")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from src.classifier import classify, needs_clarification
from src.clarifier import apply_answer, get_next_question
from src.nostr_client import search_events
from src.oersi_client import simple_search
from src.similarity import refine_after_rejection

TWILLO_PATH = Path(__file__).parent.parent / "data" / "twillo_corpus.json"
TAXONOMY_PATH = Path(__file__).parent.parent / "data" / "situations_taxonomy.json"

# Maps UI format options → HCRT learningResourceType.prefLabel.de values
FORMAT_MAP: dict[str, list[str]] = {
    "Video": ["Video", "Audio"],
    "Skript / Text": ["Skript", "Textdokument", "Lehrbuch", "Nachschlagewerk"],
    "Übungsaufgaben": ["Übung", "Lernkontrolle", "Fragebogen", "Lernspiel"],
    "Methode / Aktivität": ["Unterrichtsplanung", "Arbeitsmaterial", "Fallstudie", "Präsentation"],
}


def _lrt_labels(hit: dict) -> set[str]:
    """Extract all learningResourceType German labels from a result hit."""
    labels = set()
    for lrt in hit.get("learningResourceType") or []:
        de = lrt.get("prefLabel", {}).get("de")
        if de:
            labels.add(de)
    return labels


def _filter_by_format(hits: list[dict], format_preferred) -> list[dict]:
    """Filter hits to those matching any of the preferred formats. Returns all hits if no filter."""
    if not format_preferred:
        return hits
    formats = format_preferred if isinstance(format_preferred, list) else [format_preferred]
    allowed = set()
    for f in formats:
        allowed.update(FORMAT_MAP.get(f, [f]))
    if not allowed:
        return hits
    return [h for h in hits if _lrt_labels(h) & allowed] or hits

app = FastAPI(title="OER-Navigator API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class QueryRequest(BaseModel):
    query: str


class ClarifyRequest(BaseModel):
    classification: dict
    axis: str
    answer: str


class SearchRequest(BaseModel):
    classification: dict
    size: int = 10
    negative_keywords: list[str] | None = None
    exclude_ids: list[str] | None = None


class RefineRequest(BaseModel):
    classification: dict
    rejected: dict
    candidates: list[dict]
    size: int = 12
    prior_negative_keywords: list[str] | None = None
    prior_exclude_ids: list[str] | None = None


@app.post("/classify")
def classify_query(req: QueryRequest):
    try:
        result = classify(req.query)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"LLM nicht erreichbar: {e}")
    question = get_next_question(result) if needs_clarification(result) else None
    return {"classification": result, "clarification_needed": question is not None, "question": question, "provider": result.get("provider")}


@app.post("/clarify")
def clarify(req: ClarifyRequest):
    updated = apply_answer(req.classification, req.axis, req.answer)
    question = get_next_question(updated) if needs_clarification(updated) else None
    return {"classification": updated, "clarification_needed": question is not None, "question": question}


@app.post("/search")
async def search(req: SearchRequest):
    clf = req.classification
    thema = clf.get("thema") or ""
    language = clf.get("language")
    format_preferred = clf.get("format_preferred")

    fmt_hint = " ".join(format_preferred) if isinstance(format_preferred, list) else (format_preferred or "")
    search_text = f"{thema} {fmt_hint}".strip() if fmt_hint else thema

    async def _oersi():
        try:
            raw = simple_search(
                search_text,
                size=req.size * 3,
                lang=language,
                negative_keywords=req.negative_keywords,
                exclude_ids=req.exclude_ids,
            )
            hits = [h["_source"] for h in raw["hits"]["hits"]]
        except Exception:
            hits = _fallback_search(search_text, req.size * 3)
            if req.exclude_ids:
                excl = set(req.exclude_ids)
                hits = [h for h in hits if (h.get("id") or h.get("@id")) not in excl]
        return _filter_by_format(hits, format_preferred)[:req.size]

    async def _nostr_events():
        return await search_events(thema, limit=req.size)

    hits, events = await asyncio.gather(_oersi(), _nostr_events())

    visualization = _get_visualization(clf.get("intention", "Überblick erarbeiten"))

    return {
        "results": hits,
        "events": events,
        "visualization": visualization,
        "total": len(hits),
        "source": "oersi+nostr",
    }


@app.post("/refine")
def refine(req: RefineRequest):
    """User rejected a result. Identify similar items via LLM, refine the search,
    and return the new result set plus the metadata needed to keep refining."""
    try:
        refinement = refine_after_rejection(
            req.rejected, req.candidates, req.classification
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"LLM-Verfeinerung fehlgeschlagen: {e}")

    clf = dict(req.classification)
    if refinement.get("thema_refined"):
        clf["thema"] = refinement["thema_refined"]

    negative_keywords = list(req.prior_negative_keywords or [])
    for kw in refinement.get("negative_keywords") or []:
        if kw and kw not in negative_keywords:
            negative_keywords.append(kw)

    exclude_ids = list(req.prior_exclude_ids or [])
    for rid in refinement.get("similar_ids") or []:
        if rid and rid not in exclude_ids:
            exclude_ids.append(rid)

    thema = clf.get("thema") or ""
    format_preferred = clf.get("format_preferred")
    fmt_hint = " ".join(format_preferred) if isinstance(format_preferred, list) else (format_preferred or "")
    search_text = f"{thema} {fmt_hint}".strip() if fmt_hint else thema
    language = clf.get("language")

    try:
        raw = simple_search(
            search_text,
            size=req.size * 3,
            lang=language,
            negative_keywords=negative_keywords,
            exclude_ids=exclude_ids,
        )
        hits = [h["_source"] for h in raw["hits"]["hits"]]
    except Exception:
        hits = _fallback_search(search_text, req.size * 3)
        excl = set(exclude_ids)
        hits = [h for h in hits if (h.get("id") or h.get("@id")) not in excl]

    hits = _filter_by_format(hits, format_preferred)[:req.size]

    visualization = _get_visualization(clf.get("intention", "Überblick erarbeiten"))

    return {
        "results": hits,
        "visualization": visualization,
        "total": len(hits),
        "source": "oersi",
        "classification": clf,
        "similar_ids": refinement.get("similar_ids", []),
        "negative_keywords": negative_keywords,
        "exclude_ids": exclude_ids,
        "thema_refined": refinement.get("thema_refined"),
    }


@app.get("/visualization/{intention}")
def get_visualization(intention: str):
    return {"intention": intention, "visualization": _get_visualization(intention)}


def _get_visualization(intention: str) -> dict:
    taxonomy = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    entry = taxonomy["zuordnungsmatrix"].get(intention, {"primary": "V6", "fallback": "V6", "last_resort": "V6"})
    catalog = {v["id"]: v for v in taxonomy["visualisierungskatalog"]}
    primary = catalog.get(entry["primary"], {})
    return {"id": entry["primary"], "name": primary.get("name", "Liste"), "fallback": entry["fallback"]}


def _fallback_search(text: str, size: int) -> list[dict]:
    corpus = json.loads(TWILLO_PATH.read_text(encoding="utf-8"))
    items = corpus if isinstance(corpus, list) else corpus.get("hits", [])
    text_lower = text.lower()
    matches = [
        item for item in items
        if text_lower in json.dumps(item, ensure_ascii=False).lower()
    ]
    return matches[:size] or items[:size]
