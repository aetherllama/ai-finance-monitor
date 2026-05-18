"""
Quarterly AI Maturity Benchmark updater.

Reads data/articles.json for institution-specific news from the last 90 days,
asks Claude Haiku to assess whether scores should be adjusted, and saves the
result to data/maturity.json.

Run manually or via GitHub Actions (.github/workflows/update-maturity.yml).
"""

import json
import os
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta

MATURITY_PATH  = 'data/maturity.json'
ARTICLES_PATH  = 'data/articles.json'
LOOKBACK_DAYS  = 90
MAX_ARTICLES   = 5   # per institution


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_json(path: str) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(path: str, data: dict) -> None:
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  Saved {path}")


def tier_from_total(total: int) -> str:
    if total >= 85: return 'leader'
    if total >= 65: return 'advanced'
    if total >= 50: return 'developing'
    return 'emerging'


def get_recent_articles(articles: list, institution: dict) -> list:
    cutoff = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).strftime('%Y-%m-%d')
    aliases = [institution['name'].lower()] + [a.lower() for a in institution.get('aliases', [])]

    hits = []
    for a in articles:
        if a.get('date', '') < cutoff:
            continue
        text = (a.get('title', '') + ' ' + a.get('summary', '')).lower()
        if any(alias in text for alias in aliases):
            hits.append(a)

    hits.sort(key=lambda x: x.get('date', ''), reverse=True)
    return hits[:MAX_ARTICLES]


# ── Claude API ────────────────────────────────────────────────────────────────

def _call_claude(api_key: str, prompt: str) -> "str | None":
    payload = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 600,
        "messages": [{"role": "user", "content": prompt}]
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read())
            return body['content'][0]['text'].strip()
    except urllib.error.HTTPError as e:
        print(f"    Claude API error {e.code}: {e.read().decode()[:200]}")
    except Exception as e:
        print(f"    Claude API error: {e}")
    return None


def review_with_claude(api_key: str, institution: dict, articles: list) -> "dict | None":
    scores = institution['scores']
    articles_text = '\n'.join(
        f"- [{a['date']}] {a['title']}. {a['summary']}"
        for a in articles
    )

    prompt = f"""You are updating the AI Finance Maturity Index (AFMI) for {institution['name']} ({institution['type']}, {institution['hq']}).

Current AFMI scores (each out of 20):
  Strategy & Governance : {scores['strategy']}/20
  Data & Infrastructure  : {scores['data']}/20
  Deployment at Scale    : {scores['deployment']}/20
  Talent & Investment    : {scores['talent']}/20
  Innovation & IP        : {scores['innovation']}/20
  Total                  : {institution['total']}/100  Tier: {institution['tier']}

Recent news (last {LOOKBACK_DAYS} days):
{articles_text}

Based ONLY on the evidence above, suggest any score changes. Be conservative — only adjust if a new development clearly warrants it (max ±2 per dimension per quarter).

Respond with valid JSON only (no markdown fences):
{{"changes": [{{"dimension": "<strategy|data|deployment|talent|innovation>", "new_value": <int 0-20>, "reason": "<≤15 words>"}}], "summary": "<one sentence on the most significant new development, or empty string if none>"}}

If no changes are warranted, return: {{"changes": [], "summary": ""}}"""

    raw = _call_claude(api_key, prompt)
    if not raw:
        return None

    # Strip markdown fences if present
    raw = re.sub(r'^```(?:json)?\s*', '', raw, flags=re.MULTILINE)
    raw = re.sub(r'\s*```$', '', raw, flags=re.MULTILINE)

    try:
        result = json.loads(raw)
        if 'changes' not in result:
            return None
        return result
    except json.JSONDecodeError as e:
        print(f"    JSON parse error: {e}\n    Raw: {raw[:300]}")
        return None


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        print("Warning: ANTHROPIC_API_KEY not set — score analysis will be skipped.")

    maturity = load_json(MATURITY_PATH)

    try:
        articles = load_json(ARTICLES_PATH).get('articles', [])
        print(f"Loaded {len(articles)} articles from {ARTICLES_PATH}")
    except Exception as e:
        print(f"Could not load articles ({e}) — skipping AI review.")
        articles = []

    today      = datetime.now().strftime('%Y-%m-%d')
    next_review = (datetime.now() + timedelta(days=90)).strftime('%Y-%m-%d')

    total_changes = 0

    for inst in maturity['institutions']:
        name = inst['name']
        print(f"\n── {name} ──")

        relevant = get_recent_articles(articles, inst)
        if not relevant:
            print("  No recent mentions found.")
            continue
        print(f"  {len(relevant)} relevant article(s) found.")

        if not api_key:
            print("  Skipping AI review (no API key).")
            continue

        review = review_with_claude(api_key, inst, relevant)
        if not review:
            print("  Review failed or returned no result.")
            continue

        changes = review.get('changes', [])
        summary = review.get('summary', '').strip()

        if not changes:
            print("  No score changes recommended.")
            if summary:
                inst['latest_development'] = summary
            continue

        inst['previous_total'] = inst['total']

        for ch in changes:
            dim = ch.get('dimension', '')
            new_val = ch.get('new_value')
            if dim not in inst['scores']:
                continue
            if not isinstance(new_val, int) or not (0 <= new_val <= 20):
                continue
            # Cap quarterly change at ±2
            capped = max(inst['scores'][dim] - 2, min(inst['scores'][dim] + 2, new_val))
            old_val = inst['scores'][dim]
            inst['scores'][dim] = capped
            print(f"  {dim}: {old_val} → {capped}  ({ch.get('reason', '')})")
            total_changes += 1

        inst['total'] = sum(inst['scores'].values())
        inst['score_delta'] = inst['total'] - inst['previous_total']
        inst['tier'] = tier_from_total(inst['total'])

        if summary:
            inst['latest_development'] = summary

        if inst['score_delta'] != 0:
            print(f"  New total: {inst['total']}/100  (Δ {inst['score_delta']:+d})")

    maturity['last_updated'] = today
    maturity['next_review']  = next_review
    save_json(MATURITY_PATH, maturity)

    print(f"\n{'─'*40}")
    print(f"Update complete — {total_changes} score adjustment(s)")
    print(f"Last updated : {today}")
    print(f"Next review  : {next_review}")


if __name__ == '__main__':
    main()
