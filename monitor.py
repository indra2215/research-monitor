import requests
import feedparser
import json
import os
import urllib.parse
import time
from datetime import datetime, timedelta

# =========================
# ENV VARIABLES
# =========================
TELEGRAM_TOKEN = os.getenv("TELEGRAMTOKEN")
CHAT_ID = os.getenv("CHARTID")
S2_API_KEY = os.getenv("S2_API_KEY")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
MATERIALS_PROJECT_API_KEY = os.getenv("MATERIALS_PROJECT_API_KEY")
SPRINGER_API_KEY = os.getenv("SPRINGER_API_KEY")

CONFIG_PATH = "config.json"
SEEN_FILE = "seen.json"

# =========================
# SETTINGS
# =========================
DAYS_BACK = 3
DATE_THRESHOLD = datetime.utcnow() - timedelta(days=DAYS_BACK)
BATCH_SIZE = 20
MAX_MESSAGE_LENGTH = 3500
RESULTS_LIMIT = 10
HTTP_TIMEOUT = 10

# =========================
# LOAD KEYWORDS
# =========================
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    config = json.load(f)

keywords = []
for domain in config["domains"].values():
    keywords.extend(domain)

keywords = list(set(keywords))

# =========================
# MEMORY
# =========================
if os.path.exists(SEEN_FILE):
    with open(SEEN_FILE, "r", encoding="utf-8") as f:
        seen_links = set(json.load(f))
else:
    seen_links = set()

def save_seen():
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen_links), f)

# =========================
# UTIL
# =========================
def chunk(lst, size):
    for i in range(0, len(lst), size):
        yield lst[i:i+size]

def safe_get(url, params=None, headers=None):
    try:
        r = requests.get(url, params=params, headers=headers, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        return r
    except Exception as e:
        print("API error:", url, e)
        return None

def canonical_key(doi=None, arxiv_id=None, url=None):
    if doi:
        return doi.lower().strip()
    if arxiv_id:
        return f"arxiv:{arxiv_id}"
    if url:
        return url.strip()
    return None

# =========================
# SCORING
# =========================
def score(title, abstract="", citations=0):
    text = (title + " " + abstract).lower()
    s = 0
    for kw in keywords:
        if kw.lower() in text:
            s += 2
    if citations > 5:
        s += 1
    return s

# =========================
# TELEGRAM
# =========================
def send_telegram(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    chunks = [msg[i:i+MAX_MESSAGE_LENGTH] for i in range(0, len(msg), MAX_MESSAGE_LENGTH)]
    for c in chunks:
        requests.post(url, json={"chat_id": CHAT_ID, "text": c})

# =========================
# DISCORD
# =========================
def send_discord(msg):
    if not DISCORD_WEBHOOK:
        return

    chunks = [msg[i:i+1800] for i in range(0, len(msg), 1800)]
    for c in chunks:
        requests.post(DISCORD_WEBHOOK, json={"content": c})

# =========================
# ARXIV
# =========================
def check_arxiv():
    results = []
    base = "http://export.arxiv.org/api/query"

    for batch in chunk(keywords, BATCH_SIZE):
        query = urllib.parse.quote(" OR ".join(batch))
        url = f"{base}?search_query=all:{query}&sortBy=lastUpdatedDate&max_results=10"
        r = safe_get(url)
        if not r:
            continue

        feed = feedparser.parse(r.content)

        for e in feed.entries:
            arxiv_id = e.id.split("/")[-1]
            key = canonical_key(arxiv_id=arxiv_id)

            if key in seen_links:
                continue

            s = score(e.title, e.summary)
            if s > 2:
                seen_links.add(key)
                results.append(f"[arXiv] {e.title}\n{e.link}\n")

    return results

# =========================
# OPENALEX
# =========================
def check_openalex():
    results = []
    base = "https://api.openalex.org/works"

    for batch in chunk(keywords, BATCH_SIZE):
        query = urllib.parse.quote(" OR ".join(batch))
        r = safe_get(f"{base}?search={query}&per-page=10")
        if not r:
            continue

        for w in r.json().get("results", []):
            doi = w.get("doi")
            key = canonical_key(doi=doi, url=w.get("id"))

            if key in seen_links:
                continue

            s = score(w.get("title",""), "")
            if s > 2:
                seen_links.add(key)
                results.append(f"[OpenAlex] {w.get('title')}\n{w.get('id')}\n")

    return results

# =========================
# CROSSREF
# =========================
def check_crossref():
    results = []
    base = "https://api.crossref.org/works"

    for batch in chunk(keywords, BATCH_SIZE):
        query = urllib.parse.quote(" OR ".join(batch))
        r = safe_get(f"{base}?query={query}&rows=10")
        if not r:
            continue

        for it in r.json().get("message", {}).get("items", []):
            doi = it.get("DOI")
            key = canonical_key(doi=doi)

            if key in seen_links:
                continue

            title = (it.get("title") or [""])[0]
            s = score(title)
            if s > 2:
                seen_links.add(key)
                results.append(f"[Crossref] {title}\nhttps://doi.org/{doi}\n")

    return results

# =========================
# SPRINGER
# =========================
def check_springer():
    if not SPRINGER_API_KEY:
        return []

    results = []
    base = "https://api.springernature.com/meta/v2/json"

    for batch in chunk(keywords, BATCH_SIZE):
        params = {
            "q": " OR ".join(batch),
            "api_key": SPRINGER_API_KEY,
            "p": 10
        }
        r = safe_get(base, params=params)
        if not r:
            continue

        for rec in r.json().get("records", []):
            doi = rec.get("doi")
            key = canonical_key(doi=doi)

            if key in seen_links:
                continue

            title = rec.get("title", "")
            s = score(title)
            if s > 2:
                seen_links.add(key)
                results.append(f"[Springer] {title}\nhttps://doi.org/{doi}\n")

    return results

# =========================
# MAIN
# =========================
def main():
    utc = datetime.utcnow()
    ist = utc + timedelta(hours=5, minutes=30)

    results = []
    for f in [check_arxiv, check_openalex, check_crossref, check_springer]:
        results += f()

    results = results[:RESULTS_LIMIT]

    msg = f"""
==============================
Daily Research Monitor
==============================

UTC  : {utc.strftime('%Y-%m-%d %H:%M:%S')}
IST  : {ist.strftime('%Y-%m-%d %H:%M:%S')}
Keywords : {len(keywords)}
Memory Size : {len(seen_links)}
Matches : {len(results)}

--------------------------------
"""

    if results:
        msg += "\nRecent Findings:\n\n"
        msg += "\n".join(results)
    else:
        msg += "\nNo new relevant research.\n"

    send_telegram(msg)
    send_discord(msg)
    save_seen()

if __name__ == "__main__":
    main()
