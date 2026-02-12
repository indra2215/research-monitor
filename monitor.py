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

DAYS_BACK = 3
DATE_THRESHOLD = datetime.utcnow() - timedelta(days=DAYS_BACK)
RESULTS_LIMIT = 8
PRIMARY_RATIO = 0.8
MAX_MESSAGE_LENGTH = 3500
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

def classify_paper(title, abstract=""):
    text = (title + " " + abstract).lower()

    material_match = any(contains(text, kw) for kw in material_keywords)
    ai_match = any(contains(text, kw) for kw in ai_keywords)

    if material_match and ai_match:
        return "AI+Materials"
    elif material_match:
        return "Materials-Only"
    else:
        return None

def safe_get(url):
    try:
        r = requests.get(url, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        return r
    except:
        return None

# ================= SOURCES =================
def check_arxiv():
    results = []
    query = urllib.parse.quote(" OR ".join(material_keywords[:10]))
    url = f"http://export.arxiv.org/api/query?search_query=all:{query}&sortBy=lastUpdatedDate&max_results=15"
    r = safe_get(url)
    if not r:
        return []

    feed = feedparser.parse(r.content)

    for e in feed.entries:
        key = e.id
        if key in seen_links:
            continue

        category = classify_paper(e.title, e.summary)
        if category:
            seen_links.add(key)
            results.append((category, f"[arXiv] {e.title}\n{e.link}\n"))

    return results

# ================= TELEGRAM =================
def send_telegram(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    chunks = [msg[i:i+MAX_MESSAGE_LENGTH] for i in range(0, len(msg), MAX_MESSAGE_LENGTH)]
    for c in chunks:
        requests.post(url, json={"chat_id": CHAT_ID, "text": c})

# ================= DISCORD =================
def send_discord(msg):
    if not DISCORD_WEBHOOK:
        return
    requests.post(DISCORD_WEBHOOK, json={"content": msg})

# ================= MAIN =================
def main():
    utc = datetime.utcnow()
    ist = utc + timedelta(hours=5, minutes=30)

    collected = check_arxiv()

    primary = [r for r in collected if r[0] == "AI+Materials"]
    secondary = [r for r in collected if r[0] == "Materials-Only"]

    primary_limit = int(RESULTS_LIMIT * PRIMARY_RATIO)

    final = primary[:primary_limit]

    if len(final) < RESULTS_LIMIT:
        remaining = RESULTS_LIMIT - len(final)
        final += secondary[:remaining]

    msg = f"""
==============================
Daily Research Intelligence
==============================

UTC : {utc.strftime('%Y-%m-%d %H:%M:%S')}
IST : {ist.strftime('%Y-%m-%d %H:%M:%S')}

Primary (AI+Materials): {len(primary)}
Fallback (Materials Only): {len(secondary)}
Delivered: {len(final)}

--------------------------------
"""

    for cat, content in final:
        msg += f"\n[{cat}]\n{content}"

    if not final:
        msg += "\nNo relevant integration research found.\n"

    send_telegram(msg)
    send_discord(msg)
    save_seen()

if __name__ == "__main__":
    main()
