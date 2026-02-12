import requests
import feedparser
import json
import os
import urllib.parse
from datetime import datetime, timedelta

# ================= ENV =================
TELEGRAM_TOKEN = os.getenv("TELEGRAMTOKEN")
CHAT_ID = os.getenv("CHARTID")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
SPRINGER_API_KEY = os.getenv("SPRINGER_API_KEY")

CONFIG_PATH = "config.json"
SEEN_FILE = "seen.json"

DAYS_BACK = 180
DATE_THRESHOLD = datetime.utcnow() - timedelta(days=DAYS_BACK)

CHAR_BUDGET = 3200
DISCORD_LIMIT = 1900
HTTP_TIMEOUT = 12

# ================= LOAD CONFIG =================
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    config = json.load(f)

domains = config["domains"]

material_keywords = []
for k, v in domains.items():
    if k != "ai_methods":
        material_keywords.extend(v)

ai_keywords = domains.get("ai_methods", [])

# ================= MEMORY =================
if os.path.exists(SEEN_FILE):
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            seen = set(json.load(f))
    except:
        seen = set()
else:
    seen = set()

def save_seen():
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen), f)

def normalize_key(doi=None, url=None):
    if doi:
        return doi.lower().strip()
    if url:
        return url.lower().strip()
    return None

def safe_get(url, params=None, headers=None):
    try:
        r = requests.get(url, params=params, headers=headers, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        return r
    except:
        return None

# ================= QUERY BUILDER =================
def build_query(m_count=15, a_count=10):
    m_part = "(" + " OR ".join(material_keywords[:m_count]) + ")"
    a_part = "(" + " OR ".join(ai_keywords[:a_count]) + ")"
    return f"{m_part} AND {a_part}"

# ================= SPRINGER =================
def check_springer():
    if not SPRINGER_API_KEY:
        return []

    results = []
    query = build_query()

    params = {
        "q": query,
        "p": 50,
        "api_key": SPRINGER_API_KEY
    }

    r = safe_get("https://api.springernature.com/meta/v2/json", params=params)
    if not r:
        return results

    data = r.json()

    for rec in data.get("records", []):
        doi = rec.get("doi")
        title = rec.get("title")
        journal = rec.get("publicationName") or "Unknown Journal"

        key = normalize_key(doi=doi)
        if not key or key in seen:
            continue

        seen.add(key)
        results.append(f"[Springer] {title}\nJournal: {journal}\n")

    return results

# ================= OPENALEX =================
def check_openalex():
    results = []
    query = build_query()
    encoded = urllib.parse.quote(query)

    url = f"https://api.openalex.org/works?search={encoded}&per-page=50"

    r = safe_get(url)
    if not r:
        return results

    data = r.json()

    for w in data.get("results", []):
        doi = w.get("doi")
        title = w.get("title")

        journal = "Unknown Journal"
        primary_location = w.get("primary_location")

        if isinstance(primary_location, dict):
            source = primary_location.get("source")
            if isinstance(source, dict):
                journal = source.get("display_name") or journal

        key = normalize_key(doi=doi)
        if not key or key in seen:
            continue

        seen.add(key)
        results.append(f"[OpenAlex] {title}\nJournal: {journal}\n")

    return results

# ================= CROSSREF =================
def check_crossref():
    results = []
    query = build_query()
    encoded = urllib.parse.quote(query)

    url = f"https://api.crossref.org/works?query={encoded}&rows=50"

    r = safe_get(url)
    if not r:
        return results

    data = r.json()

    for item in data.get("message", {}).get("items", []):
        doi = item.get("DOI")
        titles = item.get("title") or []
        journal_list = item.get("container-title") or []

        title = titles[0] if titles else "Untitled"
        journal = journal_list[0] if journal_list else "Unknown Journal"

        key = normalize_key(doi=doi)
        if not key or key in seen:
            continue

        seen.add(key)
        results.append(f"[Crossref] {title}\nJournal: {journal}\n")

    return results

# ================= ARXIV =================
def check_arxiv():
    results = []
    query = build_query()
    encoded = urllib.parse.quote(query)

    url = f"http://export.arxiv.org/api/query?search_query=all:{encoded}&sortBy=lastUpdatedDate&max_results=40"

    r = safe_get(url)
    if not r:
        return results

    feed = feedparser.parse(r.content)

    for entry in feed.entries:
        if hasattr(entry, "published_parsed"):
            pub = datetime(*entry.published_parsed[:6])
            if pub < DATE_THRESHOLD:
                continue

        key = normalize_key(url=entry.id)
        if key in seen:
            continue

        category = entry.tags[0]["term"] if entry.tags else "N/A"

        seen.add(key)
        results.append(f"[arXiv] {entry.title}\nCategory: {category}\n")

    return results

# ================= TELEGRAM =================
def send_telegram(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    chunks = [msg[i:i+3500] for i in range(0, len(msg), 3500)]
    for chunk in chunks:
        requests.post(url, json={"chat_id": CHAT_ID, "text": chunk})

# ================= DISCORD =================
def send_discord(msg):
    if not DISCORD_WEBHOOK:
        return

    chunks = [msg[i:i+DISCORD_LIMIT] for i in range(0, len(msg), DISCORD_LIMIT)]
    for chunk in chunks:
        requests.post(DISCORD_WEBHOOK, json={"content": chunk})

# ================= MAIN =================
def main():
    utc = datetime.utcnow()
    ist = utc + timedelta(hours=5, minutes=30)

    results = []
    results += check_springer()
    results += check_openalex()
    results += check_crossref()
    results += check_arxiv()

    msg = f"""
==============================
AI + Materials Intelligence
==============================

UTC : {utc.strftime('%Y-%m-%d %H:%M:%S')}
IST : {ist.strftime('%Y-%m-%d %H:%M:%S')}
Window : Last {DAYS_BACK} Days

Total Findings : {len(results)}

--------------------------------
"""

    used = len(msg)

    for r in results:
        if used + len(r) > CHAR_BUDGET:
            break
        msg += r + "\n"
        used += len(r)

    if not results:
        msg += "\nNo new AI-integrated materials research detected.\n"

    send_telegram(msg)
    send_discord(msg)
    save_seen()

if __name__ == "__main__":
    main()
