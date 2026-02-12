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

CONFIG_PATH = "config.json"
SEEN_FILE = "seen.json"

DAYS_BACK = 180
DATE_THRESHOLD = datetime.utcnow() - timedelta(days=DAYS_BACK)

CHAR_BUDGET = 3200   # strict message size control
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

def classify_paper(title, abstract=""):
    text = (title + " " + abstract).lower()

    material_match = any(contains(text, kw) for kw in material_keywords)
    ai_match = any(contains(text, kw) for kw in ai_keywords)

    if material_match and ai_match:
        return "AI+Materials"
    elif material_match:
        return "Materials-Only"
    return None

def safe_get(url):
    try:
        r = requests.get(url, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        return r
    except:
        return None

def is_recent(entry):
    if hasattr(entry, "published_parsed"):
        try:
            pub = datetime(*entry.published_parsed[:6])
            return pub >= DATE_THRESHOLD
        except:
            return True
    return True

def normalize(link):
    return link.strip().lower()

# ================= ARXIV =================
def check_arxiv():
    results = []

    # Strict AND query for AI + Materials
    material_query = "(" + " OR ".join(material_keywords[:20]) + ")"
    ai_query = "(" + " OR ".join(ai_keywords[:15]) + ")"

    full_query = urllib.parse.quote(f"{material_query} AND {ai_query}")

    url = f"http://export.arxiv.org/api/query?search_query=all:{full_query}&sortBy=lastUpdatedDate&max_results=30"

    r = safe_get(url)
    if not r:
        return []

    feed = feedparser.parse(r.content)

    for e in feed.entries:
        if not is_recent(e):
            continue

        link = normalize(e.link)

        if link in seen_links:
            continue

        category = classify_paper(e.title, e.summary)
        if category:
            seen_links.add(link)
            results.append((category, link))

    return results

# ================= TELEGRAM =================
def send_telegram(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    chunks = [msg[i:i+3500] for i in range(0, len(msg), 3500)]
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

    # Remove duplicates preserving order
    temp_seen = set()
    unique = []
    for cat, link in collected:
        if link not in temp_seen:
            temp_seen.add(link)
            unique.append((cat, link))

    # Prioritize AI+Materials
    primary = [r for r in unique if r[0] == "AI+Materials"]
    secondary = [r for r in unique if r[0] == "Materials-Only"]

    ranked = primary + secondary

    msg = f"""
==============================
Daily Research Intelligence
==============================

UTC : {utc.strftime('%Y-%m-%d %H:%M:%S')}
IST : {ist.strftime('%Y-%m-%d %H:%M:%S')}

AI+Materials Found : {len(primary)}
Materials-Only Found : {len(secondary)}

--------------------------------
"""

    used_chars = len(msg)

    for cat, link in ranked:
        line = f"[{cat}] {link}\n"
        if used_chars + len(line) > CHAR_BUDGET:
            break
        msg += line
        used_chars += len(line)

    if len(ranked) == 0:
        msg += "\nNo relevant AI-integrated materials research found in last 14 days.\n"

    send_telegram(msg)
    send_discord(msg)
    save_seen()

if __name__ == "__main__":
    main()
