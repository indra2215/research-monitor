import requests
import feedparser
import json
import os
import urllib.parse
import re
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
HTTP_TIMEOUT = 10

# ================= LOAD CONFIG =================
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    config = json.load(f)

domains = config["domains"]

material_keywords = []
for k, v in domains.items():
    if k != "ai_methods":
        material_keywords.extend(v)

ai_keywords = domains.get("ai_methods", [])

material_keywords = list(set(material_keywords))
ai_keywords = list(set(ai_keywords))

# ================= MEMORY =================
if os.path.exists(SEEN_FILE):
    with open(SEEN_FILE, "r", encoding="utf-8") as f:
        seen_links = set(json.load(f))
else:
    seen_links = set()

def save_seen():
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen_links), f)

# ================= UTIL =================
def contains(text, keyword):
    pattern = r'\b' + re.escape(keyword.lower()) + r'\b'
    return re.search(pattern, text.lower()) is not None

def classify(title, abstract=""):
    text = (title + " " + abstract).lower()
    material_match = any(contains(text, kw) for kw in material_keywords)
    ai_match = any(contains(text, kw) for kw in ai_keywords)

    if material_match and ai_match:
        return "AI+Materials"
    elif material_match:
        return "Materials-Only"
    return None

def safe_get(url, params=None, headers=None):
    try:
        r = requests.get(url, params=params, headers=headers, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        return r
    except:
        return None

def normalize(link):
    return link.strip().lower()

# ================= ARXIV =================
def check_arxiv():
    results = []
    query = urllib.parse.quote(" OR ".join(material_keywords[:30]))
    url = f"http://export.arxiv.org/api/query?search_query=all:{query}&sortBy=lastUpdatedDate&max_results=50"

    r = safe_get(url)
    if not r:
        return results

    feed = feedparser.parse(r.content)

    for e in feed.entries:
        if hasattr(e, "published_parsed"):
            pub = datetime(*e.published_parsed[:6])
            if pub < DATE_THRESHOLD:
                continue

        link = normalize(e.link)
        if link in seen_links:
            continue

        cat = classify(e.title, e.summary)
        if cat:
            seen_links.add(link)
            results.append((cat, link))

    return results

# ================= SPRINGER =================
def check_springer():
    if not SPRINGER_API_KEY:
        return []

    results = []

    query = " OR ".join(material_keywords[:30])
    url = "https://api.springernature.com/meta/v2/json"
    params = {
        "q": query,
        "p": 50,
        "api_key": SPRINGER_API_KEY
    }

    r = safe_get(url, params=params)
    if not r:
        return results

    data = r.json()

    for rec in data.get("records", []):
        title = rec.get("title", "")
        abstract = rec.get("abstract", "")
        doi = rec.get("doi")

        if not doi:
            continue

        link = normalize(f"https://doi.org/{doi}")

        if link in seen_links:
            continue

        cat = classify(title, abstract)
        if cat:
            seen_links.add(link)
            results.append((cat, link))

    return results

# ================= OPENALEX =================
def check_openalex():
    results = []

    query = urllib.parse.quote(" OR ".join(material_keywords[:30]))
    url = f"https://api.openalex.org/works?search={query}&per-page=50"

    r = safe_get(url)
    if not r:
        return results

    data = r.json()

    for work in data.get("results", []):
        title = work.get("title", "")
        abstract = ""
        doi = work.get("doi")

        if not doi:
            continue

        link = normalize(f"https://doi.org/{doi}")

        if link in seen_links:
            continue

        cat = classify(title, abstract)
        if cat:
            seen_links.add(link)
            results.append((cat, link))

    return results

# ================= CROSSREF =================
def check_crossref():
    results = []

    query = urllib.parse.quote(" OR ".join(material_keywords[:30]))
    url = f"https://api.crossref.org/works?query={query}&rows=50"

    r = safe_get(url)
    if not r:
        return results

    data = r.json()

    for item in data.get("message", {}).get("items", []):
        title = (item.get("title") or [""])[0]
        doi = item.get("DOI")

        if not doi:
            continue

        link = normalize(f"https://doi.org/{doi}")

        if link in seen_links:
            continue

        cat = classify(title)
        if cat:
            seen_links.add(link)
            results.append((cat, link))

    return results

# ================= TELEGRAM =================
def send_telegram(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHAT_ID, "text": msg})

# ================= DISCORD =================
def send_discord(msg):
    if not DISCORD_WEBHOOK:
        return
    requests.post(DISCORD_WEBHOOK, json={"content": msg})

# ================= MAIN =================
def main():
    utc = datetime.utcnow()
    ist = utc + timedelta(hours=5, minutes=30)

    collected = []
    for func in [check_arxiv, check_springer, check_openalex, check_crossref]:
        try:
            collected += func()
        except:
            continue

    # Remove duplicates preserving order
    temp = set()
    unique = []
    for cat, link in collected:
        if link not in temp:
            temp.add(link)
            unique.append((cat, link))

    primary = [r for r in unique if r[0] == "AI+Materials"]
    secondary = [r for r in unique if r[0] == "Materials-Only"]

    ranked = primary + secondary

    msg = f"""
==============================
Daily Research Intelligence
==============================

UTC : {utc.strftime('%Y-%m-%d %H:%M:%S')}
IST : {ist.strftime('%Y-%m-%d %H:%M:%S')}
Window : Last {DAYS_BACK} Days

AI+Materials : {len(primary)}
Materials-Only : {len(secondary)}

--------------------------------
"""

    used = len(msg)

    for cat, link in ranked:
        line = f"[{cat}] {link}\n"
        if used + len(line) > CHAR_BUDGET:
            break
        msg += line
        used += len(line)

    if not ranked:
        msg += "\nNo relevant AI-integrated materials research found.\n"

    send_telegram(msg)
    send_discord(msg)
    save_seen()

if __name__ == "__main__":
    main()
