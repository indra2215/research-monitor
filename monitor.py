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

CONFIG_PATH = "config.json"
SEEN_FILE = "seen.json"

# =========================
# SETTINGS
# =========================
DAYS_BACK = 3
BATCH_SIZE = 20
MAX_MESSAGE_LENGTH = 3900
RESULTS_LIMIT = 10
HTTP_TIMEOUT = 10
RETRY_COUNT = 2
RETRY_BACKOFF = 2

DATE_THRESHOLD = datetime.utcnow() - timedelta(days=DAYS_BACK)

# =========================
# LOAD KEYWORDS
# =========================
if not os.path.exists(CONFIG_PATH):
    raise SystemExit("Missing config.json")

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    config = json.load(f)

keywords = []
for domain in config.get("domains", {}).values():
    keywords.extend(domain)

keywords = list(dict.fromkeys([k.strip() for k in keywords if k]))

# =========================
# MEMORY
# =========================
if os.path.exists(SEEN_FILE):
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            seen_links = set(json.load(f))
    except:
        seen_links = set()
else:
    seen_links = set()

def save_seen():
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen_links), f)

# =========================
# UTILITIES
# =========================
def chunk_keywords(lst, size=BATCH_SIZE):
    for i in range(0, len(lst), size):
        yield lst[i:i + size]

def safe_get(url, params=None, headers=None):
    for attempt in range(RETRY_COUNT + 1):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=HTTP_TIMEOUT)
            r.raise_for_status()
            return r
        except Exception as e:
            if attempt < RETRY_COUNT:
                time.sleep(RETRY_BACKOFF)
            else:
                print("Request failed:", url, e)
    return None
#discord webhook--integration

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")

def send_discord(message):
    if not DISCORD_WEBHOOK:
        print("Discord webhook missing.")
        return

    chunks = [message[i:i+1900] for i in range(0, len(message), 1900)]

    for chunk in chunks:
        try:
            r = requests.post(DISCORD_WEBHOOK, json={"content": chunk})
            print("Discord response:", r.status_code)
        except Exception as e:
            print("Discord error:", e)


# =========================
# SCORING
# =========================
def score_text(title, abstract="", citation_count=0):
    score = 0
    text = (title + " " + abstract).lower()

    for kw in keywords:
        if kw.lower() in title.lower():
            score += 5
        if kw.lower() in text:
            score += 3

    if citation_count > 5:
        score += 1

    return score

def classify(score):
    if score >= 8:
        return "HIGH"
    if score >= 3:
        return "MEDIUM"
    return None

# =========================
# TELEGRAM
# =========================
def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Telegram credentials missing.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    chunks = [message[i:i+MAX_MESSAGE_LENGTH] for i in range(0, len(message), MAX_MESSAGE_LENGTH)]

    for chunk in chunks:
        try:
            r = requests.post(url, json={
                "chat_id": CHAT_ID,
                "text": chunk
            }, timeout=HTTP_TIMEOUT)
            print("Telegram response:", r.status_code)
        except Exception as e:
            print("Telegram error:", e)

# =========================
# PROCESS ITEM
# =========================
def process_item(title, link, abstract="", citation=0, published_date=None):
    if not link:
        return None

    if link in seen_links:
        return None

    if published_date and published_date < DATE_THRESHOLD:
        return None

    score = score_text(title, abstract, citation)
    level = classify(score)

    if level:
        seen_links.add(link)
        return f"[{level}] {title}\n{link}\n"

    return None

# =========================
# SOURCES
# =========================
def check_arxiv():
    items = []
    base = "http://export.arxiv.org/api/query"

    for batch in chunk_keywords(keywords):
        query = " OR ".join([f'all:"{kw}"' for kw in batch])
        encoded = urllib.parse.quote(query, safe='')
        url = f"{base}?search_query={encoded}&sortBy=lastUpdatedDate&max_results=10"

        r = safe_get(url)
        if not r:
            continue

        feed = feedparser.parse(r.content)

        for entry in feed.entries:
            if not hasattr(entry, "published_parsed"):
                continue

            try:
                published = datetime(*entry.published_parsed[:6])
            except:
                published = None

            item = process_item(entry.title, entry.link, entry.summary, 0, published)
            if item:
                items.append(item)

    return items

def check_openalex():
    items = []
    base = "https://api.openalex.org/works"

    for batch in chunk_keywords(keywords):
        query = urllib.parse.quote(" OR ".join(batch), safe='')
        url = f"{base}?search={query}&per-page=10"

        r = safe_get(url)
        if not r:
            continue

        data = r.json()

        for w in data.get("results", []):
            title = w.get("title", "")
            link = w.get("id", "")
            citation = w.get("cited_by_count", 0)

            pub_date = w.get("publication_date")
            published = None
            if pub_date:
                try:
                    published = datetime.strptime(pub_date, "%Y-%m-%d")
                except:
                    pass

            item = process_item(title, link, "", citation, published)
            if item:
                items.append(item)

    return items

def check_crossref():
    items = []
    base = "https://api.crossref.org/works"

    for batch in chunk_keywords(keywords):
        query = urllib.parse.quote(" OR ".join(batch), safe='')
        url = f"{base}?query={query}&rows=10"

        r = safe_get(url)
        if not r:
            continue

        data = r.json()

        for it in data.get("message", {}).get("items", []):
            title = (it.get("title") or [""])[0]
            link = it.get("URL", "")
            citation = it.get("is-referenced-by-count", 0)

            item = process_item(title, link, "", citation, None)
            if item:
                items.append(item)

    return items

def check_semantic():
    if not S2_API_KEY:
        return []

    items = []
    headers = {"x-api-key": S2_API_KEY}
    url = "https://api.semanticscholar.org/graph/v1/paper/search"

    for batch in chunk_keywords(keywords):
        params = {
            "query": " OR ".join(batch),
            "limit": 10,
            "fields": "title,url,citationCount,year"
        }

        r = safe_get(url, params=params, headers=headers)
        if not r:
            continue

        data = r.json()

        for p in data.get("data", []):
            title = p.get("title", "")
            link = p.get("url", "")
            citation = p.get("citationCount", 0)

            item = process_item(title, link, "", citation, None)
            if item:
                items.append(item)

    return items

# =========================
# MAIN
# =========================
def main():
    utc_now = datetime.utcnow()
    ist_now = utc_now + timedelta(hours=5, minutes=30)

    results = []
    sources_checked = 0

    for func in [check_arxiv, check_openalex, check_crossref, check_semantic]:
        results += func()
        sources_checked += 1

    unique_results = list(dict.fromkeys(results))[:RESULTS_LIMIT]

    message = f"""
==============================
Daily Research Monitor Report
==============================

UTC Time : {utc_now.strftime('%Y-%m-%d %H:%M:%S')}
IST Time : {ist_now.strftime('%Y-%m-%d %H:%M:%S')}

Keywords Loaded : {len(keywords)}
API Sources Checked : {sources_checked}
Relevant Matches Found : {len(unique_results)}
Memory Size : {len(seen_links)}

--------------------------------
"""

    if unique_results:
        message += "\nRecent Related Findings:\n\n"
        message += "\n".join(unique_results)
    else:
        message += "\nNo new relevant research in the last 3 days.\n"

    send_telegram(message)
    send_discord(message)
    save_seen()

    print("Run completed.")

if __name__ == "__main__":
    main()
