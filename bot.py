# bot.py

import time
import asyncio
from datetime import datetime, timezone, timedelta
from ddgs import DDGS
from pymongo import MongoClient
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    filters,
    ChatMemberHandler,
)
from telegram import ChatMemberUpdated, ChatMember
from config import (
    BOT_TOKEN, MAX_RESULTS, TOR_PROXY, MONGO_URI, CACHE_EXPIRY_DAYS,
    CHANNEL_ID, CHANNEL_LINK, MAIN_GROUP_ID, GROUP_LINK,
    ADMIN_IDS, QR_IMAGE_URL, UPI_ID, PREMIUM_PLANS, PLANS_MESSAGE,
    DAILY_FREE_SEARCHES, PLAN_MESSAGE_GROUP_ID, PLAN_MESSAGE_ID,
    PREMIUM_BOT_USERNAME, PREMIUM_BOT_TOKEN, IMAGE_SEARCH_ENABLED,
    IMAGE_CACHE_EXPIRY_DAYS, WELCOME_MESSAGE
)
from filters import apply_filters, clean_title

# ── MongoDB ───────────────────────────────────────────────────────────────────
mongo = MongoClient(MONGO_URI)
db = mongo["terabox_bot"]

# Collections
col = db["search_cache"]
col.create_index("query", unique=True)
col.create_index("saved_at")

users_col = db["users"]  # User premium status and search counts
users_col.create_index("user_id", unique=True)

manual_links_col = db["manual_links"]  # Admin added movie links
manual_links_col.create_index("query")

requests_col = db["movie_requests_new"]  # User movie requests
requests_col.create_index("user_id")
requests_col.create_index("status")

user_sessions = {}

# ── Image Cache Collection ─────────────────────────────────────────────────────
image_cache_col = db["image_cache"]
image_cache_col.create_index("query", unique=True)
image_cache_col.create_index("saved_at")

# ── Image Search Functions ─────────────────────────────────────────────────────

def search_movie_image(query: str) -> str:
    """Search for movie poster image using DDG images"""
    # Check cache first
    cached = image_cache_col.find_one({"query": query.lower()})
    if cached:
        print(f"[Image Cache] Hit for: {query}")
        return cached.get("image_url")
    
    for attempt in range(1, 3):
        try:
            print(f"[Image Search] Attempt {attempt}/2 for: {query}")
            ddgs = DDGS(proxy=TOR_PROXY, timeout=15)
            
            # Search for movie poster
            image_results = ddgs.images(
                f"{query} movie poster",
                region="in-en",
                safesearch="off",
                max_results=5
            )
            
            # Find a good poster image
            for img in image_results:
                url = img.get("image")
                if url and url.startswith("http") and any(ext in url.lower() for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                    # Cache the image URL
                    image_cache_col.update_one(
                        {"query": query.lower()},
                        {"$set": {
                            "query": query.lower(),
                            "image_url": url,
                            "saved_at": datetime.now(timezone.utc)
                        }},
                        upsert=True
                    )
                    print(f"[Image Search] Found image for: {query}")
                    return url
            
        except Exception as e:
            print(f"[Image Search] Attempt {attempt} failed: {e}")
    
    print(f"[Image Search] No image found for: {query}")
    return None


def clear_expired_image_cache():
    """Clear expired image cache"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=IMAGE_CACHE_EXPIRY_DAYS)
    result = image_cache_col.delete_many({"saved_at": {"$lt": cutoff}})
    if result.deleted_count > 0:
        print(f"[Image Cache] Cleared {result.deleted_count} expired image entries")

# ── User Helpers ─────────────────────────────────────────────────────────────

def get_user(user_id: int):
    return users_col.find_one({"user_id": user_id})

def create_user(user_id: int):
    users_col.update_one(
        {"user_id": user_id},
        {"$setOnInsert": {
            "user_id": user_id,
            "premium_type": "free",
            "premium_expires": None,
            "total_searches": 0,
            "daily_searches": 0,
            "last_search_date": None,
            "searches_today": 0,
            "created_at": datetime.now(timezone.utc)
        }},
        upsert=True
    )

def make_aware(dt):
    """Convert datetime to timezone-aware if it isn't already"""
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    return dt

def get_user_searches_today(user_id: int) -> dict:
    user = get_user(user_id)
    if not user:
        return {"count": 0, "limit": DAILY_FREE_SEARCHES, "is_premium": False}
    
    today = datetime.now(timezone.utc).date()
    last_search_date = user.get("last_search_date")
    
    # Reset daily count if it's a new day
    if last_search_date:
        last_date = last_search_date.date() if isinstance(last_search_date, datetime) else last_search_date
        if last_date < today:
            users_col.update_one(
                {"user_id": user_id},
                {"$set": {"searches_today": 0, "last_search_date": datetime.now(timezone.utc)}}
            )
            user["searches_today"] = 0
    
    premium_expires = make_aware(user.get("premium_expires"))
    is_premium = user.get("premium_type") != "free" and (
        premium_expires is None or premium_expires > datetime.now(timezone.utc)
    )
    
    limit = 999999 if is_premium else DAILY_FREE_SEARCHES
    
    return {
        "count": user.get("searches_today", 0),
        "limit": limit,
        "is_premium": is_premium,
        "premium_type": user.get("premium_type", "free"),
        "premium_expires": user.get("premium_expires")
    }

def increment_search(user_id: int):
    user = get_user(user_id)
    if not user:
        create_user(user_id)
        user = get_user(user_id)
    
    today = datetime.now(timezone.utc).date()
    last_search_date = user.get("last_search_date")
    
    # Reset daily count if it's a new day
    if last_search_date:
        last_date = last_search_date.date() if isinstance(last_search_date, datetime) else last_search_date
        if last_date < today:
            new_searches_today = 1
        else:
            new_searches_today = user.get("searches_today", 0) + 1
    else:
        new_searches_today = 1
    
    users_col.update_one(
        {"user_id": user_id},
        {"$inc": {"total_searches": 1, "searches_today": 1},
         "$set": {"last_search_date": datetime.now(timezone.utc)}}
    )

def grant_premium(user_id: int, plan_type: str, days: int):
    user = get_user(user_id)
    now = datetime.now(timezone.utc)
    
    if user and user.get("premium_expires") and user["premium_expires"] > now:
        # Extend existing premium
        new_expiry = user["premium_expires"] + timedelta(days=days)
    else:
        # New premium
        new_expiry = now + timedelta(days=days)
    
    users_col.update_one(
        {"user_id": user_id},
        {"$set": {
            "premium_type": plan_type,
            "premium_expires": new_expiry
        }}
    )
    return new_expiry

def get_user_stats(user_id: int) -> dict:
    user = get_user(user_id)
    if not user:
        return None
    
    now = datetime.now(timezone.utc)
    premium_expires = make_aware(user.get("premium_expires"))
    is_premium = user.get("premium_type") != "free" and (
        premium_expires is None or premium_expires > now
    )
    
    days_left = 0
    if is_premium and premium_expires:
        days_left = (premium_expires - now).days
    
    return {
        "user_id": user_id,
        "premium_type": user.get("premium_type", "free"),
        "total_searches": user.get("total_searches", 0),
        "searches_today": user.get("searches_today", 0),
        "is_premium": is_premium,
        "days_left": days_left,
        "premium_expires": user.get("premium_expires")
    }

def get_all_users() -> list:
    return list(users_col.find())

def get_premium_users() -> list:
    now = datetime.now(timezone.utc)
    return list(users_col.find({
        "premium_type": {"$ne": "free"},
        "$or": [
            {"premium_expires": None},
            {"premium_expires": {"$gt": now}}
        ]
    }))

# ── Manual Links Helpers ─────────────────────────────────────────────────────

def add_manual_link(query: str, link: str):
    manual_links_col.update_one(
        {"query": query.lower()},
        {"$set": {"query": query.lower(), "link": link, "added_at": datetime.now(timezone.utc)}},
        upsert=True
    )

def get_manual_link(query: str):
    return manual_links_col.find_one({"query": query.lower()})

def get_all_manual_links():
    return list(manual_links_col.find())

def delete_manual_link(query: str):
    manual_links_col.delete_one({"query": query.lower()})

# ── Movie Request Helpers ─────────────────────────────────────────────────────

def add_movie_request(user_id: int, username: str, movie_name: str):
    requests_col.update_one(
        {"user_id": user_id, "movie_name": movie_name},
        {"$set": {
            "user_id": user_id,
            "username": username,
            "movie_name": movie_name,
            "status": "pending",
            "requested_at": datetime.now(timezone.utc)
        }},
        upsert=True
    )

def get_pending_requests():
    return list(requests_col.find({"status": "pending"}))

def update_request_status(user_id: int, movie_name: str, status: str, link: str = None):
    update_data = {"status": status}
    if link:
        update_data["link"] = link
    requests_col.update_one(
        {"user_id": user_id, "movie_name": movie_name},
        {"$set": update_data}
    )

# ── Cache helpers ─────────────────────────────────────────────────────────────

def cache_get(query: str):
    doc = col.find_one({"query": query})
    if doc:
        print(f"[Cache] Hit for: {query} (saved: {doc.get('saved_at', '?')})")
        return doc["results"]
    return None


def cache_set(query: str, results: list):
    col.update_one(
        {"query": query},
        {"$set": {
            "query": query,
            "results": results,
            "saved_at": datetime.now(timezone.utc),
            "count": len(results),
        }},
        upsert=True,
    )
    print(f"[Cache] Saved {len(results)} results for: {query}")


def clear_expired_cache():
    cutoff = datetime.now(timezone.utc) - timedelta(days=CACHE_EXPIRY_DAYS)
    result = col.delete_many({"saved_at": {"$lt": cutoff}})
    if result.deleted_count > 0:
        print(f"[Cache] Cleared {result.deleted_count} expired entries (older than {CACHE_EXPIRY_DAYS} days)")
    else:
        print(f"[Cache] No expired entries to clear")


# ── Background task: auto-clear cache daily ───────────────────────────────────

cache_task = None

async def auto_clear_cache_loop():
    while True:
        try:
            await asyncio.sleep(24 * 60 * 60)
            clear_expired_cache()
        except asyncio.CancelledError:
            print("[Cache] Auto-clear task cancelled")
            raise


# ── Search ────────────────────────────────────────────────────────────────────

def do_search(query: str) -> list:
    # Check manual links first
    manual = get_manual_link(query)
    if manual:
        print(f"[Search] Found manual link for: {query}")
        return [{
            "position": 1,
            "title": f"{query.title()} - Manual Link",
            "link": manual["link"],
            "displayed_link": manual["link"].split("?")[0],
            "snippet": "Admin added link",
            "source": "Manual",
            "is_valid_share_link": True,
        }]
    
    cached = cache_get(query)
    if cached:
        return cached

    for attempt in range(1, 4):
        try:
            print(f"[Search] Attempt {attempt}/3 for: {query}")
            ddgs = DDGS(proxy=TOR_PROXY, timeout=20)
            raw_results = ddgs.text(
                f"site:terabox.com {query}",
                region="in-en",
                safesearch="off",
                max_results=20,
            )
            filtered = apply_filters(raw_results, query)

            if filtered:
                cache_set(query, filtered)
                print(f"[Search] Found {len(filtered)} results on attempt {attempt}")
                return filtered
            else:
                print(f"[Search] No valid results on attempt {attempt}, retrying...")

        except Exception as e:
            print(f"[Search] Attempt {attempt} failed: {e}")

    print(f"[Search] All attempts failed for: {query}")
    return []


# ── Keyboard ──────────────────────────────────────────────────────────────────

def build_keyboard(results: list, page: int) -> InlineKeyboardMarkup:
    start = page * MAX_RESULTS
    end = start + MAX_RESULTS
    chunk = results[start:end]

    keyboard = []
    for r in chunk:
        url = r["link"]
        if not url.startswith("http"):
            url = "https://" + url
        label = clean_title(r["title"])
        if len(label) > 60:
            label = label[:57] + "..."
        keyboard.append([InlineKeyboardButton(label, url=url)])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data="prev"))
    if end < len(results):
        nav.append(InlineKeyboardButton("Next ➡️", callback_data="next"))
    if nav:
        keyboard.append(nav)

    return InlineKeyboardMarkup(keyboard)


def build_plan_keyboard(user_id: int):
    """Build plan keyboard with direct URL buttons to premium bot"""
    keyboard = [
        [InlineKeyboardButton("🥈 SILVER", url=f"https://t.me/{PREMIUM_BOT_USERNAME}?start=silver_{user_id}")],
        [InlineKeyboardButton("🥇 GOLD", url=f"https://t.me/{PREMIUM_BOT_USERNAME}?start=gold_{user_id}")],
        [InlineKeyboardButton("💎 DIAMOND", url=f"https://t.me/{PREMIUM_BOT_USERNAME}?start=diamond_{user_id}")],
        [InlineKeyboardButton("😆 LIFETIME", url=f"https://t.me/{PREMIUM_BOT_USERNAME}?start=lifetime_{user_id}")],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_admin_panel_keyboard():
    keyboard = [
        [InlineKeyboardButton("📊 Stats", callback_data="admin_stats")],
        [InlineKeyboardButton("👥 Premium Users", callback_data="admin_premium_users")],
        [InlineKeyboardButton("➕ Add Link", callback_data="admin_add_link")],
        [InlineKeyboardButton("📋 View Requests", callback_data="admin_view_requests")],
        [InlineKeyboardButton("🔗 All Links", callback_data="admin_all_links")],
        [InlineKeyboardButton("🔙 Close", callback_data="admin_close")],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_request_keyboard(request_id: str, movie_name: str, user_id: int):
    keyboard = [
        [InlineKeyboardButton("➕ Add Link", callback_data=f"req_add_{request_id}")],
        [InlineKeyboardButton("❌ Reject", callback_data=f"req_reject_{request_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)


# ── Chat Member Handler ────────────────────────────────────────────────────────

async def handle_chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle new member joins to send welcome message"""
    try:
        # Extract the ChatMemberUpdated object correctly
        chat_member_update = update.chat_member or update.my_chat_member
        if not chat_member_update:
            return

        chat = chat_member_update.chat

        # Only process in the main group
        if chat.id != MAIN_GROUP_ID:
            print(f"[ChatMember] Ignoring - not main group: {chat.id}")
            return

        old_member = chat_member_update.old_chat_member
        new_member = chat_member_update.new_chat_member

        old_status = old_member.status if old_member else None
        new_status = new_member.status if new_member else None

        print(f"[ChatMember] Update: {old_status} -> {new_status}")

        # Detect join: was left/kicked, now is member/restricted/administrator
        joined = (
            old_status in ["left", "kicked", None]
            and new_status in ["member", "restricted", "administrator"]
        )

        if joined:
            user = new_member.user

            if user.is_bot:
                return

            print(f"[Welcome] User joined: {user.first_name} ({user.id})")
            welcome_text = WELCOME_MESSAGE.format(user_name=user.first_name)

            await context.bot.send_message(
                chat_id=chat.id,
                text=welcome_text
            )

    except Exception as e:
        print(f"[Welcome Error] {e}")

# ── Handlers ──────────────────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Check if message is from the main group
    chat = update.effective_chat
    if chat.type != "group" and chat.type != "supergroup":
        return
    
    if chat.id != MAIN_GROUP_ID:
        return
    
    query = update.message.text.strip()
    user_id = update.effective_user.id

    # Create user if not exists
    create_user(user_id)
    
    # Check search limit
    search_info = get_user_searches_today(user_id)
    
    # Check if user is member of the channel
    try:
        member = await context.bot.get_chat_member(CHANNEL_ID, user_id)
        if member.status in ["left", "kicked"]:
            keyboard = [
                [InlineKeyboardButton("🔗 Join Channel", url=CHANNEL_LINK)],
                [InlineKeyboardButton("✅ Verified", callback_data="verify_join")]
            ]
            await update.message.reply_text(
                "⚠️ You must join our channel to use this bot!\n\n"
                f"👉 Join: {CHANNEL_LINK}\n\n"
                "After joining, click 'Verified' button below.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
    except Exception as e:
        print(f"[Channel Check Error] {e}")

    # Check daily search limit for free users
    if not search_info["is_premium"]:
        if search_info["count"] >= search_info["limit"]:
            await update.message.reply_text(
                f"⚠️ Daily free searches ({DAILY_FREE_SEARCHES}) exhausted!\n\n"
                f"🔓 Upgrade to Premium for unlimited searches\n\n"
                "Select your plan:",
                reply_markup=build_plan_keyboard(user_id)
            )
            return

    msg = await update.message.reply_text("🔎 Searching...")

    try:
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(None, do_search, query.lower())

        if not results:
            # Offer to request the movie
            keyboard = [
                [InlineKeyboardButton("📝 Request This Movie", callback_data=f"request_movie_{query}_{user_id}")]
            ]
            await msg.edit_text(
                "❌ No results found.\n\n"
                "💡 Tips:\n"
                "• Use English movie/show name\n"
                "• Try shorter keywords\n\n"
                "Would you like to request this movie?",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        # Increment search count
        increment_search(user_id)
        
        user_sessions[user_id] = {"results": results, "page": 0, "query": query}
        keyboard = build_keyboard(results, 0)

        # Search for movie poster image if enabled
        image_url = None
        if IMAGE_SEARCH_ENABLED:
            try:
                image_url = await loop.run_in_executor(None, search_movie_image, query)
            except Exception as e:
                print(f"[Image Search Error] {e}")

        # Build response text
        response_text = f"🎬 Found *{len(results)}* result(s) for: `{query}`"
        
        # Send with or without image
        if image_url:
            try:
                await msg.delete()
                await update.message.reply_photo(
                    photo=image_url,
                    caption=response_text,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            except Exception as e:
                print(f"[Image Send Error] {e}")
                # Fallback to text without image
                await msg.edit_text(
                    response_text,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
        else:
            await msg.edit_text(
                response_text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )

    except Exception as e:
        print(f"[Handler Error] {e}")
        await msg.edit_text("⚠️ Something went wrong. Please try again.")


async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data

    # Handle verify callbacks
    if data in ["verify_join", "verify_start"]:
        try:
            member = await context.bot.get_chat_member(CHANNEL_ID, user_id)
            if member.status in ["left", "kicked"]:
                await query.edit_message_text(
                    f"⚠️ You still haven't joined the channel!\n\n"
                    f"👉 Join: {CHANNEL_LINK}\n\n"
                    "After joining, click 'Verified' again.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔗 Join Channel", url=CHANNEL_LINK)],
                        [InlineKeyboardButton("✅ Verified", callback_data="verify_start")]
                    ])
                )
                return
        except Exception as e:
            print(f"[Verify Error] {e}")
            await query.edit_message_text("⚠️ Error checking membership. Please try again.")
            return
        
        await send_welcome(query, user_id)
        return

    # Handle navigation (next/prev) - verify user session
    if data in ["next", "prev"]:
        if user_id not in user_sessions:
            await query.edit_message_text("⚠️ Session expired. Send your query again.")
            return
        session = user_sessions[user_id]

        if data == "next":
            session["page"] += 1
        elif data == "prev":
            session["page"] -= 1

        keyboard = build_keyboard(session["results"], session["page"])
        await query.edit_message_reply_markup(reply_markup=keyboard)
        return



    # Handle movie request - verify it's the same user who clicked
    if data.startswith("request_movie_"):
        parts = data.replace("request_movie_", "").split("_")
        if len(parts) < 2:
            await query.answer("⚠️ Invalid request!", show_alert=True)
            return
        requested_user_id = int(parts[-1])
        movie_name = "_".join(parts[:-1])
        if user_id != requested_user_id:
            await query.answer("⚠️ This button is not for you!", show_alert=True)
            return
        await handle_movie_request(query, user_id, movie_name)
        return

    # Handle admin panel buttons
    if user_id in ADMIN_IDS:
        if data == "admin_stats":
            await show_admin_stats(query)
            return
        elif data == "admin_premium_users":
            await show_premium_users(query)
            return
        elif data == "admin_add_link":
            await query.edit_message_text(
                "➕ Adding Manual Link\n\n"
                "Send me in this format:\n"
                "<code>query | link</code>\n\n"
                "Example:\n"
                "<code>Avengers | https://terabox.com/s/abc123</code>",
                parse_mode="HTML"
            )
            # Set state for next message
            context.user_data["awaiting_link"] = True
            return
        elif data == "admin_view_requests":
            await show_pending_requests(query)
            return
        elif data == "admin_all_links":
            await show_all_links(query)
            return
        elif data == "admin_panel":
            await send_admin_panel(query, context)
            return
        elif data == "admin_close":
            await query.edit_message_text("✅ Panel closed")
            return
        elif data.startswith("req_add_"):
            request_id = data.replace("req_add_", "")
            await query.edit_message_text(
                f"➕ Adding link for request #{request_id}\n\n"
                "Send the movie link:",
                parse_mode="HTML"
            )
            context.user_data["awaiting_request_link"] = request_id
            return
        elif data.startswith("req_reject_"):
            request_id = data.replace("req_reject_", "")
            requests_col.update_one(
                {"_id": request_id},
                {"$set": {"status": "rejected"}}
            )
            await query.edit_message_text(f"❌ Request #{request_id} rejected.")
            return


async def handle_plan_selection(query, user_id: int, plan_type: str, context: ContextTypes.DEFAULT_TYPE):
    """This function is now only used as fallback if direct redirect fails"""
    plan = PREMIUM_PLANS.get(plan_type)
    if not plan:
        await query.edit_message_text("❌ Invalid plan selection.")
        return
    
    # Fallback: show button if direct redirect didn't work
    premium_link = f"https://t.me/{PREMIUM_BOT_USERNAME}?start={plan_type}_{user_id}"
    
    keyboard = [
        [InlineKeyboardButton("✅ Continue to Payment", url=premium_link)],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_plan")]
    ]
    
    await query.edit_message_text(
        f"""📦 {plan['name']} {plan['emoji']}

Click below to continue:""",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def handle_movie_request(query, user_id: int, movie_name: str):
    username = query.from_user.username or "N/A"
    
    # Add request to database
    requests_col.insert_one({
        "user_id": user_id,
        "username": username,
        "movie_name": movie_name,
        "status": "pending",
        "requested_at": datetime.now(timezone.utc)
    })
    
    await query.edit_message_text(
        f"✅ Request submitted for: {movie_name}\n\n"
        "📋 Admins will review your request.\n"
        "🔔 You will be notified when the movie is added."
    )
    
    # Notify admins
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id,
                f"""📝 New Movie Request

👤 User: @{username}
🆔 User ID: {user_id}
🎬 Movie: {movie_name}

/addlink {movie_name} [link]"""
            )
        except:
            pass


async def send_welcome(query, user_id: int):
    welcome_text = """🎬 Welcome to Movies • Series Finder Bot
Find your favorite Movies & Web Series instantly🚀
━━━━━━━━━━━━━━━
🔍 How to works:

1. Join our official group 👇
   👉 @aurexia_movies
2. Send any movie or series name 🎥
3. Get working links instantly ⚡️
━━━━━━━━━━━━━━━
📢 Our Official Channel:
👉 @Aurexia_Store

👑 Owner:
👉 @AzTechDeveloper
━━━━━━━━━━━━━━━
⚠️ Note:
You must join the group to use this bot.

Enjoy unlimited entertainment 🍿🔥"""
    
    keyboard = [[InlineKeyboardButton("🎬 Join Group", url=GROUP_LINK)]]
    await query.edit_message_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard))


# ── Admin Stats ─────────────────────────────────────────────────────────────

async def show_admin_stats(query):
    total_users = users_col.count_documents({})
    premium_users = len(get_premium_users())
    free_users = total_users - premium_users
    
    # Get all users for stats
    all_users = list(users_col.find())
    total_searches = sum(u.get("total_searches", 0) for u in all_users)
    
    stats_text = f"""📊 Bot Statistics

👥 Total Users: {total_users}
✅ Premium Users: {premium_users}
❌ Free Users: {free_users}

🔍 Total Searches: {total_searches}

━━━━━━━━━━━━━━━
📅 Data refreshed: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}

🔄 Back to panel:"""
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="admin_stats")],
        [InlineKeyboardButton("🔙 Back to Panel", callback_data="admin_panel")]
    ])
    
    await query.edit_message_text(stats_text, reply_markup=keyboard)


async def show_premium_users(query):
    premium = get_premium_users()
    
    if not premium:
        await query.edit_message_text("❌ No premium users found.")
        return
    
    text = "👥 Premium Users:\n\n"
    for i, u in enumerate(premium[:20], 1):
        days_left = 0
        if u.get("premium_expires"):
            days_left = (u["premium_expires"] - datetime.now(timezone.utc)).days
        
        text += f"{i}. ID: {u['user_id']}\n   Plan: {u.get('premium_type', 'N/A').upper()}\n   Days left: {days_left}\n\n"
    
    if len(premium) > 20:
        text += f"...and {len(premium) - 20} more"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back to Panel", callback_data="admin_panel")]
    ])
    
    await query.edit_message_text(text, reply_markup=keyboard)


async def show_pending_requests(query):
    requests = get_pending_requests()
    
    if not requests:
        await query.edit_message_text("❌ No pending requests.")
        return
    
    text = "📋 Pending Movie Requests:\n\n"
    for i, r in enumerate(requests[:10], 1):
        text += f"{i}. 🎬 {r['movie_name']}\n   👤 @{r['username']}\n   📅 {r['requested_at'].strftime('%Y-%m-%d')}\n\n"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back to Panel", callback_data="admin_panel")]
    ])
    
    await query.edit_message_text(text, reply_markup=keyboard)


async def show_all_links(query):
    links = get_all_manual_links()
    
    if not links:
        await query.edit_message_text("❌ No manual links found.")
        return
    
    text = "🔗 Manual Links:\n\n"
    for i, l in enumerate(links[:20], 1):
        text += f"{i}. {l['query']}\n   🔗 {l['link']}\n\n"
    
    if len(links) > 20:
        text += f"...and {len(links) - 20} more"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back to Panel", callback_data="admin_panel")]
    ])
    
    await query.edit_message_text(text, reply_markup=keyboard)


# ── Start command handler for private messages ──────────────────────────────

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Check if admin
    if user_id in ADMIN_IDS:
        await send_admin_panel(update, context)
        return
    
    # Check if user is member of the channel
    try:
        member = await context.bot.get_chat_member(CHANNEL_ID, user_id)
        if member.status in ["left", "kicked"]:
            keyboard = [
                [InlineKeyboardButton("🔗 Join Channel", url=CHANNEL_LINK)],
                [InlineKeyboardButton("✅ Verified", callback_data="verify_start")]
            ]
            await update.message.reply_text(
                "⚠️ You must join our channel to use this bot!\n\n"
                f"👉 Join: {CHANNEL_LINK}\n\n"
                "After joining, click 'Verified' button below.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
    except Exception as e:
        print(f"[Channel Check Error] {e}")
    
    # Send welcome message
    await send_welcome_message(update)


async def send_welcome_message(update: Update):
    welcome_text = """🎬 Welcome to Movies • Series Finder Bot
Find your favorite Movies & Web Series instantly🚀
━━━━━━━━━━━━━━━
🔍 How to works:

1. Join our official group 👇
   👉 @aurexia_movies
2. Send any movie or series name 🎥
3. Get working links instantly ⚡️
━━━━━━━━━━━━━━━
📢 Our Official Channel:
👉 @Aurexia_Store

👑 Owner:
👉 @AzTechDeveloper
━━━━━━━━━━━━━━━
⚠️ Note:
You must join the group to use this bot.

Enjoy unlimited entertainment 🍿🔥"""
    
    keyboard = [[InlineKeyboardButton("🎬 Join Group", url=GROUP_LINK)]]
    await update.message.reply_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard))


async def send_admin_panel(update, context):
    keyboard = build_admin_panel_keyboard()
    
    text = """👑 Admin Panel

Welcome, Admin!

Choose an option:"""
    
    # Check if it's a callback query or message
    try:
        if hasattr(update, 'callback_query') and update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=keyboard)
        elif hasattr(update, 'edit_message_text'):
            await update.edit_message_text(text, reply_markup=keyboard)
        else:
            await update.message.reply_text(text, reply_markup=keyboard)
    except:
        # Fallback
        try:
            await update.message.reply_text(text, reply_markup=keyboard)
        except:
            await update.edit_message_text(text, reply_markup=keyboard)


# ── Premium Grant Commands ─────────────────────────────────────────────────────

async def grant_premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE, plan_type: str):
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Unauthorized.")
        return
    
    if not context.args:
        await update.message.reply_text(
            f"Usage: /{plan_type} <user_id> [days]\n\n"
            f"Example: /{plan_type} 123456789 30"
        )
        return
    
    try:
        target_user_id = int(context.args[0])
        days = int(context.args[1]) if len(context.args) > 1 else PREMIUM_PLANS[plan_type]["days"]
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID or days.")
        return
    
    # Grant premium
    expiry = grant_premium(target_user_id, plan_type, days)
    
    # Notify user
    try:
        await context.bot.send_message(
            target_user_id,
            f"🎉 Congratulations! Your {plan_type.upper()} plan has been activated!\n\n"
            f"📅 Valid until: {expiry.strftime('%Y-%m-%d')}\n\n"
            "Enjoy unlimited searches! 🚀"
        )
    except:
        pass
    
    await update.message.reply_text(
        f"✅ {plan_type.upper()} plan granted to user {target_user_id}\n"
        f"📅 Expires: {expiry.strftime('%Y-%m-%d')}"
    )


# ── Admin Payment Approval Handlers ──────────────────────────────────────────

async def handle_payment_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if user_id not in ADMIN_IDS:
        return
    
    data = query.data
    
    if data.startswith("approve_"):
        parts = data.split("_")
        target_user_id = int(parts[1])
        plan_type = parts[2]
        days = int(parts[3])
        
        # Grant premium
        expiry = grant_premium(target_user_id, plan_type, days)
        
        # Notify user
        try:
            await context.bot.send_message(
                target_user_id,
                f"🎉 Congratulations! Your {plan_type.upper()} plan has been activated!\n\n"
                f"📅 Valid until: {expiry.strftime('%Y-%m-%d')}\n\n"
                "Enjoy unlimited searches! 🚀"
            )
        except:
            pass
        
        await query.edit_message_text(f"✅ Approved! {plan_type.upper()} granted to {target_user_id}")
    
    elif data.startswith("reject_"):
        target_user_id = data.replace("reject_", "")
        
        await query.edit_message_text(f"❌ Payment rejected for user {target_user_id}")
        
        # Notify user
        try:
            await context.bot.send_message(
                target_user_id,
                "❌ Payment rejected. Please contact admin for more info."
            )
        except:
            pass


# ── Admin Add Link Handler ───────────────────────────────────────────────────

async def handle_admin_link_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Check for admin link adding
    if "awaiting_link" in context.user_data and context.user_data["awaiting_link"]:
        text = update.message.text
        
        if "|" not in text:
            await update.message.reply_text("❌ Invalid format. Use: query | link")
            return
        
        parts = text.split("|", 1)
        query = parts[0].strip()
        link = parts[1].strip()
        
        add_manual_link(query, link)
        
        context.user_data["awaiting_link"] = False
        
        await update.message.reply_text(
            f"✅ Link added successfully!\n\n"
            f"🔍 Query: {query}\n"
            f"🔗 Link: {link}"
        )
        return
    
    # Handle request link
    if "awaiting_request_link" in context.user_data:
        link = update.message.text.strip()
        request_id = context.user_data["awaiting_request_link"]
        
        # Update request with link
        requests_col.update_one(
            {"_id": request_id},
            {"$set": {"status": "completed", "link": link}}
        )
        
        context.user_data["awaiting_request_link"] = False
        
        await update.message.reply_text(f"✅ Link added for request {request_id}")
        return


# ── Request Movie Command ────────────────────────────────────────────────────

async def request_movie_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /request <movie_name>")
        return
    
    movie_name = " ".join(context.args)
    user_id = update.effective_user.id
    username = update.effective_user.username or "N/A"
    
    # Add request
    add_movie_request(user_id, username, movie_name)
    
    # Notify admins
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id,
                f"""📝 New Movie Request

👤 User: @{username}
🆔 User ID: {user_id}
🎬 Movie: {movie_name}

Use /addlink command to add this movie."""
            )
        except:
            pass
    
    await update.message.reply_text(
        f"✅ Request submitted: {movie_name}\n\n"
        "📋 Admins will review your request."
    )


# ── Status Command ────────────────────────────────────────────────────────────

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ["group", "supergroup"]:
        return
    
    if chat.id != MAIN_GROUP_ID:
        return
    
    user_id = update.effective_user.id
    stats = get_user_stats(user_id)
    
    if not stats:
        await update.message.reply_text("❌ User not found. Start by searching for a movie!")
        return
    
    if stats["is_premium"]:
        status_text = f"""📊 Your Profile

👤 User ID: {user_id}
💎 Plan: {stats['premium_type'].upper()}
📅 Days Left: {stats['days_left']}
🔍 Total Searches: {stats['total_searches']}
✅ Status: Premium Active 🎉"""
    else:
        search_info = get_user_searches_today(user_id)
        remaining = max(0, search_info["limit"] - search_info["count"])
        status_text = f"""📊 Your Profile

👤 User ID: {user_id}
💎 Plan: Free User
🔍 Total Searches: {stats['total_searches']}
📅 Daily Searches Left: {remaining}/{DAILY_FREE_SEARCHES}

🔓 Upgrade to Premium for unlimited searches!
Use /plan to see options."""
    
    await update.message.reply_text(status_text)


# ── Plan Command ─────────────────────────────────────────────────────────────

async def plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        # Forward the message from group
        await context.bot.forward_message(
            chat_id=update.effective_chat.id,
            from_chat_id=PLAN_MESSAGE_GROUP_ID,
            message_id=PLAN_MESSAGE_ID
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


# ── Addlink Command ───────────────────────────────────────────────────────────

async def addlink_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Unauthorized.")
        return
    
    if not context.args:
        await update.message.reply_text(
            "Usage: /addlink <movie_name> <link>\n\n"
            "Example:\n"
            "/addlink Avengers https://terabox.com/s/abc123"
        )
        return
    
    # Check if link is provided
    if len(context.args) < 2:
        await update.message.reply_text("❌ Please provide both movie name and link!")
        return
    
    # Get the link (last argument)
    link = context.args[-1]
    movie_name = " ".join(context.args[:-1])
    
    add_manual_link(movie_name, link)
    
    await update.message.reply_text(
        f"✅ Link added successfully!\n\n"
        f"🎬 Movie: {movie_name}\n"
        f"🔗 Link: {link}"
    )


# ── Post init: runs inside PTB's event loop ───────────────────────────────────

async def post_init(app):
    """Called by PTB after its event loop starts — safe place for async tasks."""
    global cache_task
    print("[Cache] Running startup cleanup...")
    clear_expired_cache()
    clear_expired_image_cache()
    cache_task = asyncio.create_task(auto_clear_cache_loop())

async def shutdown_callback(app):
    """Called when the application is shutting down."""
    global cache_task
    print("[Shutdown] Stopping background tasks...")
    if cache_task and not cache_task.done():
        cache_task.cancel()
        try:
            await cache_task
        except asyncio.CancelledError:
            pass
    print("[Shutdown] Done")


# ── Premium Bot Variables ─────────────────────────────────────────────────────
premium_pending_payments = {}


# ── Premium Bot Handlers ─────────────────────────────────────────────────────

async def premium_start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    
    if not args:
        await update.message.reply_text(
            "👋 Welcome to Premium Payment Bot!\n\n"
            "Please select a plan from the main bot to continue."
        )
        return
    
    # Parse: /start planType_userId
    param = args[0]
    if "_" not in param:
        await update.message.reply_text("❌ Invalid start parameter.")
        return
    
    try:
        plan_type, sender_id = param.rsplit("_", 1)
        sender_id = int(sender_id)
    except:
        await update.message.reply_text("❌ Invalid parameter.")
        return
    
    if plan_type not in PREMIUM_PLANS:
        await update.message.reply_text("❌ Invalid plan type.")
        return
    
    plan = PREMIUM_PLANS[plan_type]
    username = update.effective_user.username or "N/A"
    
    payment_text = f"""📦 {plan['name']} {plan['emoji']}

👤 User: @{username}
🆔 User ID: {sender_id}

💰 Price: {plan['price']}
📅 Duration: {plan['days']} days

━━━━━━━━━━━━━━━
💳 Payment Details:
UPI ID: {UPI_ID}
━━━━━━━━━━━━━━━

📸 After payment, send screenshot here"""

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancel", callback_data="p_cancel")]
    ])
    
    # Send QR if available
    if QR_IMAGE_URL and not QR_IMAGE_URL.startswith("https://example.com"):
        try:
            await update.message.reply_photo(photo=QR_IMAGE_URL, caption=payment_text, reply_markup=keyboard)
        except:
            await update.message.reply_text(payment_text, reply_markup=keyboard)
    else:
        await update.message.reply_text(payment_text, reply_markup=keyboard)
    
    premium_pending_payments[user_id] = {"plan_type": plan_type, "sender_id": sender_id}


async def premium_handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if query.data == "p_cancel":
        if user_id in premium_pending_payments:
            del premium_pending_payments[user_id]
        try:
            await query.delete_message()
        except:
            await query.edit_message_text("❌ Cancelled.")


async def premium_handle_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in premium_pending_payments:
        await update.message.reply_text("❌ No pending payment. Select plan from main bot first.")
        return
    
    payment_info = premium_pending_payments[user_id]
    plan_type = payment_info["plan_type"]
    sender_id = payment_info["sender_id"]
    plan = PREMIUM_PLANS.get(plan_type)
    
    username = update.effective_user.username or "N/A"
    first_name = update.effective_user.first_name or "N/A"
    
    # Forward to main bot admins using the premium bot context
    for admin_id in ADMIN_IDS:
        try:
            # Try to start chat first by sending a test message
            try:
                await context.bot.send_chat_action(admin_id, 'typing')
            except:
                pass
            
            caption = f"""💰 Payment - {plan['name']} {plan['emoji']}

👤 @{username}
🆔 {user_id}
💰 {plan['price']}
📅 {plan['days']} days"""
            
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Approve", callback_data=f"papprove_{sender_id}_{plan_type}_{plan['days']}"),
                 InlineKeyboardButton("❌ Reject", callback_data=f"preject_{sender_id}_{user_id}")]
            ])
            
            if update.message.photo:
                await context.bot.send_photo(
                    chat_id=admin_id, 
                    photo=update.message.photo[-1].file_id,
                    caption=caption,
                    reply_markup=keyboard
                )
            elif update.message.document:
                await context.bot.send_document(
                    chat_id=admin_id,
                    document=update.message.document.file_id,
                    caption=caption,
                    reply_markup=keyboard
                )
            print(f"[Admin Notify] Sent to admin {admin_id}")
        except Exception as e:
            print(f"[Admin Notify Error] {admin_id}: {e}")
    
    await update.message.reply_text("✅ Screenshot sent! ⏰ You'll be notified when verified.")
    del premium_pending_payments[user_id]


async def premium_handle_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    print(f"[DEBUG] Approval callback: {query.data}, User: {user_id}, Admin: {user_id in ADMIN_IDS}")
    
    if user_id not in ADMIN_IDS:
        await query.answer("❌ Unauthorized!", show_alert=True)
        return
    
    data = query.data
    print(f"[DEBUG] Processing: {data}")
    
    if data.startswith("papprove_"):
        try:
            parts = data.split("_")
            target_user_id = int(parts[1])
            plan_type = parts[2]
            days = int(parts[3])
            
            # Grant premium in main bot DB
            expiry = grant_premium(target_user_id, plan_type, days)
            
            # Notify user
            try:
                await context.bot.send_message(
                    target_user_id,
                    f"🎉 Your {plan_type.upper()} plan is activated!\n\n"
                    f"📅 Valid until: {expiry.strftime('%Y-%m-%d')}\n\n"
                    "Enjoy unlimited searches! 🚀"
                )
            except Exception as e:
                print(f"[Notify Error] {e}")
            
            await query.edit_message_text(f"✅ Approved! {plan_type.upper()} granted to {target_user_id}")
        except Exception as e:
            print(f"[Approve Error] {e}")
            await query.answer("❌ Error processing approval!", show_alert=True)
        
    elif data.startswith("preject_"):
        try:
            parts = data.split("_")
            target_user_id = int(parts[1])
            payer_id = int(parts[2])
            
            # Notify payer
            try:
                await context.bot.send_message(
                    payer_id,
                    "❌ Payment rejected. Please try again or contact support."
                )
            except:
                pass
            
            await query.edit_message_text("❌ Payment rejected.")
        except Exception as e:
            print(f"[Reject Error] {e}")
            await query.edit_message_text("❌ Payment rejected.")


# ── Main ──────────────────────────────────────────────────────────────────────

import threading


def run_premium_bot():
    # Create a new event loop for this thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    premium_app = ApplicationBuilder().token(PREMIUM_BOT_TOKEN).build()
    
    premium_app.add_handler(CommandHandler("start", premium_start_command))
    premium_app.add_handler(CallbackQueryHandler(premium_handle_buttons))
    premium_app.add_handler(CallbackQueryHandler(premium_handle_approval, pattern="^(papprove_|preject)"))
    premium_app.add_handler(MessageHandler(filters.PHOTO, premium_handle_screenshot))
    premium_app.add_handler(MessageHandler(filters.Document.ALL, premium_handle_screenshot))
    
    print("💎 Premium Bot running...")
    
    # Use start_polling instead of run_polling to avoid signal handler issues in threads
    async def start():
        await premium_app.initialize()
        await premium_app.start()
        await premium_app.updater.start_polling()
        # Keep the bot running
        while True:
            await asyncio.sleep(3600)
    
    loop.run_until_complete(start())


if __name__ == "__main__":
    print("🔌 Connecting to MongoDB...")
    try:
        mongo.server_info()
        print("✅ MongoDB connected")
    except Exception as e:
        print(f"❌ MongoDB connection failed: {e}")
        exit(1)
    
    # Start premium bot in separate thread
    premium_thread = threading.Thread(target=run_premium_bot, daemon=True)
    premium_thread.start()
    
    # Main bot
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )
    
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("request", request_movie_command))
    app.add_handler(CommandHandler("plan", plan_command))
    app.add_handler(CommandHandler("silver", lambda u, c: grant_premium_command(u, c, "silver")))
    app.add_handler(CommandHandler("gold", lambda u, c: grant_premium_command(u, c, "gold")))
    app.add_handler(CommandHandler("diamond", lambda u, c: grant_premium_command(u, c, "diamond")))
    app.add_handler(CommandHandler("lifetime", lambda u, c: grant_premium_command(u, c, "lifetime")))
    app.add_handler(CommandHandler("admin", lambda u, c: send_admin_panel(u, c)))
    app.add_handler(CommandHandler("addlink", addlink_command))
    app.add_handler(CallbackQueryHandler(handle_buttons))
    app.add_handler(CallbackQueryHandler(handle_payment_approval, pattern="^(approve_|reject_|papprove_)"))
    
    # Chat member handlers for welcome messages - register both types
    app.add_handler(ChatMemberHandler(handle_chat_member_update, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(ChatMemberHandler(handle_chat_member_update, ChatMemberHandler.MY_CHAT_MEMBER))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & (filters.ChatType.GROUP | filters.ChatType.SUPERGROUP), handle_message))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, handle_admin_link_add))
    
    print("🤖 Main Bot running...")
    app.run_polling(allowed_updates=["message", "callback_query", "chat_member", "my_chat_member"])
