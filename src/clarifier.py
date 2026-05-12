import json
from pathlib import Path

VORLAGEN_PATH = Path(__file__).parent.parent / "data" / "rueckfrage_vorlagen.json"


def _load_vorlagen() -> dict:
    with open(VORLAGEN_PATH, encoding="utf-8") as f:
        return json.load(f)


def get_next_question(classification: dict) -> dict | None:
    """Return the single most important clarifying question, or None if everything is clear.

    Picks the highest-priority unclear axis and returns its question template.
    """
    unclear_axes = classification.get("unclear_axes", [])
    if not unclear_axes:
        return None

    vorlagen = _load_vorlagen()
    priority = vorlagen["achsen_prioritaet"]

    # pick the highest-priority unclear axis
    chosen_axis = next(
        (axis for axis in priority if axis in unclear_axes),
        unclear_axes[0],
    )

    vorlage = vorlagen["vorlagen"].get(chosen_axis)
    if not vorlage:
        return None

    return {
        "axis": chosen_axis,
        "frage": vorlage["frage"],
        "optionen": vorlage["optionen"],
    }


def apply_answer(classification: dict, axis: str, answer: str) -> dict:
    """Merge a user's clarification answer back into the classification dict."""
    updated = classification.copy()

    if axis == "vorwissen" and answer.startswith("Einsteiger"):
        updated["vorwissen"] = "Einsteiger"
    elif axis == "vorwissen" and answer.startswith("Fortgeschrittene"):
        updated["vorwissen"] = "Fortgeschrittene"
    elif axis == "vorwissen" and answer.startswith("Experte"):
        updated["vorwissen"] = "Experte"
    elif axis == "intention":
        updated["intention"] = answer
    elif axis == "rolle":
        if "Selbstlernen" in answer:
            updated["rolle"] = "Lernende"
        elif "Unterricht" in answer or "Lehre" in answer:
            updated["rolle"] = "Lehrende"
        elif "Forschung" in answer:
            updated["rolle"] = "Forschende"
    elif axis == "bildungsstufe":
        updated["bildungsstufe"] = answer
    elif axis == "einsatzkontext":
        updated["einsatzkontext"] = answer
    elif axis == "suchmodus":
        updated["suchmodus"] = answer.split(" (", 1)[0]
    elif axis == "format_preferred":
        updated["format_preferred"] = None if answer == "Kein Unterschied" else answer
    elif axis == "language":
        mapping = {"Deutsch": "de", "Englisch": "en", "Beides / egal": None}
        updated["language"] = mapping.get(answer, answer)
    elif axis == "ergebnistypen":
        mapping = {
            "Nur Lernmaterialien": ["Materialien"],
            "Materialien + Veranstaltungen": ["Materialien", "Events"],
            "Materialien + Personen / Communities": ["Materialien", "Personen"],
            "Alles": ["Materialien", "Events", "Personen"],
        }
        updated["ergebnistypen"] = mapping.get(answer, updated.get("ergebnistypen", ["Materialien"]))
    else:
        updated[axis] = answer

    # raise confidence for the answered axis and remove from unclear_axes
    if "confidence" in updated:
        updated["confidence"][axis] = 1.0
    updated["unclear_axes"] = [a for a in updated.get("unclear_axes", []) if a != axis]

    return updated


if __name__ == "__main__":
    # demo: simulate one clarification turn
    sample_classification = {
        "intention": "Überblick erarbeiten",
        "vorwissen": "Einsteiger",
        "rolle": "Lernende",
        "bildungsstufe": "Bachelor",
        "einsatzkontext": "Selbststudium",
        "suchmodus": "Explorativ",
        "thema": "Mathematik Beweise",
        "format_preferred": None,
        "language": "de",
        "ergebnistypen": ["Materialien"],
        "confidence": {
            "intention": 0.95,
            "vorwissen": 0.85,
            "rolle": 0.9,
            "bildungsstufe": 0.9,
            "einsatzkontext": 0.85,
            "suchmodus": 0.9,
            "thema": 0.9,
            "format_preferred": 0.6,
            "language": 0.95,
            "ergebnistypen": 0.8,
        },
        "unclear_axes": ["format_preferred"],
    }

    question = get_next_question(sample_classification)
    print("Rückfrage:", json.dumps(question, indent=2, ensure_ascii=False))

    updated = apply_answer(sample_classification, question["axis"], "Video")
    print("\nNach Antwort 'Video':")
    print(json.dumps(updated, indent=2, ensure_ascii=False))
    print("\nNoch unklare Achsen:", updated["unclear_axes"])
