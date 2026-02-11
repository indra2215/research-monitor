import requests
import feedparser
import json
import os
from datetime import datetime, timedelta

# ==========================================
# ENV VARIABLES (MATCH YOUR GITHUB SECRETS)
# ==========================================
TELEGRAM_TOKEN = os.getenv("TELEGRAMTOKEN")
CHAT_ID = os.getenv("CHARTID")
S2_API_KEY = os.getenv("S2_API_KEY")

# ==========================================
# LOAD KEYWORDS
# ==========================================
with open("config.json", "r") as f:
    config = json.load(f)

keywords = []
for domain in config["domains"].values():
    keywords.extend(domain)

# ==========================================
# MEMORY HANDLING
# ==========================================
SEEN_FILE = "seen.json"

if os.path.exists(SEEN_FILE):
    with open(SEEN_FILE, "r") as f:
        seen_links = set(json.load(f))
else:
    seen_links = set()

def save_seen():
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen_links), f)

# ==========================================
# SETTINGS
# ==========================================
DAYS_BACK = 3   # Only consider last 3 days
DATE_THRESHOLD = datetime.utcnow() - timedelta(days=DAYS_BACK)

# ==========================================
# BATCHING
# ==========================================
def chunk_keywords(lst, size=20):
    for i in range(0, len(lst), size):
        yield lst[i:i + size]

# ==========================================
# SCORING
# ==========================================
def score_text(title, abstract="", citation_count=0):
    score = 0
    text = (title + " " + abstract).lower()

    for kw in keywords:
        if kw.lower() in title.lower():
            score += 5
        if kw.lower() in text:
            score += 3

    if citation_count and citation_count > 10:
        score += 2

    return score

def classify(score):
    if score >= 10:
        return "HIGH"
    elif score >= 5:
        return "MEDIUM"
    return None

# ==========================================
# TELEGRAM
# ==========================================
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    })

# ==========================================
# PROCESS & FILTER
# ==========================================
def process_item(title, link, abstract="", citation=0, published_date=None):
    if not link or link in seen_links:
        return None

    if published_date and published_date < DATE_THRESHOLD:
        return None

    score = score_text(title, abstract, citation)
    level = classify(score)

    if level:
        seen_links.add(link)
        return f"*[{level}]* {title}\n{link}\n"

    return None

# ==========================================
# ARXIV
# ==========================================
def check_arxiv():
    results = []

    for batch in chunk_keywords(keywords, 20):
        query = " OR ".join([f'all:"{kw}"' for kw in batch])
        url = f"http://export.arxiv.org/api/query?search_query={query}&sortBy=lastUpdatedDate&max_results=10"

        feed = feedparser.parse(url)

        for entry in feed.entries:
            published = datetime(*entry.published_parsed[:6])
            item = process_item(
                entry.title,
                entry.link,
                entry.summary,
                0,
                published
            )
            if item:
                results.append(item)

    return results

# ==========================================
# OPENALEX
# ==========================================
def check_openalex():
    results = []

    for batch in chunk_keywords(keywords, 20):
        query = " OR ".join(batch)
        url = f"https://api.openalex.org/works?search={query}&per-page=10"

        response = requests.get(url)
        data = response.json()

        for work in data.get("results", []):
            title = work.get("title", "")
            link = work.get("id", "")
            citation = work.get("cited_by_count", 0)

            pub_date_str = work.get("publication_date")
            published = None
            if pub_date_str:
                try:
                    published = datetime.strptime(pub_date_str, "%Y-%m-%d")
                except:
                    pass

            item = process_item(title, link, "", citation, published)
            if item:
                results.append(item)

    return results

# ==========================================
# CROSSREF
# ==========================================
def check_crossref():
    results = []

    for batch in chunk_keywords(keywords, 20):
        query = " OR ".join(batch)
        url = f"https://api.crossref.org/works?query={query}&rows=10"

        response = requests.get(url)
        data = response.json()

        for item in data.get("message", {}).get("items", []):
            title = item.get("title", [""])[0]
            link = item.get("URL", "")
            citation = item.get("is-referenced-by-count", 0)

            pub_parts = item.get("published-print", {}).get("date-parts")
            published = None
            if pub_parts:
                y, m, d = pub_parts[0]
                published = datetime(y, m, d)

            result = process_item(title, link, "", citation, published)
            if result:
                results.append(result)

    return results

# ==========================================
# SEMANTIC SCHOLAR (OPTIONAL)
# ==========================================
def check_semantic():
    if not S2_API_KEY:
        return []

    results = []
    headers = {"x-api-key": S2_API_KEY}

    for batch in chunk_keywords(keywords, 20):
        query = " OR ".join(batch)

        url = "https://api.semanticscholar.org/graph/v1/paper/search"
        params = {
            "query": query,
            "limit": 10,
            "fields": "title,abstract,url,citationCount,year"
        }

        response = requests.get(url, headers=headers, params=params)
        data = response.json()

        for paper in data.get("data", []):
            title = paper.get("title", "")
            link = paper.get("url", "")
            abstract = paper.get("abstract", "")
            citation = paper.get("citationCount", 0)

            published = None
            if paper.get("year"):
                published = datetime(paper["year"], 1, 1)

            item = process_item(title, link, abstract, citation, published)
            if item:
                results.append(item)

    return results

# ==========================================
# MAIN
# ==========================================
def main():
    message = "*Daily Research Monitor*\n\n"

    results = (
        check_arxiv() +
        check_openalex() +
        check_crossref() +
        check_semantic()
    )

    if not results:
        message += "No significant updates in the last 3 days."
    else:
        message += "\n".join(results[:20])

    send_telegram(message)
    save_seen()

if __name__ == "__main__":
    main()
