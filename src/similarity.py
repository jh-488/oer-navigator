"""
LLM-based similarity + query refinement for rejected search results.

Given a rejected OER item and the current candidate list, asks the LLM to
identify conceptually similar items in the candidate set and to propose a
refined search query (negative keywords plus an optionally adjusted thema)
that should produce more relevant follow-up results.

Uses the same DWGD → Ollama → Gemini provider stack as src.classifier.
"""

import json
import logging
import re
from typing import Any

from openai import OpenAI

from src.classifier import (
    DWGD_API_KEY,
    DWGD_BASE_URL,
    DWGD_MODEL,
    GEMINI_API_KEY,
    GEMINI_BASE_URL,
    GEMINI_MODEL,
    GEMINI_FALLBACK_MODEL,
    OLLAMA_MODEL,
    OLLAMA_URL,
    _chat_json,
    _ollama_available,
)

logger = logging.getLogger(__name__)


def _item_digest(item: dict, index: int) -> dict:
    """Trim an OERSI hit down to the fields the LLM needs."""
    lrt = item.get("learningResourceType") or []
    fmt = ""
    if lrt:
        labels = lrt[0].get("prefLabel") or {}
        fmt = labels.get("de") or labels.get("en") or ""

    desc = item.get("description") or item.get("abstract") or ""
    if isinstance(desc, list):
        desc = " ".join(str(d) for d in desc)
    desc = str(desc)[:240]

    return {
        "index": index,
        "id": item.get("id") or item.get("@id") or f"idx-{index}",
        "name": item.get("name") or "",
        "description": desc,
        "format": fmt,
        "language": item.get("inLanguage") or "",
    }


def _build_prompt(rejected: dict, candidates: list[dict], classification: dict) -> str:
    rej = _item_digest(rejected, -1)
    cand = [_item_digest(c, i) for i, c in enumerate(candidates)]

    thema = classification.get("thema") or ""
    intention = classification.get("intention") or ""
    format_preferred = classification.get("format_preferred") or ""

    return f"""Du hilfst bei einer OER-Suche. Der Nutzer hat EIN Ergebnis abgelehnt, möchte aber WEITER zum gleichen Thema "{thema}" suchen.

Suchprofil (MUSS erhalten bleiben):
- thema: {thema}
- intention: {intention}
- format_preferred: {format_preferred}

Abgelehntes Ergebnis:
{json.dumps(rej, ensure_ascii=False, indent=2)}

Aktuelle Kandidaten (Index + Metadaten):
{json.dumps(cand, ensure_ascii=False, indent=2)}

Wichtige Regeln:
- Das Thema "{thema}" bleibt der Kern der Suche. Entferne es NICHT.
- "negative_keywords" sind NUR enge Sub-Konzepte (z.B. ein bestimmter Begriff, der das abgelehnte Ergebnis charakterisiert und auch andere Kandidaten betrifft) — KEINE Wörter aus dem Thema "{thema}" selbst, KEINE generischen Begriffe (Mathematik, Lernen, Kurs, Video).
- "similar_indexes" sind nur Kandidaten, die im SELBEN engen Sub-Konzept wie das abgelehnte Ergebnis liegen. Wenn nur das abgelehnte Ergebnis dieses Sub-Konzept abdeckt, gib eine leere Liste zurück.
- "thema_refined" nur setzen, wenn das ursprüngliche Thema "{thema}" darin wortwörtlich enthalten ist und es lediglich präzisiert (z.B. um eine Facette einzugrenzen). Sonst null.
- Im Zweifel lieber konservativ: leere Listen / null sind valide Antworten.

Beispiel: thema="Zahlen", abgelehnt="Komplexe Zahlen I". Dann ist "negative_keywords": ["komplexe Zahlen"] korrekt — NICHT ["Zahlen"]. "similar_indexes" enthält die anderen "Komplexe Zahlen"-Treffer, NICHT "Reelle Zahlen" oder "Natürliche Zahlen". "thema_refined" bleibt null.

Antworte NUR mit folgendem JSON, ohne erklärenden Text:
{{
  "similar_indexes": [<int>, ...],
  "negative_keywords": [<string>, ...],
  "thema_refined": <string oder null>
}}
"""


def refine_after_rejection(
    rejected: dict,
    candidates: list[dict],
    classification: dict,
) -> dict[str, Any]:
    """Ask the LLM which candidates are similar to the rejected one and how to refine the query.

    Returns dict with keys: similar_ids (list[str]), negative_keywords (list[str]),
    thema_refined (str | None).
    """
    if not candidates:
        return {"similar_ids": [], "negative_keywords": [], "thema_refined": None}

    prompt = _build_prompt(rejected, candidates, classification)
    raw = None
    last_error = None

    # --- DWGD chat-ai (OpenAI-compatible endpoint) ---
    if DWGD_API_KEY:
        try:
            logger.info("similarity: trying DWGD model=%s", DWGD_MODEL)
            dwgd = OpenAI(api_key=DWGD_API_KEY, base_url=DWGD_BASE_URL)
            raw = _chat_json(dwgd, DWGD_MODEL, prompt)
        except Exception as e:
            logger.warning("similarity: DWGD model=%s failed: %s", DWGD_MODEL, e)
            last_error = e

    # --- Ollama fallback ---
    if raw is None and _ollama_available():
        try:
            logger.info("similarity: falling back to Ollama model=%s", OLLAMA_MODEL)
            ollama = OpenAI(api_key="ollama", base_url=f"{OLLAMA_URL}/v1")
            raw = _chat_json(ollama, OLLAMA_MODEL, prompt)
        except Exception as e:
            logger.warning("similarity: Ollama model=%s failed: %s", OLLAMA_MODEL, e)
            last_error = e

    # --- Gemini fallback ---
    if raw is None and GEMINI_API_KEY:
        gemini = OpenAI(api_key=GEMINI_API_KEY, base_url=GEMINI_BASE_URL)
        for model in (GEMINI_MODEL, GEMINI_FALLBACK_MODEL):
            try:
                logger.info("similarity: trying Gemini model=%s", model)
                raw = _chat_json(gemini, model, prompt)
                break
            except Exception as e:
                logger.warning("similarity: Gemini model=%s failed: %s", model, e)
                last_error = e

    if raw is None:
        raise last_error or RuntimeError("No LLM backend available")

    raw = re.sub(r"^```(?:json)?\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    parsed = json.loads(raw)

    indexes = parsed.get("similar_indexes") or []
    similar_ids: list[str] = []
    for idx in indexes:
        if isinstance(idx, int) and 0 <= idx < len(candidates):
            c = candidates[idx]
            cid = c.get("id") or c.get("@id")
            if cid:
                similar_ids.append(cid)

    rejected_id = rejected.get("id") or rejected.get("@id")
    if rejected_id and rejected_id not in similar_ids:
        similar_ids.append(rejected_id)

    thema = (classification.get("thema") or "").strip()
    thema_tokens = {t for t in re.split(r"\W+", thema.lower()) if len(t) > 2}

    raw_negatives = [str(k).strip() for k in (parsed.get("negative_keywords") or []) if k]
    negatives: list[str] = []
    for kw in raw_negatives:
        kw_lower = kw.lower()
        if not kw_lower:
            continue
        # Drop the thema itself and single-token negatives that ARE the thema
        if thema and (kw_lower == thema.lower() or kw_lower in thema.lower()):
            logger.info("similarity: dropping negative keyword '%s' (matches thema)", kw)
            continue
        kw_tokens = {t for t in re.split(r"\W+", kw_lower) if len(t) > 2}
        # Single-word negative that's a thema token would wipe the topic — drop it
        if len(kw_tokens) == 1 and kw_tokens.issubset(thema_tokens):
            logger.info("similarity: dropping single-token negative '%s' (is thema token)", kw)
            continue
        negatives.append(kw)

    thema_refined = parsed.get("thema_refined")
    if thema_refined:
        thema_refined = str(thema_refined).strip()
        # Only accept refined thema if it still mentions the original core
        if thema and thema.lower() not in thema_refined.lower():
            logger.info(
                "similarity: discarding thema_refined='%s' (loses original thema '%s')",
                thema_refined, thema,
            )
            thema_refined = None
    else:
        thema_refined = None

    return {
        "similar_ids": similar_ids,
        "negative_keywords": negatives,
        "thema_refined": thema_refined,
    }
