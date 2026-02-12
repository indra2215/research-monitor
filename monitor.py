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
REPORT_DATA_FILE = "report_data.json"
HTML_OUTPUT = "report.html"

DAYS_BACK = 180
DATE_THRESHOLD = datetime.utcnow() - timedelta(days=DAYS_BACK)
FROM_DATE = DATE_THRESHOLD.strftime("%Y-%m-%d")

CHAR_BUDGET = 3200
DISCORD_LIMIT = 1900
HTTP_TIMEOUT = 15

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
def load_seen():
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r") as f:
                return set(json.load(f))
        except:
            return set()
    return set()

seen = load_seen()

def save_seen():
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)

def normalize_key(doi=None, url=None):
    if doi:
        return doi.lower().strip()
    if url:
        return url.lower().strip()
    return None

def safe_get(url, params=None):
    try:
        r = requests.get(url, params=params, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        return r
    except:
        return None

# ================= QUERY =================
def build_query(m_count=12, a_count=8):
    m_part = "(" + " OR ".join(material_keywords[:m_count]) + ")"
    a_part = "(" + " OR ".join(ai_keywords[:a_count]) + ")"
    return f"{m_part} AND {a_part}"

# ================= SOURCES =================
def check_openalex():
    results = []
    query = build_query()
    encoded = urllib.parse.quote(query)

    url = (
        f"https://api.openalex.org/works?"
        f"search={encoded}"
        f"&filter=from_publication_date:{FROM_DATE}"
        f"&per-page=50"
    )

    r = safe_get(url)
    if not r:
        return results

    for w in r.json().get("results", []):
        doi = w.get("doi")
        title = w.get("title")
        pub_date = w.get("publication_date")

        if not pub_date:
            continue

        pub_dt = datetime.strptime(pub_date, "%Y-%m-%d")
        if pub_dt < DATE_THRESHOLD:
            continue

        journal = "Unknown"
        primary = w.get("primary_location")
        if isinstance(primary, dict):
            source = primary.get("source")
            if isinstance(source, dict):
                journal = source.get("display_name", "Unknown")

        key = normalize_key(doi=doi)
        if not key or key in seen:
            continue

        seen.add(key)
        results.append({
            "source": "OpenAlex",
            "title": title,
            "journal": journal,
            "date": pub_date
        })

    return results

# ================= REPORT DATA STORAGE =================
def load_report_data():
    if os.path.exists(REPORT_DATA_FILE):
        try:
            with open(REPORT_DATA_FILE, "r") as f:
                return json.load(f)
        except:
            return []
    return []

def save_report_data(data):
    with open(REPORT_DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

# ================= HTML DASHBOARD =================
def generate_html(data, utc, ist):
    total = len(data)

    by_source = {}
    for item in data:
        by_source[item["source"]] = by_source.get(item["source"], 0) + 1

    html = f"""
    <html>
    <head>
        <title>AI + Materials Intelligence</title>
        <style>
            body {{
                font-family: Arial;
                background-color: #f4f6f9;
                margin: 40px;
            }}
            h1 {{
                color: #0A3D62;
            }}
            .stats {{
                background: white;
                padding: 15px;
                border-radius: 8px;
                margin-bottom: 20px;
            }}
            .card {{
                background: white;
                padding: 12px;
                margin-bottom: 10px;
                border-left: 4px solid #0A3D62;
                border-radius: 6px;
            }}
            .small {{
                color: #666;
                font-size: 12px;
            }}
        </style>
    </head>
    <body>
        <h1>AI + Materials Intelligence Dashboard</h1>

        <div class="stats">
            <b>UTC:</b> {utc}<br>
            <b>IST:</b> {ist}<br>
            <b>Window:</b> Last {DAYS_BACK} Days<br>
            <b>Total Findings:</b> {total}<br><br>
            <b>By Source:</b><br>
    """

    for src, count in by_source.items():
        html += f"{src}: {count}<br>"

    html += "</div>"

    for item in sorted(data, key=lambda x: x["date"], reverse=True):
        html += f"""
        <div class="card">
            <b>{item['title']}</b><br>
            Source: {item['source']}<br>
            Journal: {item['journal']}<br>
            <span class="small">Published: {item['date']}</span>
        </div>
        """

    html += "</body></html>"

    with open(HTML_OUTPUT, "w", encoding="utf-8") as f:
        f.write(html)

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
    chunks = [msg[i:i+DISCORD_LIMIT] for i in range(0, len(msg), DISCORD_LIMIT)]
    for chunk in chunks:
        requests.post(DISCORD_WEBHOOK, json={"content": chunk})

# ================= MAIN =================
def main():
    utc = datetime.utcnow()
    ist = utc + timedelta(hours=5, minutes=30)

    new_results = check_openalex()

    existing_data = load_report_data()

    # Merge new results
    for item in new_results:
        existing_data.append(item)

    save_report_data(existing_data)
    save_seen()

    # Message
    msg = f"""
AI + Materials Intelligence

UTC: {utc}
IST: {ist}

New Findings: {len(new_results)}
Total Stored: {len(existing_data)}
"""

    send_telegram(msg)
    send_discord(msg)

    generate_html(existing_data, utc, ist)

if __name__ == "__main__":
    main()
