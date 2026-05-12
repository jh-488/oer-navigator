"""
OERSI API client with local disk caching.
Endpoint: https://oersi.org/api/search/oer_data/_search (Elasticsearch DSL, POST)
"""

import hashlib
import json
import time
from pathlib import Path
import requests

OERSI_URL = "https://oersi.org/api/search/oer_data/_search"
OERSI_PIT_URL = "https://oersi.org/api/search/oer_data/_pit"
USER_AGENT = "OER-Navigator/0.1 (HackathOERn2026)"

CACHE_DIR = Path(__file__).parent.parent / "cache"
CACHE_TTL = 60 * 60 * 24  # 24 hours


def _cache_path(key: str) -> Path:
    digest = hashlib.sha256(key.encode()).hexdigest()[:16]
    return CACHE_DIR / f"{digest}.json"


def _load_cache(key: str) -> dict | None:
    p = _cache_path(key)
    if not p.exists():
        return None
    meta = json.loads(p.read_text())
    if time.time() - meta["ts"] > CACHE_TTL:
        return None
    return meta["data"]


def _save_cache(key: str, data: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(key).write_text(json.dumps({"ts": time.time(), "data": data}))


def search(query: dict, use_cache: bool = True) -> dict:
    """
    Send an Elasticsearch DSL query to OERSI and return the response dict.
    Results are cached by query body for 24 hours.
    """
    key = json.dumps(query, sort_keys=True)
    if use_cache:
        cached = _load_cache(key)
        if cached is not None:
            return cached

    resp = requests.post(
        OERSI_URL,
        json=query,
        headers={
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    if use_cache:
        _save_cache(key, data)

    return data


def simple_search(text: str, size: int = 10, lang: str | None = None) -> dict:
    """Convenience wrapper: full-text search across name, description, keywords."""
    must = [
        {
            "multi_match": {
                "query": text,
                "fields": ["name^3", "description", "keywords^2"],
                "type": "best_fields", 
                # Finds documents that match the query in any of the specified fields, but scores them based on the best matching field. 
                # The ^3 and ^2 boost the importance of matches in 'name' and 'keywords' respectively.
            }
        }
    ]
    if lang:
        must.append({"term": {"inLanguage": lang}})

    return search(
        {
            "size": size,
            "query": {"bool": {"must": must}},
            "sort": [{"_score": "desc"}],
        }
    )


def get_total_count() -> int:
    """Get total number of OER resources in OERSI."""
    result = search({"size": 0, "query": {"match_all": {}}})
    # To get accurate count: search({"size": 0, "track_total_hits": True, "query": {"match_all": {}}}, use_cache=False)
    return result["hits"]["total"]["value"]


def bulk_download(query: dict, page_size: int = 500) -> list[dict]:
    """
    Download all matching documents using PIT (point-in-time) pagination.
    Use for building a local backup corpus.
    """
    # Create PIT
    pit_resp = requests.post(
        f"{OERSI_PIT_URL}?keep_alive=5m",
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    pit_resp.raise_for_status()
    pit_id = pit_resp.json()["id"]

    results = []
    search_after = None

    try:
        while True:
            body = {
                **query,
                "size": page_size,
                "pit": {"id": pit_id, "keep_alive": "5m"},
                "sort": [{"id": "asc"}],
            }
            if search_after:
                body["search_after"] = search_after

            resp = requests.post(
                "https://oersi.org/api/search/_search",
                json=body,
                headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            hits = data["hits"]["hits"]
            if not hits:
                break
            results.extend(h["_source"] for h in hits)
            search_after = hits[-1]["sort"]
    finally:
        requests.delete(
            "https://oersi.org/api/search/_pit",
            json={"id": pit_id},
            headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
            timeout=10,
        )

    return results


if __name__ == "__main__":
    print(f"Total OER resources in OERSI: {get_total_count():,}")
    hits = simple_search("maschinelles Lernen", size=3)
    for h in hits["hits"]["hits"]:
        s = h["_source"]
        lrt = s.get("learningResourceType", [{}])
        fmt = lrt[0].get("prefLabel", {}).get("de", "?") if lrt else "?"
        print(f"- [{fmt}] {s.get('name', '?')} ({s.get('inLanguage', '?')})")
