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
TELEGRAM_UPDATES_URL = "https://api.telegram.org/bot{token}/getUpdates"
TELEGRAM_PIN_URL = "https://api.telegram.org/bot{token}/pinChatMessage"
TELEGRAM_UNPIN_URL = "https://api.telegram.org/bot{token}/unpinChatMessage"
REFUND_FORM_URL = "https://help.flashfood.com/hc/en-us/requests/new?ticket_form_id=360006113853&tf_anonymous_requester_email={email}"

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


def get_store_with_items(api_url: str, headers: dict, store_id: str, store_name: str) -> Optional[dict]:
    # fetches items for a single store by ID
    try:
        url = f"{api_url}/{store_id}/items"
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()

        if data.get("status") == "success":
            return {
                "id": store_id,
                "name": store_name,
                "items": data.get("data", [])
            }
    except requests.RequestException as e:
        print(f"Error fetching store {store_name} ({store_id}): {e}")

    return None

def extract_store_id(store_entry) -> str:
    # handles both new format {"id": "...", "name": "..."} and old format "..."
    if isinstance(store_entry, dict):
        return store_entry.get("id", "")
    return store_entry

def extract_store_name(store_entry) -> str:
    if isinstance(store_entry, dict):
        return store_entry.get("name", "Unknown Store")
    return "Unknown Store"

def get_user_store_ids(user: dict) -> set[str]:
    # take in user, get their store id's
    store_ids = set()

    favorite = user.get("favorite_stores", {})
    if favorite.get("enabled"):
        for entry in favorite.get("store_ids", []):
            store_ids.add(extract_store_id(entry))

    deals = user.get("deal_alerts", {})
    if deals.get("enabled"):
        for entry in deals.get("store_ids", []):
            store_ids.add(extract_store_id(entry))

    return store_ids

def get_all_store_entries(config: dict) -> dict:
    # returns {store_id: store_name} for all stores across all users
    store_entries = {}
    for user in config.get("users", []):
        for section in ["favorite_stores", "deal_alerts"]:
            section_config = user.get(section, {})
            if section_config.get("enabled"):
                for entry in section_config.get("store_ids", []):
                    sid = extract_store_id(entry)
                    name = extract_store_name(entry)
                    if sid:
                        store_entries[sid] = name
    return store_entries

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

def handle_new_user_notifications(user: dict, all_stores_in_area: dict, seen_items_obj_dict: dict, telegram_token: str) -> dict:
  # returns list of newly seen item IDs.
    chat_id = user.get("telegram_chat_id")

    if not chat_id:
        return []

    new_items = {}
    notifications = []  # List of (item, store, reasons, stop)


    # Process favorite stores
    favorite_config = user.get("favorite_stores", {})
    if favorite_config.get("enabled"):
        fav_store_entries = favorite_config.get("store_ids", [])
        expiry_filter = favorite_config.get("expiry_filter")


        for entry in fav_store_entries:
            store_id = extract_store_id(entry)
            store = all_stores_in_area.get(store_id)
            if not store:
                continue

            stop = entry.get("stop") if isinstance(entry, dict) else None

            for item in store.get("items", []):
                item_id = str(item.get("id", ""))
                seen_item_ids = seen_items_obj_dict.get("items", {}).keys()
                if not item_id or item_id in seen_item_ids:
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
                    notifications.append((item, store, ["Favorite store"], stop))


    # Process deal notifications
    deal_config = user.get("deal_alerts", {})
    if deal_config.get("enabled"):
        deal_store_entries = deal_config.get("store_ids", [])
        price_below = deal_config.get("price_below")
        discount_above = deal_config.get("discount_above_percent")
        exclude_keywords = [kw.lower() for kw in deal_config.get("exclude_keywords", [])]


        for entry in deal_store_entries:
            store_id = extract_store_id(entry)
            store = all_stores_in_area.get(store_id)
            if not store:
                continue

            stop = entry.get("stop") if isinstance(entry, dict) else None

            for item in store.get("items", []):
                item_id = str(item.get("id", ""))
                seen_item_ids = seen_items_obj_dict.get("items", {}).keys()
                if not item_id or item_id in seen_item_ids:
                    continue

                # Check exclude keywords
                item_name_lower = item.get("name", "").lower()
                if any(kw in item_name_lower for kw in exclude_keywords):
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
                    notifications.append((item, store, criteria_satisfied, stop))

    # Send all notifications after both favorite and deal processing
    for item, store, criteria_satisfied, stop in notifications:
        message = format_create_notification(item, store, criteria_satisfied, stop)
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

def pin_refund_links(telegram_token: str, config: dict, seen_items: dict):
    pinned = seen_items.setdefault("pinned_refund", {})

    for user in config.get("users", []):
        chat_id = user.get("telegram_chat_id")
        email = user.get("email", "")
        if not chat_id or not email:
            continue
        existing = pinned.get(chat_id, {})
        if existing.get("email") == email:
            continue

        # Unpin old message if email changed
        old_msg_id = existing.get("message_id")
        if old_msg_id:
            try:
                unpin_url = TELEGRAM_UNPIN_URL.format(token=telegram_token)
                requests.post(unpin_url, json={
                    "chat_id": chat_id,
                    "message_id": old_msg_id,
                }, timeout=30)
            except requests.RequestException:
                pass

        refund_url = REFUND_FORM_URL.format(email=requests.utils.quote(email))
        url = TELEGRAM_API_URL.format(token=telegram_token)
        payload = {
            "chat_id": chat_id,
            "text": f'<a href="{refund_url}">Submit a refund request</a>',
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        try:
            response = requests.post(url, json=payload, timeout=30)
            response.raise_for_status()
            message_id = response.json().get("result", {}).get("message_id")
            if message_id:
                pin_url = TELEGRAM_PIN_URL.format(token=telegram_token)
                requests.post(pin_url, json={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "disable_notification": True,
                }, timeout=30)
                pinned[chat_id] = {"email": email, "message_id": message_id}
                print(f"Pinned refund link for {user.get('name')}")
        except requests.RequestException as e:
            print(f"Error pinning refund link for {user.get('name')}: {e}")

def format_create_notification(item: dict, store: dict, match_reasons: list[str], stop: Optional[dict] = None) -> str:
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
    price_string = (f"<b>${price}</b>"
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

    if stop and stop.get("distance_km") is not None:
        lines.append(f"{stop['distance_km']}km from {stop['name']}")

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

    # Pin refund links for users with emails (once per user)
    pin_refund_links(telegram_token, config, seen_items)

    # Fetch all stores once, then distribute to users
    all_store_entries = get_all_store_entries(config)
    print(f"Fetching items from {len(all_store_entries)} stores")

    fetched_stores = {}
    for store_id, store_name in all_store_entries.items():
        store_data = get_store_with_items(api_url, headers, store_id, store_name)
        if store_data:
            fetched_stores[store_id] = store_data

    print(f"Successfully fetched {len(fetched_stores)} stores")

    all_new_items = {}
    for user in config.get("users", []):
        user_store_ids = get_user_store_ids(user)
        if not user_store_ids:
            continue

        # Filter fetched stores to just this user's stores
        user_stores = {sid: data for sid, data in fetched_stores.items() if sid in user_store_ids}

        # Process this user's notifications with their own stores
        new_items = handle_new_user_notifications(user, user_stores, seen_items, telegram_token)
        all_new_items.update(new_items)

    # Update seen items
    for item_id, expiry in all_new_items.items():
        seen_items.setdefault("items", {})[item_id] = expiry.isoformat()


    # Removing seen items that have expired
    seen_item_pairs = seen_items.get("items", {}).items()
    recently_seen_items = {
        item_id: expiry_date for item_id, expiry_date in seen_item_pairs
        if datetime.fromisoformat(expiry_date).date() >= (datetime.now() - timedelta(days=2)).date()
    }

    # Update seen_items with the filtered recent items
    seen_items["items"] = recently_seen_items
    #must rewrite seen items now to update
    save_seen_items(seen_items)



if __name__ == "__main__":
    main()
    