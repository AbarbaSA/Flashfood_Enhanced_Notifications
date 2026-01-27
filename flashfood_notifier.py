#polls flashfood and sends telegram bot notifications according to criteria.
from datetime import datetime, timedelta
from typing import Optional
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

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"

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
    # returns the dict of previously seen items
    if not SEEN_ITEMS_FILE.exists():
        return {"items": {}, "last_updated": None}
    with open(SEEN_ITEMS_FILE, "r") as seen_items_file:
        return json.load(seen_items_file)

def get_stores_by_location(api_url: str, headers: dict, latitude: float, longitude: float, max_distance: int = 75000) -> list[dict]:
    # gets all stores near specified location and all their items
    search_criteria = {
        "storesWithItemsLimit": 50,
        "includeItems": "true",
        "searchLatitude": latitude,
        "searchLongitude": longitude,
        "userLocationLatitude": latitude,
        "userLocationLongitude": longitude,
        "maxDistance": max_distance
    }

    try:
        response = requests.get(api_url, headers=headers, params=search_criteria, timeout=30)
        # raises HTTP error if bad, jumps to except block
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

def get_next_weekday(day_name: str) -> datetime:
    #Gets the next occurrence of a weekday (input 'saturday')
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    grocery_day = days.index(day_name.lower())
    
    today = datetime.now()
    current_day_int = today.weekday()

    days_ahead = grocery_day - current_day_int
    if days_ahead < 0:  # Grocery day already happened this week
        days_ahead += 7

    return today + timedelta(days=days_ahead)

def item_passes_expiry_filter(item: dict, expiry_filter: Optional[dict]) -> bool:
    if expiry_filter is None:
        return True

    best_before = item.get("bestBeforeDate")
    if not best_before:
        return True  # expiry DNE, pass on

    # Convert Unix timestamp to datetime
    expiry_date = datetime.fromtimestamp(best_before)

    if "day_of_week" in expiry_filter:
        grocery_day_date = get_next_weekday(expiry_filter["day_of_week"])
        
        # must expire on or after grocery day
        return expiry_date.date() >= grocery_day_date.date()

    return True

def handle_new_user_notifications(user: dict, all_stores_in_area: dict, seen_items: dict, telegram_token: str) -> dict:
  # returns list of newly seen item IDs.
    chat_id = user.get("telegram_chat_id")

    if not chat_id:
        return []

    new_items = {}
    notifications = []  # List of (item, store, reasons)


    # Process favorite stores
    favorite_config = user.get("favorite_stores", {})
    if favorite_config.get("enabled"):
        fav_store_ids = favorite_config.get("store_ids", [])
        expiry_filter = favorite_config.get("expiry_filter")


        for store_id in fav_store_ids:
            store = all_stores_in_area.get(store_id)
            if not store:
                continue

            for item in store.get("items", []):
                item_id = item.get("id")
                if not item_id or item_id in seen_items.get("items", {}):
                    continue

                # expiry logic check (expires before grocery day this week)
                if not item_passes_expiry_filter(item, expiry_filter):
                    continue

                # This is a new item that passes and needs a removal date generated
                new_items.setdefault(item_id, get_item_removal_date(item))

                # Check if already in notifications (from deal alerts)
                existing = next((notification for notification in notifications if notification[0].get("id") == item_id), None)
                if existing:
                    existing[2].append("Favorite store")
                else:
                    notifications.append((item, store, ["Favorite store"]))


    # Process deal notifications
    deal_config = user.get("deal_alerts", {})
    if deal_config.get("enabled"):
        less_convenient_store_ids = deal_config.get("store_ids", [])
        price_below = deal_config.get("price_below")
        discount_above = deal_config.get("discount_above_percent")


        for store_id in less_convenient_store_ids:
            store = all_stores_in_area.get(store_id)
            if not store:
                continue

            for item in store.get("items", []):
                item_id = item.get("id")
                if not item_id or item_id in seen_items.get("items", {}):
                    continue
   
                criteria_satisfied = []

                # Check if price is below great deal threshold
                try:
                    price = float(item.get("price", 100000))
                    if price_below and price < price_below:
                        criteria_satisfied.append(f"Under ${price_below}")
                except (ValueError, TypeError):
                    pass

                # Check discount percentage
                 
                discount = calculate_discount_percent(
                    item.get("originalPrice", "0"),
                    item.get("price", "0")
                )
                
                if discount_above and discount >= discount_above:
                    criteria_satisfied.append(f"Over {discount_above}% off")

                if not criteria_satisfied:
                    continue

                new_items.setdefault(item_id, get_item_removal_date(item))

                #now I need to check for duplicates and add reasons together
                existing = next((notification for notification in notifications if notification[0].get("id") == item_id), None)
                if existing:
                    existing[2].extend(criteria_satisfied)
                else:
                    notifications.append((item, store, criteria_satisfied))

    # Send all notifications after both favorite and deal processing
    for item, store, criteria_satisfied in notifications:
        message = format_create_notification(item, store, criteria_satisfied)
        send_telegram_message(telegram_token, chat_id, message)
    return new_items

def get_item_removal_date(item:dict) -> datetime:
    # defaults to a month from now
    expiry_date = datetime.now() + timedelta(days=30)
    best_before_on_item = item.get("bestBeforeDate")
    if best_before_on_item:
        expiry_date = datetime.fromtimestamp(best_before_on_item)
    return expiry_date

def save_seen_items(seen_items: dict):
    # Overwrites seen items file with updated dict
    seen_items["last_updated"] = datetime.now().isoformat()
    with open(SEEN_ITEMS_FILE, "w") as seen_items_file:
        json.dump(seen_items, seen_items_file, indent=2)

def send_telegram_message(token: str, chat_id: str, message: str) -> bool:
    url = TELEGRAM_API_URL.format(token=token)
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }

    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        return True
    except requests.RequestException as e:
        print(f"Error sending Telegram message: {e}")
        return False

def format_create_notification(item: dict, store: dict, match_reasons: list[str]) -> str:
    name = item.get("name", "Unknown Item")
    price = item.get("price", "?")
    original_price = item.get("originalPrice", price)
    quantity = item.get("quantityAvailable", "?")

    store_name = store.get("name", "Unknown Store")

    # Calculate discount
    discount_percentage = calculate_discount_percent(original_price, price)

    # Format expiry date
    best_before = item.get("bestBeforeDate")
    if best_before:
        expiry = datetime.fromtimestamp(best_before).strftime("%a, %b %d, '%y")
    else:
        expiry = "N/A"

    # Make message
    price_string = (f"Price: <b>${price}</b>"
        + (f" (was ${original_price}, {discount_percentage:.0f}% off)"
        if discount_percentage > 0 else ""))

    lines = [
        f"<b>{name}</b>",
        f"",
        f"Price: {price_string}",
        f"Qty: {quantity}",
        f"Expires: {expiry}",
        f"Store: {store_name}",
    ]
    # Add match reasons
    if match_reasons:
        lines.append("")
        lines.append(f"<i>Matched: {', '.join(match_reasons)}</i>")

    # Add picture if available — link must have text content or it
    image_url = item.get("imageUrl")
    if image_url:
        lines.append(f'<a href="{image_url}">&#8205;</a>')

    return "\n".join(lines)
    

def calculate_discount_percent(original_price: str, final_price: str) -> float:
    try:
        original = float(original_price)
        current = float(final_price)
        if original <= 0:
            return 0
        return ((original - current) / original) * 100
    except (ValueError, TypeError):
        return 0

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

    # Fixed the context window bug here
    all_new_items = {}
    for user in config.get("users", []):
        user_name = user.get("name", "Unknown")
        location = user.get("location", {})
        lat = location.get("latitude")
        lng = location.get("longitude")

        # get_user_store_ids collects all store IDs this user cares about (favorites + deals)
        user_store_ids = get_user_store_ids(user)

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

        # Process this user's notifications with their own stores
        new_items = handle_new_user_notifications(user, user_stores, seen_items, telegram_token)
        all_new_items.update(new_items)

    # Update seen items
    for item_id, expiry in all_new_items.items():
        seen_items.setdefault("items", {})[item_id] = expiry.isoformat()


    # Removing seen items that have expired; older than 30 days
    seen_item_pairs = seen_items.get("items", {}).items()
    recently_seen_items = {
        item_id: expiry_date for item_id, expiry_date in seen_item_pairs
        if datetime.fromisoformat(expiry_date) >= datetime.now()
    }

    # Update seen_items with the filtered recent items
    seen_items["items"] = recently_seen_items
    #must rewrite seen items now to update
    save_seen_items(seen_items)



if __name__ == "__main__":
    main()
    