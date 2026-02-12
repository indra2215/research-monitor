import requests
import feedparser
import json
import os
import urllib.parse
from datetime import datetime, timedelta
from collections import defaultdict, Counter

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

HTTP_TIMEOUT = 15
DISCORD_LIMIT = 1900

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

# ================= DOMAIN + SUBDOMAIN =================
def detect_domain_and_subdomain(title):
    t = title.lower()

    for domain_name, keywords in domains.items():
        if domain_name == "ai_methods":
            continue
        for kw in keywords:
            if kw.lower() in t:
                return domain_name, kw

    return "Other", "None"

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

        domain, subdomain = detect_domain_and_subdomain(title)

        seen.add(key)

        results.append({
            "source": "OpenAlex",
            "title": title,
            "journal": journal,
            "date": pub_date,
            "domain": domain,
            "subdomain": subdomain
        })

    return results

# ================= HTML =================
def generate_html(data, utc, ist):

    data_sorted = sorted(data, key=lambda x: x["date"], reverse=True)

    total = len(data_sorted)

    last_30 = sum(
        1 for d in data_sorted
        if datetime.strptime(d["date"], "%Y-%m-%d") >= datetime.utcnow() - timedelta(days=30)
    )

    by_source = Counter([d["source"] for d in data_sorted])
    by_domain = Counter([d["domain"] for d in data_sorted])
    by_subdomain = Counter([d["subdomain"] for d in data_sorted if d["subdomain"] != "None"])

    html = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>AI + Materials Intelligence</title>
<style>
body {{
    margin:0;
    font-family:Segoe UI;
    background:#0f172a;
    color:#e2e8f0;
}}
.header {{
    padding:30px;
    background:#020617;
}}
.container {{
    padding:40px;
}}
.kpi-grid {{
    display:flex;
    gap:20px;
    margin-bottom:30px;
}}
.kpi {{
    flex:1;
    background:#1e293b;
    padding:20px;
    border-radius:10px;
}}
.card {{
    background:#1e293b;
    padding:18px;
    margin-bottom:15px;
    border-radius:10px;
}}
.search {{
    padding:12px;
    width:100%;
    margin-bottom:20px;
    border-radius:8px;
    border:none;
}}
.small {{
    font-size:12px;
    color:#94a3b8;
}}
select {{
    padding:8px;
    margin-bottom:15px;
}}
</style>
</head>
<body>

<div class="header">
<h1>AI + Materials Intelligence Dashboard</h1>
<div class="small">UTC: {utc} | IST: {ist}</div>
</div>

<div class="container">

<div class="kpi-grid">
<div class="kpi"><h2>{total}</h2>Total Papers (180 Days)</div>
<div class="kpi"><h2>{last_30}</h2>Last 30 Days</div>
<div class="kpi"><h2>{len(by_source)}</h2>Active Sources</div>
</div>

<h3>Pattern Summary</h3>
<div class="card">
Top Domains:<br>
{"<br>".join([f"{k}: {v}" for k,v in by_domain.most_common(5)])}
<br><br>
Top Subdomains:<br>
{"<br>".join([f"{k}: {v}" for k,v in by_subdomain.most_common(5)])}
</div>

<input type="text" class="search" id="searchBox" placeholder="Search by title, journal, domain...">

<select id="domainFilter">
<option value="">All Domains</option>
{"".join([f"<option value='{d}'>{d}</option>" for d in by_domain.keys()])}
</select>

<div id="papers">
"""

    for item in data_sorted:
        html += f"""
<div class="card paper" data-domain="{item['domain']}">
<b>{item['title']}</b><br>
Source: {item['source']}<br>
Domain: {item['domain']}<br>
Sub-domain: {item['subdomain']}<br>
Journal: {item['journal']}<br>
<span class="small">Published: {item['date']}</span>
</div>
"""

    html += """
</div>

<script>
const searchBox = document.getElementById("searchBox");
const domainFilter = document.getElementById("domainFilter");

function filterPapers() {
    const text = searchBox.value.toLowerCase();
    const domain = domainFilter.value;
    const papers = document.querySelectorAll(".paper");

    papers.forEach(p => {
        const content = p.innerText.toLowerCase();
        const matchesText = content.includes(text);
        const matchesDomain = domain === "" || p.dataset.domain === domain;

        p.style.display = (matchesText && matchesDomain) ? "" : "none";
    });
}

searchBox.addEventListener("keyup", filterPapers);
domainFilter.addEventListener("change", filterPapers);
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
AI + Materials Intelligence

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
