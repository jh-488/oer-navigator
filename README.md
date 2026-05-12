# NavigatOER — Laligator findet OER-Materialien

KI-gestützte Suche nach Open Educational Resources (OER) für Lehrende und Lernende.

🌐 **Live:** [jh-488.github.io/oer-navigator](https://jh-488.github.io/oer-navigator/)

---

## Was ist NavigatOER?

NavigatOER ist ein intelligenter OER-Navigator, der Nutzer durch gezielte Rückfragen ein Suchprofil aufbaut und passende Lernmaterialien aus dem [OERSI](https://oersi.org)-Katalog empfiehlt. Das Persona-System erkennt, ob jemand als Lehrende/r oder Lernende/r sucht, und passt die Ergebnisse entsprechend an.

## Architektur

```
frontend/   → Statische Web-App (GitHub Pages)
src/        → FastAPI-Backend (Render)
data/       → Evaluierungskorpus & Hilfsdaten
```

| Komponente | Technologie |
|---|---|
| Frontend | HTML / CSS / Vanilla JS / D3.js |
| Backend | Python · FastAPI · Uvicorn |
| LLM | DWGD API (Meta Llama 3.1 70B) |
| OER-Katalog | OERSI REST API |
| Hosting Frontend | GitHub Pages |
| Hosting Backend | Render |

## Lokale Entwicklung

**Backend:**
```bash
pip install -r requirements.txt
cp .env.example .env   # API-Key eintragen
uvicorn src.api:app --reload
```

**Frontend:**  
`frontend/index.html` direkt im Browser öffnen oder einen lokalen Server starten:
```bash
cd frontend && python -m http.server 8080
```

Sicherstellen, dass in `frontend/config.js` die lokale URL aktiv ist:
```js
const API_BASE_URL = "http://localhost:8000";
```

## Deployment

- **Frontend:** `git subtree push --prefix frontend origin gh-pages` → GitHub Pages (Branch `gh-pages`) *oder* `docs/`-Ordner auf `main`
- **Backend:** Render erkennt `render.yaml` automatisch. `DWGD_API_KEY` muss manuell im Render-Dashboard gesetzt werden.

## Umgebungsvariablen

| Variable | Beschreibung |
|---|---|
| `DWGD_API_KEY` | API-Key für den LLM-Dienst |
| `DWGD_MODEL` | Modellname (Standard: `meta-llama-3.1-70b-instruct`) |
| `OLLAMA_MODEL` | Lokales Modell für Offline-Betrieb |

