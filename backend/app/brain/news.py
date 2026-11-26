"""Optional headlines from one RSS feed. Works offline from the last saved copy.

Only titles are read; nothing about the user is sent. Network use is bounded: one request,
a short timeout, at most 1 MB, and results are cached for `cache_minutes`.
"""
import json
import logging
import time
import urllib.request
import xml.etree.ElementTree as ET

from ..config import AVATAR_DATA
from ..settings import get_settings

log = logging.getLogger("brain.news")
MAX_BYTES = 1024 * 1024


def _fetch(url, timeout):
    request = urllib.request.Request(url, headers={"User-Agent": "LivingFrame/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("News feed too large")
    titles = []
    for item in ET.fromstring(data).iter("item"):
        title = (item.findtext("title") or "").strip()
        # Google News appends " - Source"; keep only the headline itself.
        if " - " in title:
            title = title.rsplit(" - ", 1)[0].strip()
        if title and title not in titles:
            titles.append(title[:160])
    return titles


def headlines(language="en"):
    """Return (titles, fetched_at_epoch, is_fresh) — titles may be [] if never fetched.
    Hindi conversations use the Hindi feed, so the Hindi voice reads Devanagari headlines."""
    cfg = get_settings()["news"]
    url = cfg["feed_url_hi"] if language == "hi" and cfg["feed_url_hi"] else cfg["feed_url"]
    cache = AVATAR_DATA / ("news_cache_hi.json" if url == cfg["feed_url_hi"] else "news_cache.json")
    cached = {}
    try:
        cached = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    age_ok = cached.get("fetched_at", 0) > time.time() - cfg["cache_minutes"] * 60
    if cached.get("titles") and age_ok:
        return cached["titles"][:cfg["max_items"]], cached["fetched_at"], True
    if cfg["enabled"] and url:
        try:
            titles = _fetch(url, cfg["timeout_seconds"])
            if titles:
                cached = {"titles": titles[:20], "fetched_at": time.time()}
                try:
                    cache.write_text(json.dumps(cached, ensure_ascii=False), encoding="utf-8")
                except OSError:
                    pass
                return titles[:cfg["max_items"]], cached["fetched_at"], True
        except Exception as error:  # offline, DNS failure, bad XML: fall back to the saved copy
            log.info("News unavailable (%s); using saved headlines if any", type(error).__name__)
    return cached.get("titles", [])[:cfg["max_items"]], cached.get("fetched_at"), False
