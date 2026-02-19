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
FROM_DATE = DATE_THRESHOLD.strftime("%Y-%m-%d")

HTTP_TIMEOUT = 20
DISCORD_LIMIT = 1900

# ================= LOAD CONFIG =================

with open(CONFIG_PATH, "r") as f:
    config = json.load(f)

domains = config["domains"]

material_keywords = []
for k, v in domains.items():
    if k != "ai_methods":
        material_keywords.extend(v)

ai_keywords = domains.get("ai_methods", [])

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

def build_query():

    m = "(" + " OR ".join(material_keywords[:10]) + ")"
    a = "(" + " OR ".join(ai_keywords[:8]) + ")"

    return f"{m} AND {a}"

# ================= OPENALEX =================

def fetch_openalex():

    results = []

    query = urllib.parse.quote(build_query())

    url = (
        f"https://api.openalex.org/works?"
        f"search={query}"
        f"&filter=from_publication_date:{FROM_DATE}"
        f"&per-page=50"
    )

    r = safe_get(url)

    if not r:
        return results

    for w in r.json()["results"]:

        title = w.get("title")
        date = w.get("publication_date")
        doi = w.get("doi")

        if not title or not date:
            continue

        if datetime.strptime(date, "%Y-%m-%d") < DATE_THRESHOLD:
            continue

        journal = "Unknown"

        primary = w.get("primary_location")

        if primary and primary.get("source"):
            journal = primary["source"].get("display_name", "Unknown")

        key = normalize_key(doi)

        if not key or key in seen:
            continue

        seen.add(key)

        results.append({
            "source": "OpenAlex",
            "title": title,
            "journal": journal,
            "date": date
        })

    return results

# ================= SPRINGER (Nature, Scientific Reports etc) =================

def fetch_springer():

    if not SPRINGER_API_KEY:
        return []

    results = []

    query = build_query()

    params = {
        "q": query,
        "api_key": SPRINGER_API_KEY,
        "p": 50
    }

    r = safe_get(
        "https://api.springernature.com/meta/v2/json",
        params=params
    )

    if not r:
        return results

    for rec in r.json().get("records", []):

        title = rec.get("title")
        date = rec.get("publicationDate")
        doi = rec.get("doi")
        journal = rec.get("publicationName", "Springer")

        if not title or not date:
            continue

        try:
            if datetime.strptime(date[:10], "%Y-%m-%d") < DATE_THRESHOLD:
                continue
        except:
            continue

        key = normalize_key(doi)

        if not key or key in seen:
            continue

        seen.add(key)

        results.append({
            "source": "Springer Nature",
            "title": title,
            "journal": journal,
            "date": date[:10]
        })

    return results

# ================= CROSSREF =================

def fetch_crossref():

    results = []

    query = urllib.parse.quote(build_query())

    url = f"https://api.crossref.org/works?query={query}&rows=50"

    r = safe_get(url)

    if not r:
        return results

    for item in r.json()["message"]["items"]:

        title = item.get("title", [""])[0]
        doi = item.get("DOI")
        journal = item.get("container-title", ["Unknown"])[0]

        date_parts = item.get("issued", {}).get("date-parts", [[None]])

        if not date_parts[0][0]:
            continue

        year = date_parts[0][0]
        month = date_parts[0][1] if len(date_parts[0]) > 1 else 1
        day = date_parts[0][2] if len(date_parts[0]) > 2 else 1

        date = f"{year:04}-{month:02}-{day:02}"

        if datetime.strptime(date, "%Y-%m-%d") < DATE_THRESHOLD:
            continue

        key = normalize_key(doi)

        if not key or key in seen:
            continue

        seen.add(key)

        results.append({
            "source": "Crossref",
            "title": title,
            "journal": journal,
            "date": date
        })

    return results

# ================= ARXIV =================

def fetch_arxiv():

    results = []

    query = urllib.parse.quote(build_query())

    url = f"http://export.arxiv.org/api/query?search_query=all:{query}&max_results=50"

    r = safe_get(url)

    if not r:
        return results

    feed = feedparser.parse(r.content)

    for entry in feed.entries:

        title = entry.title
        date = entry.published[:10]

        if datetime.strptime(date, "%Y-%m-%d") < DATE_THRESHOLD:
            continue

        key = normalize_key(url=entry.id)

        if key in seen:
            continue

        seen.add(key)

        results.append({
            "source": "arXiv",
            "title": title,
            "journal": "arXiv",
            "date": date
        })

    return results

# ================= HTML =================

def generate_html(data, utc, ist):

    data_sorted = sorted(data, key=lambda x: x["date"], reverse=True)

    total = len(data_sorted)

    last30 = sum(
        1 for d in data_sorted
        if datetime.strptime(d["date"], "%Y-%m-%d") >= datetime.utcnow() - timedelta(days=30)
    )

    sources = len(set(d["source"] for d in data_sorted))

    cards = ""

    for d in data_sorted:

        cards += f"""
<div class="card">
<b>{d['title']}</b><br>
Source: {d['source']}<br>
Journal: {d['journal']}<br>
<span class="small">{d['date']}</span>
</div>
"""

    html = f"""
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Crystal Research Intelligence</title>
<style>
body {{
background:#0f172a;
color:white;
font-family:Arial;
padding:20px;
}}

.card {{
background:#1e293b;
padding:15px;
margin:10px 0;
border-radius:8px;
}}

.search {{
padding:10px;
width:100%;
margin-bottom:15px;
}}
</style>
</head>
<body>

<h2>Crystal Research Intelligence</h2>

Total Papers: {total}<br>
Last 30 Days: {last30}<br>
Sources: {sources}<br><br>

<input class="search" id="search" placeholder="Search">

<div id="list">
{cards}
</div>

<script>

document.getElementById("search").onkeyup = function() {{

let v = this.value.toLowerCase()

document.querySelectorAll(".card").forEach(c=>{{
c.style.display = c.innerText.toLowerCase().includes(v) ? "" : "none"
}})

}}

</script>

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
    new += fetch_springer()
    new += fetch_crossref()
    new += fetch_arxiv()

    existing = {(d["title"], d["date"]) for d in report_data}

    for n in new:
        if (n["title"], n["date"]) not in existing:
            report_data.append(n)

    save_json(SEEN_FILE, list(seen))
    save_json(REPORT_DATA_FILE, report_data)

    generate_html(
        report_data,
        utc.strftime("%Y-%m-%d %H:%M"),
        ist.strftime("%Y-%m-%d %H:%M")
    )

if __name__ == "__main__":
    main()
