import requests
import json
import os
import urllib.parse
from datetime import datetime, timedelta

# ================= ENV =================
TELEGRAM_TOKEN = os.getenv("TELEGRAMTOKEN")
CHAT_ID = os.getenv("CHARTID")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")

CONFIG_PATH = "config.json"
SEEN_FILE = "seen.json"
REPORT_DATA_FILE = "report_data.json"
HTML_OUTPUT = "index.html"

DAYS_BACK = 180
DATE_THRESHOLD = datetime.utcnow() - timedelta(days=DAYS_BACK)
FROM_DATE = DATE_THRESHOLD.strftime("%Y-%m-%d")

DISCORD_LIMIT = 1900
HTTP_TIMEOUT = 15

# ================= LOAD CONFIG =================
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    config = json.load(f)

domains = config["domains"]

# ================= MEMORY =================
def load_json_file(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return default
    return default

def save_json_file(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

seen = set(load_json_file(SEEN_FILE, []))
report_data = load_json_file(REPORT_DATA_FILE, [])

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
def build_query():
    material_keywords = []
    for k, v in domains.items():
        if k != "ai_methods":
            material_keywords.extend(v)

    ai_keywords = domains.get("ai_methods", [])

    m_part = "(" + " OR ".join(material_keywords[:10]) + ")"
    a_part = "(" + " OR ".join(ai_keywords[:6]) + ")"
    return f"{m_part} AND {a_part}"

# ================= OPENALEX =================
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

        if not title or not pub_date:
            continue

        try:
            pub_dt = datetime.strptime(pub_date, "%Y-%m-%d")
            if pub_dt < DATE_THRESHOLD:
                continue
        except:
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

# ================= HTML DASHBOARD =================
def generate_html(data, utc, ist):

    data_sorted = sorted(data, key=lambda x: x["date"], reverse=True)

    total = len(data_sorted)

    last_30 = sum(
        1 for d in data_sorted
        if datetime.strptime(d["date"], "%Y-%m-%d") >= datetime.utcnow() - timedelta(days=30)
    )

    active_sources = len(set(d["source"] for d in data_sorted))

    html = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Crystal Research Intelligence</title>

<style>
body {{
    margin:0;
    font-family:Segoe UI;
    background:#0f172a;
    color:#e2e8f0;
}}

.header {{
    padding:25px;
    background:linear-gradient(90deg,#020617,#0f172a);
    text-align:center;
}}

.logo {{
    font-size:22px;
    font-weight:bold;
    letter-spacing:1px;
    color:#38bdf8;
}}

.subtitle {{
    font-size:13px;
    color:#94a3b8;
    margin-top:6px;
}}

.container {{
    padding:20px;
    max-width:900px;
    margin:auto;
}}

.kpi-grid {{
    display:flex;
    flex-wrap:wrap;
    gap:15px;
    margin-bottom:25px;
}}

.kpi {{
    flex:1;
    min-width:150px;
    background:#1e293b;
    padding:18px;
    border-radius:12px;
    text-align:center;
}}

.kpi h2 {{
    margin:0;
    color:#38bdf8;
}}

.search {{
    width:100%;
    padding:12px;
    border-radius:10px;
    border:none;
    margin-bottom:20px;
    font-size:14px;
}}

.card {{
    background:#1e293b;
    padding:18px;
    margin-bottom:14px;
    border-radius:12px;
    transition:0.2s;
}}

.card:hover {{
    background:#273549;
}}

.small {{
    font-size:12px;
    color:#94a3b8;
}}

@media(max-width:600px){{
    .kpi-grid {{
        flex-direction:column;
    }}
}}
</style>
</head>

<body>

<div class="header">
<div class="logo">🔷 Crystal Research Intelligence</div>
<div class="subtitle">
UTC: {utc} | IST: {ist}
</div>
</div>

<div class="container">

<div class="kpi-grid">
<div class="kpi">
<h2>{total}</h2>
<div>Total Papers (180 Days)</div>
</div>

<div class="kpi">
<h2>{last_30}</h2>
<div>Last 30 Days</div>
</div>

<div class="kpi">
<h2>{active_sources}</h2>
<div>Active Sources</div>
</div>
</div>

<input type="text" id="searchBox" class="search" placeholder="Search papers by title or journal...">

<div id="paperList">
"""

    for item in data_sorted:
        html += f"""
<div class="card">
<b>{item['title']}</b><br>
Source: {item['source']}<br>
Journal: {item['journal']}<br>
<span class="small">Published: {item['date']}</span>
</div>
"""

    html += """
</div>

<script>
const searchBox = document.getElementById("searchBox");

searchBox.addEventListener("keyup", function() {
    const filter = searchBox.value.toLowerCase();
    const cards = document.getElementsByClassName("card");

    for (let i = 0; i < cards.length; i++) {
        const text = cards[i].innerText.toLowerCase();
        cards[i].style.display = text.includes(filter) ? "" : "none";
    }
});
</script>

</body>
</html>
"""

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

    existing_keys = {(d["title"], d["date"]) for d in report_data}

    for item in new_results:
        if (item["title"], item["date"]) not in existing_keys:
            report_data.append(item)

    save_json_file(SEEN_FILE, list(seen))
    save_json_file(REPORT_DATA_FILE, report_data)

    msg = f"""
Crystal Research Intelligence

UTC: {utc.strftime('%Y-%m-%d %H:%M:%S')}
IST: {ist.strftime('%Y-%m-%d %H:%M:%S')}

New Findings: {len(new_results)}
Total Stored: {len(report_data)}
"""

    send_telegram(msg)
    send_discord(msg)

    generate_html(
        report_data,
        utc.strftime('%Y-%m-%d %H:%M:%S'),
        ist.strftime('%Y-%m-%d %H:%M:%S')
    )

if __name__ == "__main__":
    main()
