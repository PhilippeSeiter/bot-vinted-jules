"""
Vinted API Routes - Endpoints for managing queries, fetching items, and computing stats
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
import uuid
import statistics
import logging

from vinted_fetcher import fetch_vinted_items, parse_item

logger = logging.getLogger(__name__)

# Router with /api/vinted prefix
vinted_router = APIRouter(prefix="/api/vinted", tags=["vinted"])

# Will be set by server.py
db = None

def set_db(database):
    global db
    db = database


# ===== Pydantic Models =====

class QueryCreate(BaseModel):
    name: str = Field(..., description="Human-readable name for the search")
    search_text: str = Field(default="", description="Keywords to search")
    catalog_ids: Optional[List[int]] = Field(default=None, description="Category IDs")
    brand_ids: Optional[List[int]] = Field(default=None, description="Brand IDs")
    size_ids: Optional[List[int]] = Field(default=None, description="Size IDs")
    price_from: Optional[float] = Field(default=None, description="Min price filter")
    price_to: Optional[float] = Field(default=None, description="Max price filter")


class QueryResponse(BaseModel):
    id: str
    name: str
    query_json: Dict[str, Any]
    created_at: str


class FetchResult(BaseModel):
    query_id: str
    items_fetched: int
    items_new: int
    items_existing: int
    source: str  # "live" or "mock"
    is_mock: bool
    blocked_reason: Optional[str] = None


class StatsResponse(BaseModel):
    query_id: str
    day: str
    avg_price: Optional[float]
    median_price: Optional[float]
    item_count: int


# ===== Endpoints =====

@vinted_router.post("/queries", response_model=QueryResponse)
async def create_query(query: QueryCreate):
    """Save a new search query."""
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    query_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    
    query_json = {
        "search_text": query.search_text,
        "catalog_ids": query.catalog_ids,
        "brand_ids": query.brand_ids,
        "size_ids": query.size_ids,
        "price_from": query.price_from,
        "price_to": query.price_to,
    }
    
    doc = {
        "id": query_id,
        "name": query.name,
        "query_json": query_json,
        "created_at": now
    }
    
    await db.vinted_queries.insert_one(doc)
    logger.info(f"Created query: {query_id} - {query.name}")
    
    return QueryResponse(
        id=query_id,
        name=query.name,
        query_json=query_json,
        created_at=now
    )


@vinted_router.get("/queries", response_model=List[QueryResponse])
async def list_queries():
    """List all saved queries."""
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    queries = await db.vinted_queries.find({}, {"_id": 0}).to_list(100)
    return [QueryResponse(**q) for q in queries]


@vinted_router.post("/queries/{query_id}/fetch", response_model=FetchResult)
async def fetch_for_query(query_id: str):
    """
    Trigger a fetch run for a specific query.
    Fetches latest 20 items and stores them with dedupe.
    """
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    # Get the query
    query_doc = await db.vinted_queries.find_one({"id": query_id}, {"_id": 0})
    if not query_doc:
        raise HTTPException(status_code=404, detail=f"Query {query_id} not found")
    
    query_json = query_doc["query_json"]
    
    # Fetch items from Vinted
    fetch_result = fetch_vinted_items(
        search_text=query_json.get("search_text", ""),
        catalog_ids=query_json.get("catalog_ids"),
        brand_ids=query_json.get("brand_ids"),
        size_ids=query_json.get("size_ids"),
        price_from=query_json.get("price_from"),
        price_to=query_json.get("price_to"),
        per_page=20
    )
    
    raw_items = fetch_result["items"]
    source = fetch_result["source"]
    is_mock = fetch_result["is_mock"]
    blocked_reason = fetch_result["blocked_reason"]
    
    items_new = 0
    items_existing = 0
    now = datetime.now(timezone.utc).isoformat()
    
    for raw_item in raw_items:
        parsed = parse_item(raw_item)
        
        # Check if item already exists (dedupe by query_id + item_id)
        existing = await db.vinted_items.find_one({
            "query_id": query_id,
            "item_id": parsed["item_id"]
        })
        
        if existing:
            items_existing += 1
        else:
            doc = {
                "id": str(uuid.uuid4()),
                "query_id": query_id,
                "item_id": parsed["item_id"],
                "title": parsed["title"],
                "price": parsed["price"],
                "currency": parsed["currency"],
                "brand": parsed["brand"],
                "size": parsed["size"],
                "url": parsed["url"],
                "created_at": now,
                "raw_json": parsed["raw_json"]
            }
            await db.vinted_items.insert_one(doc)
            items_new += 1
    
    logger.info(f"[SOURCE={source}] Fetch complete for query {query_id}: {items_new} new, {items_existing} existing, is_mock={is_mock}")
    
    return FetchResult(
        query_id=query_id,
        items_fetched=len(raw_items),
        items_new=items_new,
        items_existing=items_existing,
        source=source,
        is_mock=is_mock,
        blocked_reason=blocked_reason
    )


@vinted_router.post("/queries/{query_id}/stats", response_model=StatsResponse)
async def compute_stats(query_id: str):
    """
    Compute and store daily stats (avg, median, count) for a query.
    """
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    # Verify query exists
    query_doc = await db.vinted_queries.find_one({"id": query_id}, {"_id": 0})
    if not query_doc:
        raise HTTPException(status_code=404, detail=f"Query {query_id} not found")
    
    # Get all items for this query
    items = await db.vinted_items.find(
        {"query_id": query_id},
        {"_id": 0, "price": 1}
    ).to_list(10000)
    
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now = datetime.now(timezone.utc).isoformat()
    
    prices = [item["price"] for item in items if item.get("price", 0) > 0]
    
    avg_price = None
    median_price = None
    item_count = len(prices)
    
    if prices:
        avg_price = round(sum(prices) / len(prices), 2)
        median_price = round(statistics.median(prices), 2)
    
    # Upsert daily stats row
    stats_doc = {
        "id": str(uuid.uuid4()),
        "query_id": query_id,
        "day": today,
        "avg_price": avg_price,
        "median_price": median_price,
        "item_count": item_count,
        "created_at": now
    }
    
    # Update or insert for today
    await db.vinted_stats_daily.update_one(
        {"query_id": query_id, "day": today},
        {"$set": stats_doc},
        upsert=True
    )
    
    logger.info(f"Stats computed for query {query_id}: avg={avg_price}, median={median_price}, count={item_count}")
    
    return StatsResponse(
        query_id=query_id,
        day=today,
        avg_price=avg_price,
        median_price=median_price,
        item_count=item_count
    )


@vinted_router.get("/queries/{query_id}/stats", response_model=List[StatsResponse])
async def get_stats_history(query_id: str):
    """Get historical stats for a query."""
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    stats = await db.vinted_stats_daily.find(
        {"query_id": query_id},
        {"_id": 0}
    ).sort("day", -1).to_list(100)
    
    return [StatsResponse(**s) for s in stats]


@vinted_router.get("/queries/{query_id}/items")
async def get_items(query_id: str, limit: int = 50):
    """Get items for a query."""
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    items = await db.vinted_items.find(
        {"query_id": query_id},
        {"_id": 0, "raw_json": 0}
    ).sort("created_at", -1).to_list(limit)
    
    return {"query_id": query_id, "items": items, "count": len(items)}
