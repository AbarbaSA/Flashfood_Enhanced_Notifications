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

def get_next_weekday(day_name: str) -> datetime:
    #Gets the next occurrence of a weekday (input 'saturday')
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    #idk if config checks are necessary but it's more robust
    target_day = days.index(day_name.lower())
    
    # Note, does server location of GH change what 'now' means?
    today = datetime.now()
    current_day_int = today.weekday()

    days_ahead = target_day - current_day_int
    if days_ahead < 0:  # Target day already happened this week
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
    
    new_items = {}
    notifications = []  # List of (item, store, reasons)
    chat_id = user.get("telegram_chat_id")

    # Process favorite stores
    favorite_config = user.get("favorite_stores", {})
    if favorite_config.get("enabled"):
        fav_store_ids = favorite_config.get("store_ids", [])
        expiry_filter = favorite_config.get("expiry_filter")


        for store_id in fav_store_ids:
            store = all_stores_in_area.get(store_id)

            # if they're out of range, could happen
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

                #This will duplicate notifications if there's overlap between favourite
                #stores and deal alert stores
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

                # reason we're making this a notification in case multiple exist
                # necessary?    
                reasons = []

                # Check if price is below great deal threshold
                try:
                    # default value if I can't find it in dict
                    price = float(item.get("price", 100000))
                    if price_below and price < price_below:
                        reasons.append(f"Under ${price_below}")
                except (ValueError, TypeError):
                    pass

                # Check discount percentage
                 
                discount = calculate_discount_percent(
                    item.get("originalPrice", "0"),
                    item.get("price", "0")
                )
                
                if discount_above and discount >= discount_above:
                    reasons.append(f"Over {discount_above}% off")

                if not reasons:
                    continue

                new_items.setdefault(item_id, get_item_removal_date(item))
                #now I need to check for duplicates and add reasons together
                #made the notification
                for item, store, reasons in notifications:
                    message = format_create_notification(item, store, reasons)
                    send_telegram_message(telegram_token, chat_id, message)
    #making this a set removes duplicates.
    return list(set(new_items))

def get_item_removal_date(item:dict) -> datetime:
    # defaults to a week from now
    expiry_date = datetime.now() - timedelta(days=7)
    best_before_on_item = item.get("bestBeforeDate")
    if best_before_on_item:
        expiry_date = datetime.fromtimestamp(best_before_on_item)
    return expiry_date


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

    #maybe find address if unknown
    store_name = store.get("name", "Unknown Store")

    # Calculate discount
    discount_percentage = calculate_discount_percent(original_price, price)

    # Format expiry date - wanna make it day of the week based
    best_before = item.get("bestBeforeDate")
    if best_before:
        #strftime("Today is %A, %B %d, %y")
        #Today is Wednesday, April 09, 25
        # it isn't recognizing %y, will test.
        expiry = datetime.fromtimestamp(best_before).strftime("%a, %b %d, '%y")
    else:
        expiry = "N/A"

    # making message, can use a little styling
    price_string = "Price: <b>${price}</b>" 
    + (f" (was ${original_price}, {discount_percentage:.0f}% off)" 
    if discount_percentage > 0 else ""),

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

    # Add picture if available
    image_url = item.get("imageUrl")
    if image_url:
        lines.append("")
        lines.append(f'<a href="{image_url}"></a>')

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
    # Process each user
    all_new_items = {}
    for user in config.get("users", []):
        new_items = handle_new_user_notifications(user, user_stores, seen_items, telegram_token)
        all_new_items.extend(new_items)

    for item_id, expiry in all_new_items:
        seen_items.setdefault("items", {})[item_id] = expiry.isoformat()


    # find expiry date. If none, put a week from now.
    # run check and remove any that have already expired.
    # seen items need to have their expiry date when added.
    seen_item_pairs = seen_items.get("items", {}).items()
    recently_seen_items = {
        item_id: expiry_date for item_id, expiry_date in seen_item_pairs
        if datetime.fromisoformat(expiry_date) >= datetime.now()
    }

    # Update seen_items with the filtered recent items
    seen_items["items"] = recently_seen_items
    #must rewrite seen items now to update



if __name__ == "__main__":
    main()
    