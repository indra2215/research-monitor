import requests
import feedparser
import json
import os
import urllib.parse
import time
from datetime import datetime, timedelta

# =========================
# ENV / CONFIG
# =========================
TELEGRAM_TOKEN = os.getenv("TELEGRAMTOKEN")
CHAT_ID = os.getenv("CHARTID")
S2_API_KEY = os.getenv("S2_API_KEY")

CONFIG_PATH = "config.json"
SEEN_FILE = "seen.json"

# Behavior
DAYS_BACK = 3
DATE_THRESHOLD = datetime.utcnow() - timedelta(days=DAYS_BACK)
BATCH_SIZE = 20
MAX_MESSAGE_LENGTH = 3900
RESULTS_LIMIT = 10
HTTP_TIMEOUT = 10  # seconds
RETRY_COUNT = 2
RETRY_BACKOFF = 2  # seconds

# =========================
# Load keywords
# =========================
if not os.path.exists(CONFIG_PATH):
    raise SystemExit("Missing config.json")

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    config = json.load(f)

keywords = []
for domain in config.get("domains", {}).values():
    keywords.extend(domain)
# flatten and dedupe lightly
keywords = list(dict.fromkeys([k.strip() for k in keywords if k and isinstance(k, str)]))

# =========================
# Memory (seen links)
# =========================
if os.path.exists(SEEN_FILE):
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            seen_links = set(json.load(f))
    except Exception:
        seen_links = set()
else:
    seen_links = set()

def save_seen():
    try:
        with open(SEEN_FILE, "w", encoding="utf-8") as f:
            json.dump(list(seen_links), f)
    except Exception as e:
        print("Error saving seen.json:", e)

# =========================
# Utilities
# =========================
def chunk_keywords(lst, size=BATCH_SIZE):
    for i in range(0, len(lst), size):
        yield lst[i:i + size]

def safe_get(url, params=None, headers=None):
    last_exc = None
    for attempt in range(RETRY_COUNT + 1):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=HTTP_TIMEOUT)
            r.raise_for_status()
            return r
        except Exception as e:
            last_exc = e
            if attempt < RETRY_COUNT:
                time.sleep(RETRY_BACKOFF * (attempt + 1))
            else:
                print(f"Request failed: {url} error: {e}")
    return None

# =========================
# Scoring & classification
# =========================
def score_text(title, abstract="", citation_count=0):
    score = 0
    text = (title + " " + (abstract or "")).lower()
    for kw in keywords:
        k = kw.lower()
        if k in title.lower():
            score += 5
        if k in text:
            score += 3
    if citation_count and citation_count > 10:
        score += 2
    return score

def classify(score):
    if score >= 10:
        return "HIGH"
    if score >= 5:
        return "MEDIUM"
    return None

# =========================
# Telegram sender (no Markdown)
# =========================
def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Telegram credentials missing. Check GitHub secrets.")
        return

    # do not print token anywhere
    print("Telegram CHAT_ID:", CHAT_ID)
    print("Full message length:", len(message))

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    # split if too long
    chunks = [message[i:i + MAX_MESSAGE_LENGTH] for i in range(0, len(message), MAX_MESSAGE_LENGTH)]
    for chunk in chunks:
        try:
            resp = requests.post(url, json={"chat_id": CHAT_ID, "text": chunk}, timeout=HTTP_TIMEOUT)
            try:
                print("Telegram response:", resp.status_code, resp.text)
            except Exception:
                print("Telegram response status:", resp.status_code)
        except Exception as e:
            print("Failed to send to Telegram:", e)

# =========================
# Process item & dedupe
# =========================
def process_item(title, link, abstract="", citation=0, published_date=None):
    if not link:
        return None
    # use canonical link string
    link_key = link.strip()
    if link_key in seen_links:
        return None
    if published_date and published_date < DATE_THRESHOLD:
        return None
    score = score_text(title, abstract or "", citation)
    lvl = classify(score)
    if lvl:
        seen_links.add(link_key)
        # No markdown, simple bracket label to avoid parsing errors
        return f"[{lvl}] {title}\n{link_key}\n"
    return None

# =========================
# Source: arXiv
# =========================
def check_arxiv():
    items = []
    base = "http://export.arxiv.org/api/query"
    for batch in chunk_keywords(keywords):
        raw_query = " OR ".join([f'all:"{kw}"' for kw in batch])
        encoded = urllib.parse.quote(raw_query, safe='')
        url = f"{base}?search_query={encoded}&sortBy=lastUpdatedDate&max_results=10"
        try:
            r = safe_get(url)
            if not r:
                continue
            feed = feedparser.parse(r.content)
            for entry in feed.entries:
                if not hasattr(entry, "published_parsed"):
                    continue
                try:
                    published = datetime(*entry.published_parsed[:6])
                except Exception:
                    published = None
                item = process_item(entry.title, getattr(entry, "link", ""), getattr(entry, "summary", ""), 0, published)
                if item:
                    items.append(item)
        except Exception as e:
            print("arXiv batch error:", e)
    return items

# =========================
# Source: OpenAlex
# =========================
def check_openalex():
    items = []
    base = "https://api.openalex.org/works"
    for batch in chunk_keywords(keywords):
        raw_query = " OR ".join(batch)
        encoded = urllib.parse.quote(raw_query, safe='')
        url = f"{base}?search={encoded}&per-page=10"
        r = safe_get(url)
        if not r:
            continue
        try:
            data = r.json()
        except Exception:
            print("OpenAlex: invalid JSON")
            continue
        for w in data.get("results", []):
            title = w.get("title", "") or ""
            link = w.get("id", "") or ""
            citation = w.get("cited_by_count", 0) or 0
            pub_date_str = w.get("publication_date")
            published = None
            if pub_date_str:
                try:
                    published = datetime.strptime(pub_date_str, "%Y-%m-%d")
                except Exception:
                    published = None
            item = process_item(title, link, "", citation, published)
            if item:
                items.append(item)
    return items

# =========================
# Source: Crossref
# =========================
def check_crossref():
    items = []
    base = "https://api.crossref.org/works"
    for batch in chunk_keywords(keywords):
        raw_query = " OR ".join(batch)
        encoded = urllib.parse.quote(raw_query, safe='')
        url = f"{base}?query={encoded}&rows=10"
        r = safe_get(url)
        if not r:
            continue
        try:
            data = r.json()
        except Exception:
            print("Crossref: invalid JSON")
            continue
        for it in data.get("message", {}).get("items", []):
            title = (it.get("title") or [""])[0]
            link = it.get("URL", "") or ""
            citation = it.get("is-referenced-by-count", 0) or 0
            published = None
            pub_parts = (it.get("published-print", {}) or {}).get("date-parts") or []
            if pub_parts:
                try:
                    y, m, d = (pub_parts[0] + [1, 1, 1])[:3]
                    published = datetime(int(y), int(m), int(d))
                except Exception:
                    published = None
            item = process_item(title, link, "", citation, published)
            if item:
                items.append(item)
    return items

# =========================
# Source: Semantic Scholar (optional)
# =========================
def check_semantic():
    if not S2_API_KEY:
        return []
    items = []
    headers = {"x-api-key": S2_API_KEY}
    base = "https://api.semanticscholar.org/graph/v1/paper/search"
    for batch in chunk_keywords(keywords):
        raw_query = " OR ".join(batch)
        params = {"query": raw_query, "limit": 10, "fields": "title,abstract,url,citationCount,year"}
        r = safe_get(base, params=params, headers=headers)
        if not r:
            continue
        try:
            data = r.json()
        except Exception:
            print("Semantic Scholar: invalid JSON")
            continue
        for paper in data.get("data", []):
            title = paper.get("title", "") or ""
            link = paper.get("url", "") or ""
            abstract = paper.get("abstract", "") or ""
            citation = paper.get("citationCount", 0) or 0
            published = None
            if paper.get("year"):
                try:
                    published = datetime(int(paper["year"]), 1, 1)
                except Exception:
                    published = None
            item = process_item(title, link, abstract, citation, published)
            if item:
                items.append(item)
    return items

# =========================
# Main
# =========================
def main():
    print("Monitor run starting. Keywords:", len(keywords))
    results = []
    try:
        results += check_arxiv()
        results += check_openalex()
        results += check_crossref()
        results += check_semantic()
    except Exception as e:
        print("Unexpected error during checks:", e)

    # Keep order but limit number of results
    if not results:
        message = "Daily Research Monitor\n\nNo significant updates in the last 3 days."
    else:
        # de-duplicate results text while preserving order (links were already deduped)
        seen_text = set()
        unique = []
        for r in results:
            if r not in seen_text:
                unique.append(r)
                seen_text.add(r)
        trimmed = unique[:RESULTS_LIMIT]
        message = "Daily Research Monitor\n\n" + "\n".join(trimmed)

    # Send message(s)
    send_telegram(message)
    # Persist memory
    save_seen()
    print("Monitor run finished. Sent items:", len(results))

if __name__ == "__main__":
    main()
