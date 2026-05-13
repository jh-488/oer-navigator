import asyncio
import json
import logging
import time
from datetime import datetime, timezone

import websockets

RELAY_URL = "wss://relay.edufeed.org"
CONNECT_TIMEOUT = 8
_cache: dict = {"events": [], "fetched_at": 0.0}
CACHE_TTL = 600  # 10 minutes

logger = logging.getLogger(__name__)


async def _fetch_all_events() -> list[dict]:
    """Fetch all Kind 31923 events from the relay. Returns raw event dicts."""
    results = []
    sub_id = "oer-nav-events"
    req = json.dumps(["REQ", sub_id, {"kinds": [31923], "limit": 500}])

    try:
        async with websockets.connect(RELAY_URL, open_timeout=CONNECT_TIMEOUT) as ws:
            await ws.send(req)
            while True:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=CONNECT_TIMEOUT)
                except asyncio.TimeoutError:
                    break
                data = json.loads(msg)
                if data[0] == "EVENT" and data[1] == sub_id:
                    results.append(data[2])
                elif data[0] == "EOSE":
                    break
    except Exception as e:
        logger.warning("NOSTR relay unreachable: %s", e)

    return results


async def _get_cached_events() -> list[dict]:
    now = time.monotonic()
    if now - _cache["fetched_at"] < CACHE_TTL and _cache["events"]:
        return _cache["events"]
    events = await _fetch_all_events()
    if events:
        _cache["events"] = events
        _cache["fetched_at"] = now
    return _cache["events"]


def _tag_value(tags: list, name: str) -> str | None:
    for t in tags:
        if t and t[0] == name and len(t) > 1:
            return t[1]
    return None


def _tag_values(tags: list, name: str) -> list[str]:
    return [t[1] for t in tags if t and t[0] == name and len(t) > 1]


def _parse_event(raw: dict) -> dict:
    tags = raw.get("tags", [])
    start_ts = _tag_value(tags, "start")
    end_ts = _tag_value(tags, "end")

    def _fmt(ts: str | None) -> str | None:
        if not ts:
            return None
        try:
            return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        except (ValueError, OSError):
            return None

    return {
        "type": "event",
        "title": _tag_value(tags, "title") or "",
        "summary": _tag_value(tags, "summary") or raw.get("content", "")[:300],
        "content": raw.get("content", ""),
        "start": _fmt(start_ts),
        "end": _fmt(end_ts),
        "location": _tag_value(tags, "location") or "",
        "url": _tag_value(tags, "r") or "",
        "tags": _tag_values(tags, "t"),
        "pubkey": raw.get("pubkey", ""),
    }


def _matches(event: dict, topic: str) -> bool:
    words = [w for w in topic.lower().split() if len(w) > 2]
    if not words:
        return False
    haystack = " ".join([
        event.get("title", ""),
        event.get("summary", ""),
        event.get("content", ""),
    ]).lower()
    return any(w in haystack for w in words)


async def search_events(topic: str, limit: int = 10) -> list[dict]:
    """Return parsed Kind 31923 events whose text fields match the topic."""
    if not topic:
        return []
    try:
        raw_events = await _get_cached_events()
        parsed = [_parse_event(e) for e in raw_events]
        matches = [e for e in parsed if _matches(e, topic)]
        return matches[:limit]
    except Exception as e:
        logger.warning("search_events failed: %s", e)
        return []


async def search_persons(topic: str, limit: int = 5) -> list[dict]:
    """Return Kind 0 profiles of authors who published events matching the topic."""
    if not topic:
        return []
    try:
        raw_events = await _get_cached_events()
        pubkeys = list({
            e["pubkey"] for e in raw_events
            if _matches(_parse_event(e), topic) and e.get("pubkey")
        })[:limit * 2]

        if not pubkeys:
            return []

        profiles = []
        sub_id = "oer-nav-profiles"
        req = json.dumps(["REQ", sub_id, {"kinds": [0], "authors": pubkeys, "limit": limit * 2}])

        async with websockets.connect(RELAY_URL, open_timeout=CONNECT_TIMEOUT) as ws:
            await ws.send(req)
            while True:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=CONNECT_TIMEOUT)
                except asyncio.TimeoutError:
                    break
                data = json.loads(msg)
                if data[0] == "EVENT" and data[1] == sub_id:
                    ev = data[2]
                    try:
                        meta = json.loads(ev.get("content", "{}"))
                    except json.JSONDecodeError:
                        meta = {}
                    profiles.append({
                        "type": "person",
                        "name": meta.get("display_name") or meta.get("name", ""),
                        "about": meta.get("about", ""),
                        "picture": meta.get("picture", ""),
                        "pubkey": ev.get("pubkey", ""),
                        "nip05": meta.get("nip05", ""),
                    })
                elif data[0] == "EOSE":
                    break

        return profiles[:limit]
    except Exception as e:
        logger.warning("search_persons failed: %s", e)
        return []
