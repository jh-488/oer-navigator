import json
import logging
import os
import re
import urllib.request
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

logger = logging.getLogger(__name__)

load_dotenv(Path(__file__).parent.parent / ".env")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY_HERE")
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
GEMINI_MODEL = "gemini-2.5-flash-lite"
GEMINI_FALLBACK_MODEL = "gemini-2.0-flash-lite"

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")

EVAL_CORPUS_PATH = Path(__file__).parent.parent / "data" / "eval_corpus.json"

CONFIDENCE_THRESHOLD = 0.7

VALID_INTENTIONS = ["orientieren", "problemlösung", "eigenschaftssuche", "recherche", "problemorientiert"]
VALID_VORWISSEN = ["Einsteiger", "Fortgeschrittene", "Experte"]
VALID_ROLLEN = ["Lernende", "Lehrende", "Forschende"]
VALID_ERGEBNISTYPEN = ["Materialien", "Events", "Personen"]


def _load_few_shot_examples() -> list[dict]:
    with open(EVAL_CORPUS_PATH, encoding="utf-8") as f:
        corpus = json.load(f)
    return corpus["queries"]


def _build_prompt(query: str, examples: list[dict]) -> str:
    few_shot_block = ""
    for ex in examples:
        e = ex["expected"]
        few_shot_block += f"""
Anfrage: "{ex['natural_language']}"
Ausgabe:
{{
  "intention": "{e['intention']}",
  "vorwissen": "{e['vorwissen']}",
  "rolle": "{e['rolle']}",
  "thema": {json.dumps(e['thema'], ensure_ascii=False)},
  "format_preferred": {json.dumps(e['format_preferred'], ensure_ascii=False)},
  "language": {json.dumps(e['language'], ensure_ascii=False)},
  "ergebnistypen": {json.dumps(e['ergebnistypen'], ensure_ascii=False)},
  "confidence": {{
    "intention": 0.92,
    "vorwissen": 0.80,
    "thema": 0.88,
    "format_preferred": 0.75
  }}
}}
"""

    return f"""Du bist ein Klassifikator für OER-Suchanfragen. Analysiere die natürlichsprachliche Suchanfrage und gib ein strukturiertes JSON-Objekt zurück.

Mögliche Werte:
- intention: {VALID_INTENTIONS}
- vorwissen: {VALID_VORWISSEN}
- rolle: {VALID_ROLLEN}
- ergebnistypen: Teilmenge von {VALID_ERGEBNISTYPEN}
- language: ISO-639-1 Code (z.B. "de", "en") oder null wenn mehrsprachig
- thema: kurze Themenbeschreibung oder null wenn unklar
- format_preferred: z.B. "Video", "Methode", "Skript", "Übung" oder null

Confidence-Werte zwischen 0.0 und 1.0 für jede Achse. Werte unter {CONFIDENCE_THRESHOLD} signalisieren Unklarheit → Rückfrage nötig.

Antworte NUR mit dem JSON-Objekt, kein erklärender Text.

Beispiele:
{few_shot_block}
Anfrage: "{query}"
Ausgabe:"""


def _ollama_available() -> bool:
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def _chat_json(client: OpenAI, model: str, prompt: str) -> str:
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    return response.choices[0].message.content.strip()


def classify(query: str) -> dict:
    """Classify a natural-language OER search query.

    Tries Gemini models first, falls back to local Ollama if all Gemini calls fail.
    Both providers are accessed via their OpenAI-compatible endpoints.
    """
    examples = _load_few_shot_examples()
    prompt = _build_prompt(query, examples)
    raw = None
    last_error = None

    # --- Gemini (OpenAI-compatible endpoint) ---
    gemini = OpenAI(api_key=GEMINI_API_KEY, base_url=GEMINI_BASE_URL)
    for model in (GEMINI_MODEL, GEMINI_FALLBACK_MODEL):
        try:
            logger.info("classify: trying Gemini model=%s", model)
            raw = _chat_json(gemini, model, prompt)
            logger.info("classify: succeeded with Gemini model=%s", model)
            break
        except Exception as e:
            logger.warning("classify: Gemini model=%s failed: %s", model, e)
            last_error = e

    # --- Ollama fallback (OpenAI-compatible endpoint) ---
    if raw is None:
        if _ollama_available():
            logger.info("classify: falling back to Ollama model=%s at %s", OLLAMA_MODEL, OLLAMA_URL)
            ollama = OpenAI(api_key="ollama", base_url=f"{OLLAMA_URL}/v1")
            raw = _chat_json(ollama, OLLAMA_MODEL, prompt)
            logger.info("classify: succeeded with Ollama model=%s", OLLAMA_MODEL)
        else:
            logger.error("classify: Ollama unavailable at %s, no fallback possible", OLLAMA_URL)
            raise last_error

    raw = re.sub(r"^```(?:json)?\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)

    result = json.loads(raw)
    result["unclear_axes"] = _find_unclear_axes(result)
    return result


def _find_unclear_axes(result: dict) -> list[str]:
    """Return axes whose confidence is below the threshold."""
    confidence = result.get("confidence", {})
    return [axis for axis, score in confidence.items() if score < CONFIDENCE_THRESHOLD]


def needs_clarification(classification: dict) -> bool:
    return len(classification.get("unclear_axes", [])) > 0


if __name__ == "__main__":
    import sys

    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Grundstudium Mathematik Vorkurs Beweise — wo fange ich an?"
    print(f"Query: {query}\n")
    result = classify(query)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if needs_clarification(result):
        print(f"\n→ Rückfrage nötig für: {result['unclear_axes']}")
    else:
        print("\n→ Klassifikation eindeutig, keine Rückfrage nötig.")
