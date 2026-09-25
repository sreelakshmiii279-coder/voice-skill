"""Google News: recent industry headlines on a note's topic, offered to the
drafting step as a possible hook.

Uses Google News' public RSS search feed, which needs no API key. Any failure
just means no headlines — drafting never waits on or fails because of news.
"""

import logging
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

import requests

FEED_URL = "https://news.google.com/rss/search"
# Skinstinct is an Indian brand, so ask for the Indian English edition.
EDITION = {"hl": "en-IN", "gl": "IN", "ceid": "IN:en"}

log = logging.getLogger(__name__)


def recent_headlines(query, limit=8, days=30):
    """Returns up to `limit` dicts with title, source, date and link."""
    if not query.strip():
        return []
    try:
        resp = requests.get(
            FEED_URL,
            params={"q": f"{query} when:{days}d", **EDITION},
            headers={"User-Agent": "Mozilla/5.0 (compatible; meera-drafts bot)"},
            timeout=8,
        )
        resp.raise_for_status()
        root = ElementTree.fromstring(resp.content)
    except (requests.RequestException, ElementTree.ParseError) as e:
        log.warning("Google News lookup failed for %r: %s", query, e)
        return []

    headlines = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        source = (item.findtext("source") or "").strip()
        # Google appends " - <outlet>" to every title.
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3].strip()
        try:
            date = parsedate_to_datetime(item.findtext("pubDate") or "").strftime("%d %b %Y")
        except (TypeError, ValueError):
            date = ""
        if title:
            headlines.append({"title": title, "source": source, "date": date, "link": (item.findtext("link") or "").strip()})
        if len(headlines) >= limit:
            break
    return headlines
