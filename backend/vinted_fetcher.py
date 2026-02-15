"""
Vinted Fetcher - Minimal implementation for fetching public listings
Uses session-based approach to handle Vinted's cookie requirements
"""
import requests
import time
import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

# Vinted domains by country
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

# Default headers to mimic browser
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}


def get_vinted_session(domain: str = "www.vinted.fr") -> requests.Session:
    """
    Create a session and get necessary cookies from Vinted.
    """
    session = requests.Session()
    session.headers.update(HEADERS)
    
    try:
        # Visit the main page to get cookies
        response = session.get(f"https://{domain}", timeout=30)
        response.raise_for_status()
        logger.info(f"Got session cookies from {domain}")
    except Exception as e:
        logger.warning(f"Could not get session from {domain}: {e}")
    
    return session


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
        country: Country code (fr, de, es, uk, etc.)
    
    Returns:
        List of item dictionaries
    """
    domain = VINTED_DOMAINS.get(country, "www.vinted.fr")
    
    params = {
        "per_page": min(per_page, 96),
        "order": order,
        "page": 1,
        "time": int(time.time()),
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
    
    # Rate limiting - gentle delay
    time.sleep(1)
    
    # Get session with cookies
    session = get_vinted_session(domain)
    
    api_url = f"https://{domain}/api/v2/catalog/items"
    
    try:
        response = session.get(api_url, params=params, timeout=30)
        
        logger.info(f"Vinted API response status: {response.status_code}")
        
        if response.status_code == 401 or response.status_code == 403:
            logger.warning("Vinted API requires authentication - trying alternative approach")
            return fetch_vinted_items_scrape(search_text, domain)
        
        response.raise_for_status()
        data = response.json()
        items = data.get("items", [])
        
        logger.info(f"Fetched {len(items)} items from Vinted")
        return items
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching Vinted items: {e}")
        # Try scraping approach as fallback
        return fetch_vinted_items_scrape(search_text, domain)


def fetch_vinted_items_scrape(search_text: str, domain: str = "www.vinted.fr") -> List[Dict[str, Any]]:
    """
    Fallback: scrape items from search page HTML when API fails.
    Extracts embedded JSON data from the page.
    """
    import re
    import json
    
    logger.info(f"Trying scrape approach for: {search_text}")
    
    session = requests.Session()
    session.headers.update(HEADERS)
    
    try:
        # Build search URL
        search_url = f"https://{domain}/catalog"
        params = {"search_text": search_text} if search_text else {}
        
        time.sleep(1)  # Rate limit
        
        response = session.get(search_url, params=params, timeout=30)
        response.raise_for_status()
        
        html = response.text
        
        # Try to find embedded catalog data in script tags
        # Vinted embeds initial state as JSON in the page
        patterns = [
            r'window\.__PRELOADED_STATE__\s*=\s*({.*?});',
            r'"catalog":\s*(\{.*?"items":\s*\[.*?\].*?\})',
            r'data-items="([^"]*)"',
        ]
        
        for pattern in patterns:
            matches = re.search(pattern, html, re.DOTALL)
            if matches:
                try:
                    data_str = matches.group(1)
                    # Handle HTML-encoded JSON
                    data_str = data_str.replace('&quot;', '"').replace('&amp;', '&')
                    data = json.loads(data_str)
                    
                    # Navigate to items
                    if isinstance(data, dict):
                        if "catalog" in data:
                            items = data["catalog"].get("items", [])
                        elif "items" in data:
                            items = data["items"]
                        else:
                            items = []
                        
                        if items:
                            logger.info(f"Scraped {len(items)} items from HTML")
                            return items[:20]
                except (json.JSONDecodeError, KeyError) as e:
                    logger.debug(f"Pattern {pattern} failed to parse: {e}")
                    continue
        
        logger.warning("Could not extract items from page HTML")
        return []
        
    except Exception as e:
        logger.error(f"Scrape approach failed: {e}")
        return []


def parse_item(raw_item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse a raw Vinted item into a normalized structure.
    Handles both API and scraped data formats.
    """
    # Handle different price formats
    price_data = raw_item.get("price", 0)
    if isinstance(price_data, dict):
        price = float(price_data.get("amount", 0))
        currency = price_data.get("currency_code", "EUR")
    elif isinstance(price_data, str):
        # Try to parse price string like "15,00 €"
        import re
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
    
    return {
        "item_id": str(item_id),
        "title": raw_item.get("title", ""),
        "price": price,
        "currency": currency,
        "brand": raw_item.get("brand_title", "") or raw_item.get("brand", ""),
        "size": raw_item.get("size_title", "") or raw_item.get("size", ""),
        "url": url,
        "photo_url": raw_item.get("photo", {}).get("url", "") if isinstance(raw_item.get("photo"), dict) else raw_item.get("photo", ""),
        "raw_json": raw_item
    }
