Crystal Research Intelligence
AI + Materials Science Research Monitoring System

Live Dashboard:
https://indra2215.github.io/research-monitor/

1️⃣ Project Overview

Crystal Research Intelligence is an automated AI-powered research monitoring system designed to:

Track AI + Materials Science publications

Store metadata over time

Detect new releases within a rolling 180-day window

Deliver alerts via:

Telegram

Discord Webhook

GitHub Pages dashboard

Maintain persistent research memory

Provide searchable public research dashboard

This is a Phase-3 automated SaaS-ready monitoring system.

2️⃣ Core Objective

The system answers one core question daily:

“Is there any new AI-integrated materials research published recently?”

It monitors:

Superconductors

Rare earth materials

Solid-state batteries

Li-ion batteries

AI-driven materials discovery

Only AI + Materials combined papers are targeted.

3️⃣ Architecture Overview
Data Flow
OpenAlex API
      ↓
Keyword AND Query
      ↓
Filter by publication date (Last 180 Days)
      ↓
Deduplication (seen.json)
      ↓
Persistent storage (report_data.json)
      ↓
Generate HTML Dashboard (index.html)
      ↓
Push to GitHub
      ↓
GitHub Pages Auto Deploy
      ↓
Telegram + Discord Alerts

4️⃣ APIs Used
🔹 Primary Research Source

OpenAlex API
Endpoint:

https://api.openalex.org/works

Query Strategy

We build a strict AND query:

(Material Keywords) AND (AI Keywords)


Filtered by:

from_publication_date: YYYY-MM-DD

API Calls Per Run

1 OpenAlex API request

Max 50 results per run

180-day rolling window

5️⃣ Environment Variables Used

Stored securely in GitHub Secrets:

Variable	Purpose
TELEGRAMTOKEN	Telegram Bot API Token
CHARTID	Telegram Chat ID
DISCORD_WEBHOOK	Discord Channel Webhook URL

No API keys are exposed in source code.

6️⃣ Duplicate Handling Strategy
🔹 seen.json

Stores normalized DOI values.

Before storing a new paper:

if DOI in seen:
    skip


Prevents:

Repeated alerts

Repeated dashboard entries

Reprocessing same data

🔹 report_data.json

Stores persistent metadata:

{
  source,
  title,
  journal,
  date
}


This allows:

Historical accumulation

180-day rolling analysis

Long-term research tracking

7️⃣ How Updates Work
Daily Workflow:

GitHub Action triggers at 10:00 AM IST

monitor.py runs

OpenAlex queried

New results filtered

Deduplicated

Stored in report_data.json

index.html regenerated

Changes committed

GitHub Pages auto deploys

Telegram + Discord notified

8️⃣ GitHub Workflow Structure
Workflow 1: Daily Monitor

File:

.github/workflows/daily.yml


Responsible for:

Running monitor.py

Updating JSON files

Committing index.html

Workflow 2: Static Deployment

File:

.github/workflows/static.yml


Responsible for:

Deploying index.html

Publishing GitHub Pages site

9️⃣ Dashboard Features (Phase 3)

Clean SaaS-ready UI:

Total Papers (180 Days)

Papers in Last 30 Days

Active Sources

Real-time search filter

Mobile responsive

Dark crystal-themed UI

No heavy graphs

Fast rendering

Public shareable link

🔟 Edge Cases Handled
Issue	Solution
Duplicate results	seen.json check
Old publications appearing	Strict publication_date filter
Broken JSON file	Try/except fallback
API timeout	safe_get wrapper
Telegram message limit	Split chunks
Discord message limit	Split chunks
GitHub rebase conflict	Only add changed files
Missing JSON files	Auto-create if absent
404 GitHub Pages	Enforced index.html output
11️⃣ Phases of Development
Phase 1 – Core Logic

OpenAlex integration

Keyword matching

180-day filtering

Telegram alerts

Phase 2 – Multi-source + Persistence

Deduplication logic

seen.json memory

report_data.json storage

Discord webhook

GitHub auto commits

Phase 3 – Public SaaS Dashboard

HTML auto generation

Mobile UI

Search filtering

GitHub Pages deployment

Professional UI polish

12️⃣ SaaS Potential

This system can be extended into:

Paid research monitoring service

University subscription dashboard

Domain-specific research tracker

AI + Materials trend analyzer

Custom alerting engine

Industry R&D monitoring platform

13️⃣ How To Reuse For Other Domains

To adapt for another research domain:

Modify config.json

Update material + AI keywords

Adjust DAYS_BACK if needed

Deploy same workflows

No structural changes required.

14️⃣ Efficiency & Design Decisions

Why OpenAlex?

Free

Structured metadata

Reliable filtering

DOI normalization

No scraping required

Why GitHub Pages?

Free hosting

Auto deploy

Version control

Public credibility

Why JSON persistence?

Lightweight

Transparent

No database required

Git-based storage

15️⃣ Limitations

Relies on metadata (not full-text)

Limited to 50 results per run

No authentication layer

No AI summary yet

16️⃣ Future Roadmap

Planned upgrades:

AI-generated summaries per paper

Trend detection

Research heatmap

PDF export

Admin dashboard

Multi-user login

API monetization

17️⃣ Full Technology Stack
Layer	Tech
Backend	Python
API	OpenAlex
Automation	GitHub Actions
Hosting	GitHub Pages
Alerts	Telegram Bot API
Webhook	Discord Webhook
Storage	JSON (Git-based persistence)
Frontend	HTML + CSS + JS
18️⃣ Why This Matters

AI + Materials research is accelerating.

Manual tracking is inefficient.

This system:

Automates discovery

Stores knowledge

Tracks history

Alerts instantly

Provides public dashboard

Can scale into SaaS

19️⃣ Repository

GitHub:

https://github.com/indra2215/research-monitor


Live Site:

https://indra2215.github.io/research-monitor/
