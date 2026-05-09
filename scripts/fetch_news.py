#!/usr/bin/env python3
"""
Fetches AI-in-finance news from RSS feeds, merges with existing articles.json,
deduplicates by title similarity, and writes the updated file.
"""

import json
import re
import sys
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path

DATA_FILE = Path("data/articles.json")

RSS_FEEDS = [
    ("Reuters Business", "https://feeds.reuters.com/reuters/businessNews"),
    ("Reuters Technology", "https://feeds.reuters.com/reuters/technologyNews"),
    ("Financial Times", "https://www.ft.com/rss/home"),
    ("Finextra", "https://www.finextra.com/rss/headlines.aspx"),
    ("American Banker", "https://feeds.americanbanker.com/americanbanker/breakingnews"),
    ("VentureBeat AI", "https://venturebeat.com/category/ai/feed/"),
    ("MIT Tech Review", "https://www.technologyreview.com/feed/"),
    ("The Fintech Times", "https://thefintechtimes.com/feed/"),
    ("Coindesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Pymnts", "https://www.pymnts.com/feed/"),
]

AI_KEYWORDS = [
    r"\bai\b", r"\bartificial intelligence\b", r"\bmachine learning\b",
    r"\bdeep learning\b", r"\bllm\b", r"\blarge language model\b",
    r"\bgenerative ai\b", r"\bneural network\b", r"\balgorithm(?:ic)?\b",
    r"\bautomat(?:ed|ion)\b", r"\bpredictive\b", r"\bnatural language\b",
    r"\bcomputer vision\b", r"\btransformer model\b", r"\bai[- ]driven\b",
    r"\bai[- ]powered\b", r"\bai[- ]agent\b", r"\bcopilot\b",
]

FINANCE_KEYWORDS = [
    r"\bbank(?:ing)?\b", r"\bfinance\b", r"\bfinancial\b", r"\bfintech\b",
    r"\btrading\b", r"\binvestment\b", r"\bhedge fund\b", r"\binsur(?:ance|tech)\b",
    r"\bpayment\b", r"\bcredit\b", r"\bfraud\b", r"\bkyc\b", r"\baml\b",
    r"\bregulat\b", r"\bsec\b", r"\bcfpb\b", r"\becb\b", r"\bocc\b",
    r"\bwall street\b", r"\bstock\b", r"\bequit\b", r"\bfixed income\b",
    r"\bmortgage\b", r"\bloan\b", r"\bcompliance\b", r"\blender\b",
    r"\bwealth\b", r"\basset manag\b", r"\bcapital market\b",
    r"\bunderwriting\b", r"\bclaim\b", r"\bportfolio\b",
]

# Titles containing any of these (and nothing redemptive) are discarded
EXCLUSION_PATTERNS = [
    r"\bbitcoin\b", r"\bcrypto(?!currency.*finance)\b", r"\bnft\b",
    r"\bgaming\b", r"\bhealthcare\b", r"\bmedical\b", r"\bclimate\b",
    r"\bagriculture\b", r"\bretail(?! bank)\b",
]

CATEGORY_MAP = {
    "Banking": [r"\bbank\b", r"\bkyc\b", r"\baml\b", r"\bonboard\b", r"\bcustomer service\b"],
    "Trading": [r"\btrading\b", r"\bhedge fund\b", r"\bquant\b", r"\bequit\b", r"\bportfolio\b", r"\bstock\b"],
    "RegTech": [r"\bregulat\b", r"\bcompliance\b", r"\bsec\b", r"\bcfpb\b", r"\becb\b", r"\bfsb\b", r"\bgdpr\b"],
    "InsurTech": [r"\binsur\b", r"\bclaim\b", r"\bunderwriting\b", r"\bactuar\b"],
    "Payments": [r"\bpayment\b", r"\bfintech\b", r"\bbnpl\b", r"\bwallet\b", r"\bstablecoin\b", r"\bcbdc\b"],
}


def fetch_rss(url: str, timeout: int = 10) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "AI-Finance-Monitor/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception as e:
        print(f"  ✗ {url}: {e}", file=sys.stderr)
        return None


def parse_rss(xml_bytes: bytes) -> list[dict]:
    items = []
    try:
        root = ET.fromstring(xml_bytes)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        # RSS 2.0
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            desc = (item.findtext("description") or "").strip()
            pub = item.findtext("pubDate") or ""
            items.append({"title": title, "url": link, "summary": strip_html(desc), "pub": pub})
        # Atom
        for entry in root.findall(".//atom:entry", ns):
            title = (entry.findtext("atom:title", namespaces=ns) or "").strip()
            link_el = entry.find("atom:link", ns)
            link = (link_el.get("href") if link_el is not None else "") or ""
            desc = (entry.findtext("atom:summary", namespaces=ns) or "").strip()
            pub = entry.findtext("atom:updated", namespaces=ns) or ""
            items.append({"title": title, "url": link, "summary": strip_html(desc), "pub": pub})
    except ET.ParseError as e:
        print(f"  XML parse error: {e}", file=sys.stderr)
    return items


def strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"&#?\w+;", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def is_relevant(title: str, body: str) -> bool:
    title_l = title.lower()
    body_l = body.lower()
    combined = title_l + " " + body_l

    # Hard exclusions on title
    if any(re.search(p, title_l) for p in EXCLUSION_PATTERNS):
        return False

    has_ai_title = any(re.search(p, title_l) for p in AI_KEYWORDS)
    has_finance_title = any(re.search(p, title_l) for p in FINANCE_KEYWORDS)
    has_ai_body = any(re.search(p, body_l) for p in AI_KEYWORDS)
    has_finance_body = any(re.search(p, body_l) for p in FINANCE_KEYWORDS)

    # Both AI and finance must appear somewhere
    if not ((has_ai_title or has_ai_body) and (has_finance_title or has_finance_body)):
        return False

    # At least one must be explicit in the title — prevents tangential matches
    # buried in a long summary
    return has_ai_title or has_finance_title


def classify(text: str) -> str:
    t = text.lower()
    for cat, patterns in CATEGORY_MAP.items():
        if any(re.search(p, t) for p in patterns):
            return cat
    return "Banking"


def parse_pub_date(pub: str) -> str:
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
    ):
        try:
            return datetime.strptime(pub.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def extract_tags(text: str, category: str) -> list[str]:
    tags = []
    entities = re.findall(r"\b[A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+)?\b", text)
    seen = set()
    for e in entities:
        if e.lower() not in {"the", "a", "an", "of", "in", "at", "to", "for", "and"} and e not in seen:
            tags.append(e.lower())
            seen.add(e)
        if len(tags) >= 3:
            break
    return tags or [category.lower()]


TREND_STOPWORDS = {
    "the", "a", "an", "of", "in", "at", "to", "for", "and", "or", "is", "as",
    "on", "with", "by", "from", "its", "into", "not", "all", "this", "that",
    "says", "say", "said", "will", "can", "has", "have", "are", "be", "been",
    "launch", "launches", "launched", "build", "builds", "built", "bring",
    "brings", "make", "makes", "turns", "warns", "signals", "urges", "opens",
    "over", "now", "new", "more", "top", "best", "first", "next", "last",
    "finance", "financial", "banking", "payment", "payments", "artificial",
    "intelligence", "machine", "learning", "technology", "market", "markets",
    "digital", "data", "platform", "systems", "services", "global", "latest",
    "report", "reports", "using", "based", "powered", "amid", "help", "helps",
    "news", "how", "what", "why", "when", "who", "which",
}

# Terms that are always present and don't signal anything trending
ALWAYS_PRESENT = {"ai", "bank", "fintech", "trading", "payment", "credit"}


def compute_trending(articles: list[dict], top_n: int = 10) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=14)
    counts: dict[str, int] = {}

    for article in articles:
        art_date = datetime.strptime(article["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if art_date < cutoff:
            continue

        words = re.findall(r"\b[A-Za-z][a-z]{2,}\b", article["title"])
        seen_in_article: set[str] = set()

        for w in words:
            key = w.lower()
            if key in TREND_STOPWORDS or key in ALWAYS_PRESENT or len(key) < 4:
                continue
            if key not in seen_in_article:
                counts[key] = counts.get(key, 0) + 1
                seen_in_article.add(key)

        # Also count tags (lower weight — tags are 3 per article, very common)
        for tag in article.get("tags", []):
            key = tag.lower().strip()
            if key and key not in TREND_STOPWORDS and key not in ALWAYS_PRESENT and len(key) >= 4:
                counts[key] = counts.get(key, 0) + 1

    ranked = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    return [
        {"topic": term.capitalize(), "count": cnt}
        for term, cnt in ranked[:top_n]
        if cnt >= 2
    ]


def slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower())[:80]


def load_existing() -> tuple[dict, set]:
    if DATA_FILE.exists():
        data = json.loads(DATA_FILE.read_text())
        seen = {slug(a["title"]) for a in data.get("articles", [])}
        return data, seen
    return {"articles": []}, set()


def main():
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    existing, seen_slugs = load_existing()
    new_articles = []

    for source_name, feed_url in RSS_FEEDS:
        print(f"Fetching: {source_name}", file=sys.stderr)
        xml = fetch_rss(feed_url)
        if not xml:
            continue
        items = parse_rss(xml)
        for item in items:
            title = item["title"]
            if not title or not is_relevant(title, item["summary"]):
                continue
            s = slug(title)
            if s in seen_slugs:
                continue
            seen_slugs.add(s)
            date_str = parse_pub_date(item["pub"])
            art_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if art_date < cutoff:
                continue
            cat = classify(title + " " + item["summary"])
            tags = extract_tags(title + " " + item["summary"], cat)
            summary = item["summary"][:280] + "…" if len(item["summary"]) > 280 else item["summary"]
            if not summary:
                summary = title
            new_articles.append({
                "id": str(abs(hash(title)) % 10**9),
                "title": title,
                "summary": summary,
                "source": source_name,
                "url": item["url"],
                "date": date_str,
                "category": cat,
                "tags": tags,
            })

    print(f"Found {len(new_articles)} new relevant articles", file=sys.stderr)

    all_articles = new_articles + existing.get("articles", [])
    all_articles.sort(key=lambda a: a["date"], reverse=True)
    all_articles = all_articles[:60]  # cap at 60 articles

    trending = compute_trending(all_articles)
    print(f"Trending topics: {[t['topic'] for t in trending]}", file=sys.stderr)

    output = {
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "trending": trending,
        "articles": all_articles,
    }

    DATA_FILE.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"Wrote {len(all_articles)} articles to {DATA_FILE}", file=sys.stderr)


if __name__ == "__main__":
    main()
