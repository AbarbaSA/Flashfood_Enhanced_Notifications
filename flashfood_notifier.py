#polls flashfood and sends telegram bot notifications according to criteria.
import json
import os
from pathlib import Path
import requests


# Keeping these as secrets in case they're sensitive
def get_flashfood_config() -> tuple[str, dict]:
    
    #Gets Flashfood API fields and headers from environment variables
    api_url = os.environ.get("FLASHFOOD_API_URL")
    api_key = os.environ.get("FLASHFOOD_API_KEY")
    app_info = os.environ.get("FLASHFOOD_APP_INFO")

    if not all([api_url, api_key, app_info]):
        raise ValueError(
            "Missing flashfood environment variables: "
            "FLASHFOOD_API_URL, FLASHFOOD_API_KEY, FLASHFOOD_APP_INFO"
        )

    headers = {
        "accept": "application/json",
        "x-ff-api-key": api_key,
        "flashfood-app-info": app_info,
        "User-Agent": "okhttp/4.12.0"
    }

    return api_url, headers

# Full file paths
SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "config.json"
SEEN_ITEMS_FILE = SCRIPT_DIR / "seen_items.json"

def load_config() -> dict:
    #loads local config
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(f"Config file not found: {CONFIG_FILE}")
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)
    
def load_seen_items() -> dict:
    #don't want to alert on items already sent. Probably don't
    #want to keep adding stuff to this list forever and ever
    if not SEEN_ITEMS_FILE.exists():
        return {"items": {}, "last_updated": None}
    with open(SEEN_ITEMS_FILE, "r") as f:
        return json.load(f)

def get_stores_by_location(api_url: str, headers: dict, latitude: float, longitude: float, max_distance: int = 75000) -> list[dict]:
# gets all stores near specified location and all their items
    
    search_criteria = {
        "storesWithItemsLimit": 30,
        "includeItems": "true",
        "searchLatitude": latitude,
        "searchLongitude": longitude,
        "userLocationLatitude": latitude,
        "userLocationLongitude": longitude,
        "maxDistance": max_distance
    }

    try:
        response = requests.get(api_url, headers=headers, params=search_criteria, timeout=30)
        response.raise_for_status()
        data = response.json()

        if data.get("status") == "success":
            return data.get("data", [])
    except requests.RequestException as e:
        print(f"Getting stores by location failed: {e}")

    return []

def get_user_store_ids(user: dict) -> set[str]:
    # take in user, get their store id's
    store_ids = set()

    favorite = user.get("favorite_stores", {})
    if favorite.get("enabled"):
        store_ids.update(favorite.get("store_ids", []))

    deals = user.get("deal_alerts", {})
    if deals.get("enabled"):
        store_ids.update(deals.get("store_ids", []))

    return store_ids

def main():
    # Get telegram token from environment
    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not telegram_token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set")

    # Get Flashfood API config from environment
    api_url, headers = get_flashfood_config()

    # Load config
    config = load_config()

    # Load seen items
    seen_items = load_seen_items()

    for user in config.get("users", []):
        user_name = user.get("name", "Unknown")
        location = user.get("location", {})
        lat = location.get("latitude")
        lng = location.get("longitude")

        user_store_ids = get_user_store_ids(user)

        # want to skip if nothing is configured and not send a bogus request
        if not user_store_ids:
            continue
        # Get stores near this user's location
        print(f"Finding stores for {user_name} near ({lat}, {lng})")
        all_nearby_stores = get_stores_by_location(api_url, headers, lat, lng)

        # Filter to just the stores this user cares about
        user_stores = {}
        for store in all_nearby_stores:
            store_id = store.get("id")
            if store_id and store_id in user_store_ids:
                user_stores[store_id] = store

        # Then figure out what notification to send


if __name__ == "__main__":
    main()
    