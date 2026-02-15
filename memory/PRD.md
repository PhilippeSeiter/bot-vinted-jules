# Vinted Price Tracker - MVP V1

## Original Problem Statement
Build a minimal MVP that tracks newly listed items on Vinted for saved searches and computes daily average + median prices.

## Architecture
- Backend: FastAPI + MongoDB (existing stack)
- No frontend UI in V1 (curl only)
- Manual polling (no cron)

## What's Been Implemented (2026-02-15)
- [x] Save search queries endpoint
- [x] Fetch items for query (with dedupe)
- [x] Compute daily stats (avg, median, count)
- [x] List queries/items/stats endpoints
- [x] Mock data fallback when Vinted scraping fails

## Collections
- vinted_queries: saved searches
- vinted_items: fetched items (deduped by query_id + item_id)
- vinted_stats_daily: daily aggregated stats

## Files Created/Modified
- /app/backend/vinted_fetcher.py (NEW)
- /app/backend/vinted_routes.py (NEW)
- /app/backend/server.py (modified - added router)

## Backlog (P0/P1/P2)
- P1: Real Vinted scraping (current uses mock when blocked)
- P1: Cron/scheduler for automated fetching
- P2: Dashboard UI
- P2: Price alerts/notifications
- P3: Multi-country support
- P3: Historical price charts
