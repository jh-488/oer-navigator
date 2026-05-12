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
from src.oersi_client import simple_search

TWILLO_PATH = Path(__file__).parent.parent / "data" / "twillo_corpus.json"
TAXONOMY_PATH = Path(__file__).parent.parent / "data" / "situations_taxonomy.json"

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


@app.post("/classify")
def classify_query(req: QueryRequest):
    try:
        result = classify(req.query)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"LLM nicht erreichbar: {e}")
    question = get_next_question(result) if needs_clarification(result) else None
    return {"classification": result, "clarification_needed": question is not None, "question": question}


@app.post("/clarify")
def clarify(req: ClarifyRequest):
    updated = apply_answer(req.classification, req.axis, req.answer)
    question = get_next_question(updated) if needs_clarification(updated) else None
    return {"classification": updated, "clarification_needed": question is not None, "question": question}


@app.post("/search")
def search(req: SearchRequest):
    clf = req.classification
    thema = clf.get("thema") or ""
    language = clf.get("language")
    format_preferred = clf.get("format_preferred")

    search_text = thema
    if format_preferred:
        search_text = f"{thema} {format_preferred}".strip()

    try:
        raw = simple_search(search_text, size=req.size, lang=language)
        hits = [h["_source"] for h in raw["hits"]["hits"]]
    except Exception:
        hits = _fallback_search(search_text, req.size)

    visualization = _get_visualization(clf.get("intention", "orientieren"))

    return {
        "results": hits,
        "visualization": visualization,
        "total": len(hits),
        "source": "oersi",
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
