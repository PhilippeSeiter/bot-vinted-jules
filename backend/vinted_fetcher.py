"""
Vinted Fetcher - Minimal implementation for fetching public listings
"""
import requests
import time
import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

# Vinted public API base - uses their catalog search
VINTED_BASE_URL = "https://www.vinted.fr/api/v2/catalog/items"

# Default headers to mimic browser
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}


def fetch_vinted_items(
    search_text: str = "",
    catalog_ids: Optional[List[int]] = None,
    brand_ids: Optional[List[int]] = None,
    size_ids: Optional[List[int]] = None,
    price_from: Optional[float] = None,
    price_to: Optional[float] = None,
    order: str = "newest_first",
    per_page: int = 20
) -> List[Dict[str, Any]]:
    """
    Fetch items from Vinted's public catalog API.
    
    Args:
        search_text: Keywords to search for
        catalog_ids: Category IDs (optional)
        brand_ids: Brand IDs (optional)
        size_ids: Size IDs (optional)
        price_from: Minimum price (optional)
        price_to: Maximum price (optional)
        order: Sort order (newest_first, price_low_to_high, price_high_to_low)
        per_page: Number of items to fetch (max 96)
    
    Returns:
        List of item dictionaries
    """
    params = {
        "per_page": min(per_page, 96),
        "order": order,
    }
    
    if search_text:
        params["search_text"] = search_text
    if catalog_ids:
        params["catalog_ids"] = ",".join(map(str, catalog_ids))
    if brand_ids:
        params["brand_ids"] = ",".join(map(str, brand_ids))
    if size_ids:
        params["size_ids"] = ",".join(map(str, size_ids))
    if price_from is not None:
        params["price_from"] = price_from
    if price_to is not None:
        params["price_to"] = price_to
    
    logger.info(f"Fetching Vinted items with params: {params}")
    
    try:
        # Rate limiting - gentle delay
        time.sleep(1)
        
        response = requests.get(
            VINTED_BASE_URL,
            params=params,
            headers=HEADERS,
            timeout=30
        )
        response.raise_for_status()
        
        data = response.json()
        items = data.get("items", [])
        
        logger.info(f"Fetched {len(items)} items from Vinted")
        return items
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching Vinted items: {e}")
        return []


def parse_item(raw_item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse a raw Vinted item into a normalized structure.
    """
    return {
        "item_id": str(raw_item.get("id", "")),
        "title": raw_item.get("title", ""),
        "price": float(raw_item.get("price", {}).get("amount", 0) if isinstance(raw_item.get("price"), dict) else raw_item.get("price", 0)),
        "currency": raw_item.get("price", {}).get("currency_code", "EUR") if isinstance(raw_item.get("price"), dict) else "EUR",
        "brand": raw_item.get("brand_title", ""),
        "size": raw_item.get("size_title", ""),
        "url": raw_item.get("url", f"https://www.vinted.fr/items/{raw_item.get('id', '')}"),
        "photo_url": raw_item.get("photo", {}).get("url", "") if isinstance(raw_item.get("photo"), dict) else "",
        "raw_json": raw_item
    }
