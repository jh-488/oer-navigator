import json
import os
import re
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from google import genai

load_dotenv(Path(__file__).parent.parent / ".env")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY_HERE")
GEMINI_MODEL = "models/gemini-2.5-flash-lite"

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


def classify(query: str) -> dict:
    """Classify a natural-language OER search query into a structured situation profile."""
    client = genai.Client(api_key=GEMINI_API_KEY)

    examples = _load_few_shot_examples()
    prompt = _build_prompt(query, examples)

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config={"temperature": 0.1, "response_mime_type": "application/json"},
    )

    raw = response.text.strip()
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
