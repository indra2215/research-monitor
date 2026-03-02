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

def load_json(path, default=None):
    """
    BUG FIX #1: Added 'default' param.
    config.json is a dict, seen.json/report_data.json are lists.
    Returning wrong type caused TypeError: list indices must be integers.
    """
    if default is None:
        default = []
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"Failed to load {path}: {e}")
            return default
    return default

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

seen_list = load_json(SEEN_FILE, default=[])
seen = set(seen_list)
report_data = load_json(REPORT_DATA_FILE, default=[])

# ================= UTIL =================

def normalize_key(doi=None, url=None, title=None):
    """
    BUG FIX #7: Added title fallback so papers without DOI/URL aren't silently dropped.
    """
    if doi:
        return doi.strip().lower()
    if url:
        return url.strip().lower()
    if title:
        return title.strip().lower()
    return None

def safe_get(url, params=None):
    try:
        r = requests.get(url, params=params, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        return r
    except Exception as e:
        print("HTTP ERROR:", e)
        return None

def is_recent(date_str):
    """
    BUG FIX #2: DATE_THRESHOLD was defined but never applied anywhere.
    Now used in both fetchers to filter old papers.
    """
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt >= DATE_THRESHOLD
    except Exception:
        return True  # If we can't parse date, don't discard

# ================= TELEGRAM =================

def send_telegram(msg):
    """
    BUG FIX #4: Chunking at raw char boundaries splits HTML tags,
    causing Telegram to reject with 400 parse error.
    Strip HTML tags for chunked sends, or send plain text.
    Safe approach: use plain text (no parse_mode) for chunked messages.
    """
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Telegram secrets missing")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    chunks = []
    current = ""
    for line in msg.split("\n"):
        if len(current) + len(line) + 1 > TELEGRAM_LIMIT:
            chunks.append(current)
            current = line
        else:
            current += ("\n" if current else "") + line
    if current:
        chunks.append(current)

    for chunk in chunks:
        try:
            r = requests.post(
                url,
                json={
                    "chat_id": CHAT_ID,
                    "text": chunk,
                    "parse_mode": "HTML"
                },
                timeout=HTTP_TIMEOUT
            )
            if r.status_code != 200:
                # Fallback: retry without parse_mode if HTML parse fails
                r2 = requests.post(
                    url,
                    json={
                        "chat_id": CHAT_ID,
                        "text": chunk
                    },
                    timeout=HTTP_TIMEOUT
                )
                print("Telegram fallback status:", r2.status_code)
            else:
                print("Telegram status:", r.status_code)
        except Exception as e:
            print("Telegram send error:", e)

# ================= DISCORD =================

def send_discord(msg):
    if not DISCORD_WEBHOOK:
        print("Discord webhook missing")
        return

    for i in range(0, len(msg), DISCORD_LIMIT):
        chunk = msg[i:i + DISCORD_LIMIT]
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
    """
    BUG FIX #1: config.json must be loaded as dict default={}.
    """
    config = load_json(CONFIG_PATH, default={})

    if not config or "domains" not in config:
        print("ERROR: config.json missing or malformed")
        return ""

    material = []
    for k, v in config["domains"].items():
        if k != "ai_methods":
            material.extend(v)

    ai = config["domains"].get("ai_methods", [])

    if not material or not ai:
        print("WARNING: Empty material or ai_methods in config")
        return ""

    m = "(" + " OR ".join(material[:15]) + ")"
    a = "(" + " OR ".join(ai[:10]) + ")"

    return f"{m} AND {a}"

# ================= OPENALEX =================

def fetch_openalex():
    results = []
    query_str = build_query()

    if not query_str:
        print("Skipping OpenAlex: empty query")
        return results

    query = urllib.parse.quote(query_str)
    url = f"https://api.openalex.org/works?search={query}&per-page=50"

    r = safe_get(url)
    if not r:
        return results

    try:
        works = r.json().get("results", [])
    except Exception as e:
        print("OpenAlex JSON parse error:", e)
        return results

    for w in works:
        title = w.get("title")
        date = w.get("publication_date")
        doi = w.get("doi")
        landing = w.get("primary_location", {}) or {}
        link = landing.get("landing_page_url") or doi or ""

        if not title or not date:
            continue

        # BUG FIX #2: Apply date filter
        if not is_recent(date):
            continue

        # BUG FIX #7: Fallback to URL or title if no DOI
        key = normalize_key(doi=doi, url=link, title=title)
        if not key or key in seen:
            continue

        seen.add(key)
        results.append({
            "source": "OpenAlex",
            "title": title,
            "date": date,
            "url": link
        })

    return results

# ================= NATURE RSS =================

def is_relevant(title, config):
    """
    BUG FIX #3: Nature RSS returns ALL papers from general feed.
    This checks if the paper title contains any of our keywords.
    """
    if not config or "domains" not in config:
        return True  # If no config, allow everything

    keywords = []
    for k, v in config["domains"].items():
        keywords.extend(v)

    title_lower = title.lower()
    return any(kw.lower() in title_lower for kw in keywords)

def fetch_nature():
    feeds = [
        "https://www.nature.com/subjects/materials-science.rss",
        "https://www.nature.com/subjects/artificial-intelligence.rss"
        # Removed generic nature.rss — too noisy, no relevance filtering possible
    ]

    config = load_json(CONFIG_PATH, default={})
    results = []

    for url in feeds:
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            print(f"feedparser error on {url}: {e}")
            continue

        for entry in feed.entries:
            title = getattr(entry, "title", None)
            link = getattr(entry, "link", None)

            if not title or not link:
                continue

            # BUG FIX #5: entry.published may not exist — use getattr with fallback
            raw_date = getattr(entry, "published", None) or getattr(entry, "updated", None)
            if raw_date:
                date = raw_date[:10]
            else:
                date = datetime.utcnow().strftime("%Y-%m-%d")

            # BUG FIX #2: Apply date filter
            if not is_recent(date):
                continue

            # BUG FIX #3: Relevance filter for Nature
            if not is_relevant(title, config):
                continue

            key = normalize_key(url=link, title=title)
            if not key or key in seen:
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
        title = d.get("title", "No Title")
        source = d.get("source", "Unknown")
        date = d.get("date", "")
        url = d.get("url", "#")
        cards += f"""
        <div class="card" style="background:#1e293b;margin:10px 0;padding:15px;border-radius:8px;">
        <b>{title}</b><br>
        <span style="color:#94a3b8;">Source: {source} &nbsp;|&nbsp; Date: {date}</span><br>
        <a href="{url}" target="_blank" style="color:#38bdf8;">Open Paper</a>
        </div>
        """

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Crystal Research Intelligence</title>
</head>
<body style="background:#0f172a;color:white;font-family:Arial;padding:20px;max-width:900px;margin:auto;">
<h2 style="color:#38bdf8;">Crystal Research Intelligence</h2>
<p>Last sync IST: {ist}<br>Total papers: {len(data)}</p>
{cards}
</body>
</html>"""

    with open(HTML_OUTPUT, "w") as f:
        f.write(html)

# ================= MAIN =================

def main():
    utc = datetime.utcnow()
    ist = utc + timedelta(hours=5, minutes=30)

    new = []
    new += fetch_openalex()
    new += fetch_nature()

    # BUG FIX #6: Check for duplicates before appending to report_data
    existing_keys = set()
    for item in report_data:
        k = normalize_key(
            doi=item.get("url"),
            title=item.get("title")
        )
        if k:
            existing_keys.add(k)

    added = 0
    for n in new:
        k = normalize_key(doi=n.get("url"), title=n.get("title"))
        if k and k not in existing_keys:
            report_data.append(n)
            existing_keys.add(k)
            added += 1

    save_json(SEEN_FILE, list(seen))
    save_json(REPORT_DATA_FILE, report_data)
    generate_html(report_data, ist.strftime("%Y-%m-%d %H:%M"))

    msg = f"""<b>Crystal Research Sync Complete</b>

New papers: {added}
Total papers: {len(report_data)}
Time: {ist.strftime("%Y-%m-%d %H:%M IST")}"""

    # DEBUG: Verify secrets are loaded before attempting to send
    print("=== SECRET CHECK ===")
    print("TG token set:", bool(TELEGRAM_TOKEN))
    print("Chat ID set:", bool(CHAT_ID))
    print("Discord set:", bool(DISCORD_WEBHOOK))
    print("====================")

    send_telegram(msg)
    send_discord(msg)
    print("Sync complete. New:", added, "| Total:", len(report_data))

# ================= ENTRY =================

if __name__ == "__main__":
    main()
