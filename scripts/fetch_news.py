#!/usr/bin/env python3
"""
Fetches AI-in-finance news from RSS feeds, merges with existing articles.json,
deduplicates by title similarity, and writes the updated file.
"""

import json
import os
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


def parse_pub_date(pub: str) -> "str | None":
    """Return YYYY-MM-DD if date is valid and not in the future; else None."""
    today = datetime.now(timezone.utc).date()
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
    ):
        try:
            dt = datetime.strptime(pub.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            d = dt.date()
            if d > today:
                print(f"  Skipping future date {d}", file=sys.stderr)
                return None
            return d.strftime("%Y-%m-%d")
        except ValueError:
            continue
    # Cannot parse — skip rather than assume today
    print(f"  Cannot parse date: {pub!r} — skipping", file=sys.stderr)
    return None


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


# Curated AI topics: each entry is (display_name, [regex_patterns])
# Patterns are matched against article title + summary (case-insensitive).
AI_TOPICS = [
    ("AI Agents",              [r"\bai[- ]agent", r"\bagentic\b", r"\bagent(?:ic)?\s+ai\b"]),
    ("Generative AI",          [r"\bgenerative\s+ai\b", r"\bgen[- ]ai\b"]),
    ("Large Language Models",  [r"\bllm\b", r"\blarge\s+language\s+model"]),
    ("Machine Learning",       [r"\bmachine\s+learning\b"]),
    ("Neural Networks",        [r"\bneural\s+network"]),
    ("Natural Language",       [r"\bnlp\b", r"\bnatural\s+language\s+process"]),
    ("Computer Vision",        [r"\bcomputer\s+vision\b"]),
    ("Deep Learning",          [r"\bdeep\s+learning\b"]),
    ("Automation",             [r"\bautonomous\b", r"\bautomat(?:ed|ion|ing)\b"]),
    ("Predictive Analytics",   [r"\bpredictive\s+anal", r"\bpredictive\s+model", r"\bpredictive\b"]),
    ("Fraud Detection",        [r"\bfraud\s+detect", r"\bfraud\s+prevent", r"\banti[- ]fraud\b"]),
    ("Algorithmic Trading",    [r"\balgorithm(?:ic)?\s+trad", r"\bquant(?:itative)?\s+trad", r"\bautomat\w+\s+trad"]),
    ("Risk Management",        [r"\bai[- \w]{0,10}risk\b", r"\brisk\s+(?:model|score|assess)"]),
    ("Credit & Underwriting",  [r"\bai[- \w]{0,10}credit\b", r"\bai[- \w]{0,10}underwr", r"\bai[- \w]{0,10}lend"]),
    ("Regulatory AI",          [r"\bregtech\b", r"\bai[- \w]{0,10}regulat", r"\bregulat\w+\s+ai\b", r"\bai[- \w]{0,10}compli"]),
    ("Customer Service AI",    [r"\bai[- \w]{0,10}customer", r"\bchatbot\b", r"\bvirtual\s+assistant\b", r"\bai\s+assistant\b"]),
    ("Payments AI",            [r"\bai[- \w]{0,10}payment", r"\bpayment[- \w]{0,10}ai\b"]),
    ("KYC / AML",              [r"\bai[- \w]{0,10}kyc\b", r"\bai[- \w]{0,10}aml\b"]),
    ("Robo-Advisory",          [r"\brobo[- ]advis"]),
    ("Copilot / Assistants",   [r"\bcopilot\b", r"\bai[- ]powered\s+assist"]),
    ("Stablecoin AI",          [r"\bstablecoin\b", r"\bcbdc\b"]),
    ("Portfolio Management",   [r"\bportfolio\s+(?:manag|construct|optim)", r"\basset\s+manag\w+\s+ai\b"]),
]


def compute_trending(articles: list[dict], top_n: int = 10) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=14)
    counts: dict[str, int] = {}

    for article in articles:
        try:
            art_date = datetime.strptime(article["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if art_date < cutoff:
            continue

        text = (article.get("title", "") + " " + article.get("summary", "")).lower()

        for topic_name, patterns in AI_TOPICS:
            if any(re.search(p, text) for p in patterns):
                counts[topic_name] = counts.get(topic_name, 0) + 1

    ranked = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    return [{"topic": name, "count": cnt} for name, cnt in ranked[:top_n] if cnt >= 1]


def _claude_insights(api_key: str, articles: list[dict]) -> dict:
    items = "\n".join(
        f"[{a['category']}] {a['title']}: {a['summary'][:220]}"
        for a in articles
    )
    prompt = (
        "You are a financial policy analyst briefing senior executives at central banks, "
        "regulators, and systemically important financial institutions. "
        "Based solely on these recent AI-in-finance developments, identify:\n"
        "- 3 RISKS: concrete threats to financial stability, regulatory compliance, "
        "operational resilience, or competitive position that policymakers and "
        "financial institutions must address now.\n"
        "- 3 OPPORTUNITIES: actionable advantages in policy design, product innovation, "
        "cost reduction, or market positioning that policymakers and financial "
        "institutions can capture from these developments.\n\n"
        "Rules: 1–2 sentences each. Be specific—name institutions, regulators, "
        "or technologies. No generic statements. No preamble or markdown.\n\n"
        "Return only valid JSON in this exact shape:\n"
        '{"risks": ["...", "...", "..."], "opportunities": ["...", "...", "..."]}\n\n'
        f"Developments:\n{items}"
    )
    payload = {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 900,
        "messages": [{"role": "user", "content": prompt}],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode(),
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
    text = result["content"][0]["text"].strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    parsed = json.loads(text)
    if (
        isinstance(parsed, dict)
        and isinstance(parsed.get("risks"), list)
        and isinstance(parsed.get("opportunities"), list)
        and len(parsed["risks"]) >= 2
        and len(parsed["opportunities"]) >= 2
    ):
        return {
            "risks": [str(s) for s in parsed["risks"][:3]],
            "opportunities": [str(s) for s in parsed["opportunities"][:3]],
        }
    raise ValueError(f"Unexpected response shape: {text[:200]}")


def _fallback_insights(articles: list[dict]) -> dict:
    """Rule-based fallback when Claude API is unavailable."""
    cats: dict[str, dict] = {}
    for a in articles:
        if a["category"] not in cats:
            cats[a["category"]] = a

    risks = []
    opps = []

    if "RegTech" in cats:
        risks.append(f"Regulatory: {cats['RegTech']['title']} — review compliance obligations.")
    if "Trading" in cats:
        risks.append(f"Trading risk: {cats['Trading']['title']} — assess algorithmic exposure.")
    if "Banking" in cats:
        risks.append(f"Operational: {cats['Banking']['title']} — evaluate model governance gaps.")

    if "Payments" in cats:
        opps.append(f"Payments: {cats['Payments']['title']} — potential infrastructure advantage.")
    if "Banking" in cats:
        opps.append(f"Banking efficiency: {cats['Banking']['title']} — cost reduction opportunity.")
    if "InsurTech" in cats:
        opps.append(f"InsurTech: {cats['InsurTech']['title']} — underwriting modernisation potential.")

    return {
        "risks": risks[:3] or ["Monitor AI developments for emerging regulatory risks."],
        "opportunities": opps[:3] or ["AI adoption creating operational efficiency opportunities."],
    }


def generate_insights(articles: list[dict]) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    recent = sorted(articles, key=lambda a: a["date"], reverse=True)[:15]
    if api_key:
        try:
            result = _claude_insights(api_key, recent)
            print("Insights generated via Claude API", file=sys.stderr)
            return result
        except Exception as e:
            print(f"Claude API error ({e}), using fallback", file=sys.stderr)
    return _fallback_insights(recent)


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
            date_str = parse_pub_date(item["pub"])
            if date_str is None:
                continue  # future-dated or unparseable — skip
            art_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if art_date < cutoff:
                continue
            s = slug(title)
            if s in seen_slugs:
                continue
            seen_slugs.add(s)
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

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    clean_existing = [
        a for a in existing.get("articles", [])
        if a.get("date", "") <= today_str
    ]
    dropped = len(existing.get("articles", [])) - len(clean_existing)
    if dropped:
        print(f"Dropped {dropped} future-dated article(s) from existing store", file=sys.stderr)

    all_articles = new_articles + clean_existing
    all_articles.sort(key=lambda a: a["date"], reverse=True)
    all_articles = all_articles[:60]  # cap at 60 articles

    trending = compute_trending(all_articles)
    print(f"Trending topics: {[t['topic'] for t in trending]}", file=sys.stderr)

    insights = generate_insights(all_articles)
    print(f"Insights: {insights}", file=sys.stderr)

    output = {
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "insights": insights,
        "trending": trending,
        "articles": all_articles,
    }

    DATA_FILE.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"Wrote {len(all_articles)} articles to {DATA_FILE}", file=sys.stderr)


if __name__ == "__main__":
    main()
