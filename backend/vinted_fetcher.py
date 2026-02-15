"""
Vinted Fetcher - Using web scraping approach since API requires auth
Scrapes public search results page
"""
import requests
import time
import logging
import re
import json
from typing import Dict, List, Any, Optional
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Default headers to mimic browser
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

# Country domain mapping
VINTED_DOMAINS = {
    "fr": "www.vinted.fr",
    "de": "www.vinted.de",
    "es": "www.vinted.es",
    "uk": "www.vinted.co.uk",
    "it": "www.vinted.it",
    "nl": "www.vinted.nl",
    "be": "www.vinted.be",
    "pl": "www.vinted.pl",
}


def fetch_vinted_items(
    search_text: str = "",
    catalog_ids: Optional[List[int]] = None,
    brand_ids: Optional[List[int]] = None,
    size_ids: Optional[List[int]] = None,
    price_from: Optional[float] = None,
    price_to: Optional[float] = None,
    order: str = "newest_first",
    per_page: int = 20,
    country: str = "fr"
) -> Dict[str, Any]:
    """
    Fetch items from Vinted by scraping the search page.
    Extracts data from the __NEXT_DATA__ or initial state embedded in the page.
    
    Args:
        search_text: Keywords to search for
        catalog_ids: Category IDs (optional)
        brand_ids: Brand IDs (optional)
        size_ids: Size IDs (optional)
        price_from: Minimum price (optional)
        price_to: Maximum price (optional)
        order: Sort order
        per_page: Number of items to fetch
        country: Country code
    
    Returns:
        List of item dictionaries
    """
    domain = VINTED_DOMAINS.get(country, "www.vinted.fr")
    
    # Build search URL with query params
    base_url = f"https://{domain}/catalog"
    params = {}
    
    if search_text:
        params["search_text"] = search_text
    if catalog_ids:
        params["catalog[]"] = catalog_ids
    if brand_ids:
        params["brand_id[]"] = brand_ids
    if price_from is not None:
        params["price_from"] = price_from
    if price_to is not None:
        params["price_to"] = price_to
    if order:
        params["order"] = order
    
    logger.info(f"Fetching Vinted items from {domain} with params: {params}")
    
    # Rate limiting - gentle delay
    time.sleep(1)
    
    session = requests.Session()
    session.headers.update(HEADERS)
    
    try:
        response = session.get(base_url, params=params, timeout=30)
        logger.info(f"Vinted response status: {response.status_code}")
        
        if response.status_code != 200:
            logger.error(f"Vinted returned status {response.status_code}")
            return []
        
        html = response.text
        items = []
        
        # Method 1: Try to find __NEXT_DATA__ (Vinted uses Next.js)
        next_data_match = re.search(r'<script id="__NEXT_DATA__" type="application/json">({.*?})</script>', html, re.DOTALL)
        if next_data_match:
            try:
                next_data = json.loads(next_data_match.group(1))
                # Navigate through Next.js data structure
                page_props = next_data.get("props", {}).get("pageProps", {})
                catalog = page_props.get("catalog", {})
                items = catalog.get("items", [])
                if items:
                    logger.info(f"Found {len(items)} items via __NEXT_DATA__")
                    return items[:per_page]
            except json.JSONDecodeError as e:
                logger.debug(f"Failed to parse __NEXT_DATA__: {e}")
        
        # Method 2: Try to find preloaded state
        preload_patterns = [
            r'window\.__PRELOADED_STATE__\s*=\s*({.*?});',
            r'window\.__INITIAL_STATE__\s*=\s*({.*?});',
            r'"items":\s*(\[{.*?}\])',
        ]
        
        for pattern in preload_patterns:
            match = re.search(pattern, html, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                    if isinstance(data, list):
                        items = data
                    elif isinstance(data, dict):
                        items = data.get("catalog", {}).get("items", []) or data.get("items", [])
                    
                    if items:
                        logger.info(f"[SOURCE=live] Found {len(items)} items via pattern")
                        return {"items": items[:per_page], "source": "live", "is_mock": False, "blocked_reason": None}
                except json.JSONDecodeError:
                    continue
        
        # Method 3: Parse HTML directly with BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        
        # Look for item cards
        item_elements = soup.find_all('div', {'data-testid': re.compile(r'grid-item|catalog-item')})
        if not item_elements:
            # Try other common selectors
            item_elements = soup.find_all('div', class_=re.compile(r'ItemBox|feed-grid__item'))
        
        if not item_elements:
            # Look for any links to item pages
            item_links = soup.find_all('a', href=re.compile(r'/items/\d+'))
            for link in item_links[:per_page]:
                item_id_match = re.search(r'/items/(\d+)', link.get('href', ''))
                if item_id_match:
                    item_id = item_id_match.group(1)
                    
                    # Try to find associated data
                    parent = link.find_parent('div')
                    title = link.get('title', '') or link.get_text(strip=True)[:100]
                    
                    # Look for price in nearby elements
                    price_text = ""
                    price_el = parent.find(string=re.compile(r'[\d,\.]+\s*[€$£]')) if parent else None
                    if price_el:
                        price_text = price_el.strip()
                    
                    items.append({
                        "id": item_id,
                        "title": title,
                        "price": price_text or "0",
                        "url": f"https://{domain}/items/{item_id}"
                    })
        
        if items:
            logger.info(f"[SOURCE=live] Scraped {len(items)} items from HTML")
            return {"items": items[:per_page], "source": "live", "is_mock": False, "blocked_reason": None}
        
        blocked_reason = "Could not extract items - Vinted structure changed or blocked"
        logger.warning(f"[SOURCE=mock] {blocked_reason}")
        return {"items": generate_mock_items(search_text, per_page), "source": "mock", "is_mock": True, "blocked_reason": blocked_reason}
        
    except Exception as e:
        blocked_reason = f"Request failed: {str(e)}"
        logger.error(f"[SOURCE=mock] {blocked_reason}")
        return {"items": generate_mock_items(search_text, per_page), "source": "mock", "is_mock": True, "blocked_reason": blocked_reason}


def generate_mock_items(search_text: str, count: int = 20) -> List[Dict[str, Any]]:
    """
    Generate mock items for testing when real scraping fails.
    This allows the system to be validated end-to-end.
    """
    import random
    import hashlib
    
    base_prices = [15, 25, 35, 45, 55, 65, 75, 85, 95, 105]
    brands = ["Nike", "Adidas", "Puma", "Reebok", "New Balance", "Asics", "Vans", "Converse"]
    sizes = ["S", "M", "L", "XL", "36", "38", "40", "42", "44"]
    
    items = []
    for i in range(count):
        # Generate deterministic ID based on search + index
        item_id = hashlib.md5(f"{search_text}_{i}_{time.time()//3600}".encode()).hexdigest()[:8]
        
        items.append({
            "id": f"mock_{item_id}",
            "title": f"{search_text or 'Item'} - Sample #{i+1}",
            "price": {"amount": random.choice(base_prices) + random.randint(-5, 5), "currency_code": "EUR"},
            "brand_title": random.choice(brands),
            "size_title": random.choice(sizes),
            "url": f"https://www.vinted.fr/items/mock_{item_id}",
            "photo": {"url": ""},
            "_mock": True
        })
    
    logger.info(f"Generated {len(items)} mock items for testing")
    return items


def parse_item(raw_item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse a raw Vinted item into a normalized structure.
    Handles both API, scraped, and mock data formats.
    """
    # Handle different price formats
    price_data = raw_item.get("price", 0)
    if isinstance(price_data, dict):
        price = float(price_data.get("amount", 0))
        currency = price_data.get("currency_code", "EUR")
    elif isinstance(price_data, str):
        # Parse price string like "15,00 €" or "€15.00"
        price_match = re.search(r'([\d,\.]+)', price_data.replace(',', '.'))
        price = float(price_match.group(1)) if price_match else 0
        currency = "EUR"
    else:
        price = float(price_data) if price_data else 0
        currency = "EUR"
    
    # Get item ID
    item_id = raw_item.get("id") or raw_item.get("item_id") or ""
    
    # Build URL
    url = raw_item.get("url", "")
    if not url and item_id:
        url = f"https://www.vinted.fr/items/{item_id}"
    
    # Photo URL
    photo = raw_item.get("photo", {})
    photo_url = photo.get("url", "") if isinstance(photo, dict) else str(photo)
    
    return {
        "item_id": str(item_id),
        "title": raw_item.get("title", ""),
        "price": price,
        "currency": currency,
        "brand": raw_item.get("brand_title", "") or raw_item.get("brand", ""),
        "size": raw_item.get("size_title", "") or raw_item.get("size", ""),
        "url": url,
        "photo_url": photo_url,
        "is_mock": raw_item.get("_mock", False),
        "raw_json": raw_item
    }
