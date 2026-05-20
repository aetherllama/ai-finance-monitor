"""Monthly AI FinTech Performance Index (AFPI) score updater.

Looks back 30 days of news articles, uses Claude Haiku to assess each company,
then applies bounded ±1/dimension adjustments. Tier and next_review are
recalculated automatically.
"""

import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import anthropic

ROOT        = Path(__file__).parent.parent
DATA_DIR    = ROOT / "data"
FINTECHS_F  = DATA_DIR / "fintechs.json"
ARTICLES_F  = DATA_DIR / "articles.json"

TIER_THRESHOLDS = {"elite": 80, "leader": 65, "growth": 50}
MAX_DELTA = 1          # ±1 per dimension per monthly cycle
LOOKBACK_DAYS = 30

DIM_KEYS = [
    "ai_innovation",
    "fi_client_depth",
    "processing_scale",
    "global_reach",
    "commercial_traction",
]


def load_json(path: Path) -> dict | list:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, obj) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def tier_for(total: int) -> str:
    if total >= TIER_THRESHOLDS["elite"]:
        return "elite"
    if total >= TIER_THRESHOLDS["leader"]:
        return "leader"
    if total >= TIER_THRESHOLDS["growth"]:
        return "growth"
    return "emerging"


def recent_articles(articles: list, lookback: int = LOOKBACK_DAYS) -> list:
    cutoff = datetime.now() - timedelta(days=lookback)
    out = []
    for a in articles:
        ts = a.get("published") or a.get("date") or ""
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if dt.replace(tzinfo=None) >= cutoff:
                out.append(a)
        except (ValueError, AttributeError):
            pass
    return out


def articles_for_company(company: dict, articles: list) -> list:
    names = [company["name"].lower()] + [a.lower() for a in company.get("aliases", [])]
    hits = []
    for a in articles:
        text = ((a.get("title") or "") + " " + (a.get("summary") or "")).lower()
        if any(n in text for n in names):
            hits.append(a)
    return hits


def build_prompt(company: dict, articles: list) -> str:
    snippets = "\n".join(
        f"- [{a.get('published','?')[:10]}] {a.get('title','')}: {(a.get('summary') or '')[:200]}"
        for a in articles[:15]
    )
    if not snippets:
        snippets = "(no recent news found)"

    scores_str = "\n".join(
        f"  {k}: {company['scores'].get(k, 0)}/20" for k in DIM_KEYS
    )

    return f"""You are updating the AI FinTech Performance Index (AFPI) for {company['name']}.

Current scores (out of 20 each):
{scores_str}
Total: {company['total']}/100

Recent news articles (last 30 days):
{snippets}

Based ONLY on the evidence in these articles, suggest score adjustments for each dimension.
Adjustments must be in the range [-1, 0, +1]. If there is no relevant evidence, use 0.

Dimensions:
- ai_innovation: Sophistication and novelty of AI capabilities
- fi_client_depth: Breadth and quality of FI clients in production
- processing_scale: Operational transaction/data volume scale
- global_reach: International deployment footprint
- commercial_traction: Financial health, growth, and market validation

Also write a one-sentence highlight (max 120 chars) summarising the most noteworthy recent development.
If no news found, keep the existing highlight.

Respond ONLY with valid JSON in this exact format:
{{
  "adjustments": {{
    "ai_innovation": 0,
    "fi_client_depth": 0,
    "processing_scale": 0,
    "global_reach": 0,
    "commercial_traction": 0
  }},
  "highlight": "..."
}}"""


def clamp(val: int, lo: int = 0, hi: int = 20) -> int:
    return max(lo, min(hi, val))


def update_company(client: anthropic.Anthropic, company: dict, articles: list) -> bool:
    relevant = articles_for_company(company, articles)
    prompt   = build_prompt(company, relevant)

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        # Strip markdown code fences if present
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
        result = json.loads(raw)
    except (json.JSONDecodeError, IndexError, anthropic.APIError) as e:
        print(f"  [WARN] {company['name']}: API/parse error — {e}", file=sys.stderr)
        return False

    adj  = result.get("adjustments", {})
    changed = False
    for key in DIM_KEYS:
        delta = int(adj.get(key, 0))
        delta = max(-MAX_DELTA, min(MAX_DELTA, delta))
        old   = company["scores"].get(key, 0)
        new   = clamp(old + delta)
        if new != old:
            company["scores"][key] = new
            changed = True

    new_total = sum(company["scores"][k] for k in DIM_KEYS)
    if new_total != company["total"]:
        company["total"] = new_total
        changed = True

    new_tier = tier_for(new_total)
    if new_tier != company["tier"]:
        company["tier"] = new_tier
        changed = True

    highlight = (result.get("highlight") or "").strip()
    if highlight and highlight != company.get("highlight", ""):
        company["highlight"] = highlight[:160]
        changed = True

    return changed


def next_review_date() -> str:
    today = date.today()
    # Same day next month
    month = today.month % 12 + 1
    year  = today.year + (1 if today.month == 12 else 0)
    return date(year, month, today.day).isoformat()


def main() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ANTHROPIC_API_KEY not set")

    client = anthropic.Anthropic(api_key=api_key)

    data      = load_json(FINTECHS_F)
    companies = data.get("companies", [])

    articles_data = load_json(ARTICLES_F) if ARTICLES_F.exists() else []
    if isinstance(articles_data, dict):
        articles_data = articles_data.get("articles", [])
    articles = recent_articles(articles_data)
    print(f"Loaded {len(articles)} articles from last {LOOKBACK_DAYS} days")

    updated_count = 0
    for i, company in enumerate(companies, 1):
        print(f"[{i:02d}/{len(companies)}] {company['name']}…", end=" ", flush=True)
        changed = update_company(client, company, articles)
        print("updated" if changed else "no change")
        if changed:
            updated_count += 1

    data["last_updated"] = date.today().isoformat()
    data["next_review"]  = next_review_date()
    data["update_frequency"] = "monthly"

    # Re-sort by total descending (stable)
    data["companies"] = sorted(companies, key=lambda c: c["total"], reverse=True)

    save_json(FINTECHS_F, data)
    print(f"\nDone — {updated_count}/{len(companies)} companies updated.")
    print(f"Next review: {data['next_review']}")


if __name__ == "__main__":
    main()
