import requests
import json
import os
import urllib.parse
import feedparser
from datetime import datetime, timedelta

# ================= ENV =================

# Fixed typo to match your GitHub Secrets: CHARTID
TELEGRAM_TOKEN = os.getenv("TELEGRAMTOKEN")
CHAT_ID = os.getenv("CHARTID") 
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
SPRINGER_API_KEY = os.getenv("SPRINGER_API_KEY")

CONFIG_PATH = "config.json"
SEEN_FILE = "seen.json"
REPORT_DATA_FILE = "report_data.json"
HTML_OUTPUT = "index.html"

DAYS_BACK = 180
DATE_THRESHOLD = datetime.utcnow() - timedelta(days=DAYS_BACK)
FROM_DATE = DATE_THRESHOLD.strftime("%Y-%m-%d")

HTTP_TIMEOUT = 20
DISCORD_LIMIT = 1900
TELEGRAM_LIMIT = 4000 # Safety margin for 4096 limit

# ================= STORAGE =================

def load_json(path):
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except:
            return []
    return []

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

seen = set(load_json(SEEN_FILE))
report_data = load_json(REPORT_DATA_FILE)

# ================= NOTIFICATIONS =================

def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Telegram config missing.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    
    # Chunking to prevent 4096 character limit error
    for i in range(0, len(message), TELEGRAM_LIMIT):
        part = message[i:i+TELEGRAM_LIMIT]
        payload = {"chat_id": CHAT_ID, "text": part, "parse_mode": "HTML"}
        try:
            r = requests.post(url, json=payload, timeout=HTTP_TIMEOUT)
            r.raise_for_status()
        except Exception as e:
            print(f"Telegram Error: {e}")

def send_discord(message):
    if not DISCORD_WEBHOOK:
        print("Discord config missing.")
        return
    # Discord chunking
    for i in range(0, len(message), DISCORD_LIMIT):
        part = message[i:i+DISCORD_LIMIT]
        payload = {"content": part}
        try:
            r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=HTTP_TIMEOUT)
            r.raise_for_status()
        except Exception as e:
            print(f"Discord Error: {e}")

# ================= UTIL =================

def normalize_key(doi=None, url=None):
    if doi: return doi.lower().strip()
    if url: return url.lower().strip()
    return None

def safe_get(url, params=None):
    try:
        r = requests.get(url, params=params, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        return r
    except:
        return None

def build_query():
    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)
    domains = config["domains"]
    material_keywords = []
    for k, v in domains.items():
        if k != "ai_methods":
            material_keywords.extend(v)
    ai_keywords = domains.get("ai_methods", [])
    
    m = "(" + " OR ".join(material_keywords[:15]) + ")"
    a = "(" + " OR ".join(ai_keywords[:10]) + ")"
    return f"{m} AND {a}"

# ================= FETCHERS (Logic remains same) =================

def fetch_openalex():
    results = []
    query = urllib.parse.quote(build_query())
    url = f"https://api.openalex.org/works?search={query}&filter=from_publication_date:{FROM_DATE}&per-page=50"
    r = safe_get(url)
    if not r: return results
    for w in r.json().get("results", []):
        title, date, doi = w.get("title"), w.get("publication_date"), w.get("doi")
        if not title or not date: continue
        key = normalize_key(doi)
        if not key or key in seen: continue
        seen.add(key)
        results.append({"source": "OpenAlex", "title": title, "journal": "OpenAlex", "date": date, "url": doi})
    return results

def fetch_arxiv():
    results = []
    url = f"http://export.arxiv.org/api/query?search_query=all:{urllib.parse.quote(build_query())}&max_results=50"
    r = safe_get(url)
    if not r: return results
    feed = feedparser.parse(r.content)
    for entry in feed.entries:
        title, date = entry.title, entry.published[:10]
        key = normalize_key(url=entry.id)
        if key in seen: continue
        seen.add(key)
        results.append({"source": "arXiv", "title": title, "journal": "arXiv", "date": date, "url": entry.id})
    return results

# ================= HTML GENERATOR =================

def generate_html(data, utc, ist):
    data_sorted = sorted(data, key=lambda x: x["date"], reverse=True)
    cards = ""
    for d in data_sorted:
        link = d.get('url', '#')
        cards += f"""
        <div class="card">
            <div class="card-title">{d['title']}</div>
            <div class="card-meta">
                <span><b>Source:</b> {d['source']}</span> | 
                <span><b>Date:</b> {d['date']}</span>
            </div>
            <a href="{link}" target="_blank" class="link-btn">View Paper</a>
        </div>"""

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Crystal Research Intelligence</title>
        <style>
            :root {{ --bg: #0f172a; --card: #1e293b; --accent: #38bdf8; --text: #f1f5f9; }}
            body {{ background: var(--bg); color: var(--text); font-family: 'Segoe UI', sans-serif; margin: 0; padding: 20px; }}
            .container {{ max-width: 800px; margin: auto; }}
            header {{ border-bottom: 2px solid var(--accent); padding-bottom: 20px; margin-bottom: 30px; }}
            .card {{ background: var(--card); padding: 20px; margin: 15px 0; border-radius: 12px; border-left: 4px solid var(--accent); }}
            .card-title {{ font-size: 1.1rem; font-weight: bold; margin-bottom: 10px; color: var(--accent); }}
            .card-meta {{ font-size: 0.85rem; opacity: 0.8; margin-bottom: 15px; }}
            .link-btn {{ display: inline-block; padding: 8px 15px; background: var(--accent); color: var(--bg); text-decoration: none; border-radius: 5px; font-weight: bold; font-size: 0.8rem; }}
        </style>
    </head>
    <body>
        <div class="container">
            <header>
                <h1>💎 Crystal Research Intelligence</h1>
                <p>Last Sync (IST): {ist} | Total Papers: {len(data_sorted)}</p>
            </header>
            {cards}
        </div>
    </body>
    </html>"""
    with open(HTML_OUTPUT, "w", encoding="utf-8") as f:
        f.write(html)

# ================= MAIN =================

def main():
    print("Starting Research Sync...")
    utc = datetime.utcnow()
    ist = utc + timedelta(hours=5, minutes=30)

    # 1. Fetching
    new_found = []
    new_found += fetch_openalex()
    new_found += fetch_arxiv()
    # Add other fetchers here...

    if new_found:
        print(f"Found {len(new_found)} new papers. Sending notifications...")
        
        # 2. Construct Notification
        msg = f"<b>💎 Crystal Research Update</b>\n<i>{ist.strftime('%Y-%m-%d %H:%M')} IST</i>\n\n"
        for i, item in enumerate(new_found, 1):
            msg += f"{i}. <b>{item['title']}</b>\nSource: {item['source']}\n\n"
        
        send_telegram(msg)
        send_discord(msg)

        # 3. Update Database
        for n in new_found:
            report_data.append(n)
        
        save_json(SEEN_FILE, list(seen))
        save_json(REPORT_DATA_FILE, report_data)
    else:
        print("No new research discovered.")

    # Always regenerate HTML to reflect total history
    generate_html(report_data, utc.strftime("%Y-%m-%d %H:%M"), ist.strftime("%Y-%m-%d %H:%M"))

if __name__ == "__main__":
    main()
