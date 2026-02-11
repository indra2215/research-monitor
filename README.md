Research Monitor Automation System
Overview

This project implements a fully automated, zero-cost research monitoring system using GitHub Actions and multiple academic APIs.

It runs daily and sends filtered research alerts to Telegram while maintaining persistent memory to avoid duplicate notifications.

Architecture
Execution Layer

GitHub Actions (scheduled cron job)

Runs daily at 03:00 UTC

No local machine required

Data Sources
Source	Type	API Key Required
arXiv	Open API (XML/RSS)	No
OpenAlex	REST API	No
Crossref	REST API	No
Semantic Scholar	Graph API	Yes
Keyword Engine

Keywords stored in config.json

Batched in groups of 20

URL-encoded before query

Scored based on:

Title match (+5)

Abstract match (+3)

Citation count bonus (+2)

Relevance Classification
Score	Label
≥ 10	HIGH
≥ 5	MEDIUM

Only HIGH and MEDIUM results are sent.

Date Filtering

Only considers papers published within last 3 days

Prevents historical flooding

Deduplication & Memory System

Persistent memory stored in:

seen.json

How it works:

All sent links are stored in seen.json

On next run, duplicates are skipped

GitHub workflow auto-commits updated memory

Memory persists across runs

This ensures:

No repeated alerts

Long-term monitoring stability

Telegram Integration

Uses Telegram Bot API.

Required Secrets (Repository Level):
TELEGRAMTOKEN
CHARTID
S2_API_KEY (optional)

Message Handling:

No Markdown (prevents parsing errors)

Messages auto-split at 3900 characters

Safe against Telegram 4096 limit

GitHub Workflow

Installs dependencies

Runs monitor.py

Commits updated seen.json

Uses git pull --rebase to avoid push conflicts

Production Safety Features

URL encoding for all queries

Retry logic for HTTP requests

Timeout handling

JSON validation

Safe error handling

Chunked Telegram messaging

Stateless runner support

Zero-Cost Infrastructure

This system runs entirely on:

GitHub Free tier

Open academic APIs

Telegram free bot API

No paid services required.

Key Engineering Lessons

Never hardcode API tokens

Always URL-encode query strings

Handle API response errors

GitHub runners are ephemeral

State persistence requires explicit commit logic

Markdown in Telegram is fragile

Logging is mandatory in production

Final State

The system is:

Automated

Persistent

Fault tolerant

Scalable

Zero-cost

Cloud-native
