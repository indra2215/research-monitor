import requests
import json
import os
import urllib.parse
import feedparser
from datetime import datetime, timedelta

# ================= ENV =================

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

HTTP_TIMEOUT = 20
TELEGRAM_LIMIT = 3900
DISCORD_LIMIT = 1900

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

# ================= UTIL =================

def normalize_key(doi=None, url=None):
    if doi:
        return doi.lower()
    if url:
        return url.lower()
    return None

def safe_get(url, params=None):
    try:
        r = requests.get(url, params=params, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        return r
    except Exception as e:
        print("HTTP ERROR:", e)
        return None

# ================= TELEGRAM =================

def send_telegram(msg):

    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Telegram secrets missing")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    for i in range(0, len(msg), TELEGRAM_LIMIT):

        chunk = msg[i:i+TELEGRAM_LIMIT]

        try:
            r = requests.post(url,
                json={
                    "chat_id": CHAT_ID,
                    "text": chunk,
                    "parse_mode": "HTML"
                },
                timeout=HTTP_TIMEOUT)

            print("Telegram status:", r.status_code)

        except Exception as e:
            print("Telegram send error:", e)

# ================= DISCORD =================

def send_discord(msg):

    if not DISCORD_WEBHOOK:
        print("Discord webhook missing")
        return

    for i in range(0, len(msg), DISCORD_LIMIT):

        chunk = msg[i:i+DISCORD_LIMIT]

        try:
            r = requests.post(
                DISCORD_WEBHOOK,
                json={"content": chunk},
                timeout=HTTP_TIMEOUT
            )

            print("Discord status:", r.status_code)

        except Exception as e:
            print("Discord error:", e)

# ================= QUERY =================

def build_query():

    config = load_json(CONFIG_PATH)

    material = []
    for k, v in config["domains"].items():
        if k != "ai_methods":
            material.extend(v)

    ai = config["domains"].get("ai_methods", [])

    m = "(" + " OR ".join(material[:15]) + ")"
    a = "(" + " OR ".join(ai[:10]) + ")"

    return f"{m} AND {a}"

# ================= OPENALEX =================

def fetch_openalex():

    results = []

    query = urllib.parse.quote(build_query())

    url = f"https://api.openalex.org/works?search={query}&per-page=50"

    r = safe_get(url)

    if not r:
        return results

    for w in r.json()["results"]:

        title = w.get("title")
        date = w.get("publication_date")
        doi = w.get("doi")

        if not title or not date:
            continue

        key = normalize_key(doi)

        if not key or key in seen:
            continue

        seen.add(key)

        results.append({
            "source": "OpenAlex",
            "title": title,
            "date": date,
            "url": doi
        })

    return results

# ================= NATURE RSS =================

def fetch_nature():

    feeds = [
        "https://www.nature.com/nature.rss",
        "https://www.nature.com/subjects/materials-science.rss",
        "https://www.nature.com/subjects/artificial-intelligence.rss"
    ]

    results = []

    for url in feeds:

        feed = feedparser.parse(url)

        for entry in feed.entries:

            title = entry.title
            date = entry.published[:10]
            link = entry.link

            key = normalize_key(url=link)

            if key in seen:
                continue

            seen.add(key)

            results.append({
                "source": "Nature",
                "title": title,
                "date": date,
                "url": link
            })

    return results

# ================= HTML =================

def generate_html(data, ist):

    cards = ""

    for d in sorted(data, key=lambda x: x["date"], reverse=True):

        cards += f"""
        <div class="card">
        <b>{d['title']}</b><br>
        Source: {d['source']}<br>
        Date: {d['date']}<br>
        <a href="{d['url']}" target="_blank">Open</a>
        </div>
        """

    html = f"""
<html>
<body style="background:#0f172a;color:white;font-family:Arial;padding:20px;">
<h2>Crystal Research Intelligence</h2>
Last sync IST: {ist}<br>
Total papers: {len(data)}<br>
{cards}
</body>
</html>
"""

    with open(HTML_OUTPUT, "w") as f:
        f.write(html)

# ================= MAIN =================

def main():

    utc = datetime.utcnow()
    ist = utc + timedelta(hours=5, minutes=30)

    new = []

    new += fetch_openalex()
    new += fetch_nature()

    for n in new:
        report_data.append(n)

    save_json(SEEN_FILE, list(seen))
    save_json(REPORT_DATA_FILE, report_data)

    generate_html(report_data, ist.strftime("%Y-%m-%d %H:%M"))

    msg = f"""
<b>Crystal Research Sync Complete</b>

New papers: {len(new)}
Total papers: {len(report_data)}

Time: {ist.strftime("%Y-%m-%d %H:%M IST")}
"""

    send_telegram(msg)
    send_discord(msg)

    print("Sync complete")

# ================= ENTRY =================

if __name__ == "__main__":
    main()
