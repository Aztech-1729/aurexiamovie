# bot.py

import time
import asyncio
import threading
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
    IMAGE_CACHE_EXPIRY_DAYS, WELCOME_MESSAGE, FREE_LIMIT_MESSAGE,
    FILE_MANAGER_BOT_TOKEN, FILE_MANAGER_BOT_USERNAME
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

def build_keyboard(results: list, page: int, query: str = None) -> InlineKeyboardMarkup:
    keyboard = []
    
    # Show only "Click Here" button in group - results shown in File Manager bot
    if query:
        keyboard.append([InlineKeyboardButton("📥 Click Here to Open in Bot", url=f"https://t.me/{FILE_MANAGER_BOT_USERNAME}?start={query.replace(' ', '_')}")])

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

    # Check daily search limit for free users (admins have unlimited)
    if user_id not in ADMIN_IDS:
        if not search_info["is_premium"]:
            if search_info["count"] >= search_info["limit"]:
                username = update.effective_user.username or update.effective_user.first_name
                limit_message = FREE_LIMIT_MESSAGE.format(
                    username=username,
                    limit=search_info["limit"]
                )
                await update.message.reply_text(
                    limit_message,
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
        
        # Search for movie image
        image_url = await loop.run_in_executor(None, search_movie_image, query)
        response_text = f"🎬 Found *{len(results)}* result(s) for: `{query}`"
        
        print(f"[Debug] Results length: {len(results)}")
        if len(results) > 0:
            print(f"[Debug] First result: {results[0]}")
        
        # Delete loading message
        await msg.delete()
        
        # Build keyboard properly
        keyboard_markup = build_keyboard(results, 0, query)
        
        # Send photo with inline keyboard
        if image_url:
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=image_url,
                caption=response_text,
                reply_markup=keyboard_markup,
                parse_mode="Markdown"
            )
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=response_text,
                reply_markup=keyboard_markup,
                parse_mode="Markdown"
            )
    except Exception as e:
        print(f"[Error] {e}")
        await msg.edit_text("⚠️ Error")


# ── Callback Query Handler ───────────────────────────────────────────────────

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    # Handle movie request
    if data.startswith("request_movie_"):
        parts = data.split("_")
        movie_name = "_".join(parts[2:-1])
        request_user_id = int(parts[-1])
        
        if user_id != request_user_id:
            await query.edit_message_text("⚠️ You can only request movies for yourself.")
            return
        
        add_movie_request(user_id, query.from_user.username or "unknown", movie_name)
        await query.edit_message_text(f"✅ Movie request submitted: {movie_name}\n\nWe'll notify you when it's added!")
        return
    
    # Handle verify join
    if data == "verify_join":
        try:
            member = await context.bot.get_chat_member(CHANNEL_ID, user_id)
            if member.status in ["left", "kicked"]:
                await query.edit_message_text("⚠️ Please join the channel first!")
            else:
                await query.edit_message_text("✅ Verified! You can now use the bot.")
        except Exception as e:
            print(f"[Verify Error] {e}")
            await query.edit_message_text("⚠️ Error verifying membership.")
        return
    
    # Handle admin panel
    if user_id in ADMIN_IDS:
        if data == "admin_stats":
            all_users = get_all_users()
            premium_users = get_premium_users()
            total_searches = sum(u.get("total_searches", 0) for u in all_users)
            
            stats_text = (
                "📊 *Bot Statistics*\n\n"
                f"👥 Total Users: {len(all_users)}\n"
                f"⭐ Premium Users: {len(premium_users)}\n"
                f"🔍 Total Searches: {total_searches}\n"
            )
            await query.edit_message_text(stats_text, reply_markup=build_admin_panel_keyboard(), parse_mode="Markdown")
            return
        
        if data == "admin_premium_users":
            premium_users = get_premium_users()
            if not premium_users:
                text = "👥 No premium users found."
            else:
                text = "👥 *Premium Users*\n\n"
                for user in premium_users[:10]:  # Show first 10
                    expiry = user.get("premium_expires", "Lifetime")
                    text += f"• ID: {user['user_id']} | {user.get('premium_type', 'Unknown')} | {expiry}\n"
                if len(premium_users) > 10:
                    text += f"\n... and {len(premium_users) - 10} more"
            
            await query.edit_message_text(text, reply_markup=build_admin_panel_keyboard(), parse_mode="Markdown")
            return
        
        if data == "admin_add_link":
            user_sessions[user_id] = {"state": "adding_link"}
            await query.edit_message_text("➕ Send the movie name and link in format:\n`movie_name|link`", reply_markup=build_admin_panel_keyboard(), parse_mode="Markdown")
            return
        
        if data == "admin_view_requests":
            pending = get_pending_requests()
            if not pending:
                text = "📋 No pending requests."
            else:
                text = "📋 *Pending Requests*\n\n"
                for req in pending[:10]:
                    text += f"• {req.get('movie_name', 'Unknown')} by {req.get('username', 'Unknown')} (ID: {req['user_id']})\n"
                if len(pending) > 10:
                    text += f"\n... and {len(pending) - 10} more"
            
            await query.edit_message_text(text, reply_markup=build_admin_panel_keyboard(), parse_mode="Markdown")
            return
        
        if data == "admin_all_links":
            links = get_all_manual_links()
            if not links:
                text = "🔗 No manual links found."
            else:
                text = "🔗 *Manual Links*\n\n"
                for link in links[:10]:
                    text += f"• {link.get('query', 'Unknown')}: {link.get('link', 'No link')[:50]}...\n"
                if len(links) > 10:
                    text += f"\n... and {len(links) - 10} more"
            
            await query.edit_message_text(text, reply_markup=build_admin_panel_keyboard(), parse_mode="Markdown")
            return
        
        if data == "admin_close":
            await query.edit_message_text("🔙 Admin panel closed.")
            return


# ── Admin Commands ───────────────────────────────────────────────────────────

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⚠️ You don't have permission to use this command.")
        return
    
    await update.message.reply_text("🔧 *Admin Panel*", reply_markup=build_admin_panel_keyboard(), parse_mode="Markdown")


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⚠️ You don't have permission to use this command.")
        return
    
    all_users = get_all_users()
    premium_users = get_premium_users()
    total_searches = sum(u.get("total_searches", 0) for u in all_users)
    
    stats_text = (
        "📊 *Bot Statistics*\n\n"
        f"👥 Total Users: {len(all_users)}\n"
        f"⭐ Premium Users: {len(premium_users)}\n"
        f"🔍 Total Searches: {total_searches}\n"
    )
    await update.message.reply_text(stats_text, parse_mode="Markdown")


async def add_link_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⚠️ You don't have permission to use this command.")
        return
    
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /addlink <movie_name> <link>")
        return
    
    movie_name = " ".join(context.args[:-1])
    link = context.args[-1]
    
    add_manual_link(movie_name, link)
    await update.message.reply_text(f"✅ Added manual link for: {movie_name}")


async def delete_link_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⚠️ You don't have permission to use this command.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /deletelink <movie_name>")
        return
    
    movie_name = " ".join(context.args)
    delete_manual_link(movie_name)
    await update.message.reply_text(f"✅ Deleted link for: {movie_name}")


async def clear_cache_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⚠️ You don't have permission to use this command.")
        return
    
    clear_expired_cache()
    await update.message.reply_text("✅ Cache cleared!")


# ── File Manager Bot Handlers ───────────────────────────────────────────────────

fm_user_sessions = {}

async def fm_start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command in file manager bot"""
    user_id = update.effective_user.id
    
    # Check if there's a query parameter
    if context.args:
        query = " ".join(context.args).replace("_", " ")
        print(f"[File Manager] User {user_id} searching for: {query}")
        
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
                    [InlineKeyboardButton("✅ Verified", callback_data="fm_verify_join")]
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

        # Check daily search limit for free users (admins have unlimited)
        if user_id not in ADMIN_IDS:
            if not search_info["is_premium"]:
                if search_info["count"] >= search_info["limit"]:
                    username = update.effective_user.username or update.effective_user.first_name
                    limit_message = FREE_LIMIT_MESSAGE.format(
                        username=username,
                        limit=search_info["limit"]
                    )
                    await update.message.reply_text(
                        limit_message,
                        reply_markup=build_plan_keyboard(user_id)
                    )
                    return
        
        msg = await update.message.reply_text("🔎 Searching...")
        
        try:
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(None, do_search, query.lower())
            
            if not results:
                keyboard = [
                    [InlineKeyboardButton("📝 Request This Movie", callback_data=f"fm_request_{query}_{user_id}")]
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
            
            fm_user_sessions[user_id] = {"results": results, "page": 0, "query": query}
            
            # Search for movie image
            image_url = await loop.run_in_executor(None, search_movie_image, query)
            
            # Build results keyboard
            keyboard = build_results_keyboard(results, 0)
            
            response_text = f"🎬 Found *{len(results)}* result(s) for: `{query}`"
            
            print(f"[File Manager] Results length: {len(results)}")
            
            # Delete loading message
            await msg.delete()
            
            # Send photo with inline keyboard
            if image_url:
                await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=image_url,
                    caption=response_text,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            else:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=response_text,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
        except Exception as e:
            print(f"[File Manager Error] {e}")
            await msg.edit_text("⚠️ Error searching for movie.")
    else:
        # No query parameter, show welcome message
        welcome_text = (
            "🎬 *Movie Search Bot*\n\n"
            "👋 Welcome! Search for movies by sending the movie name.\n\n"
            "📌 *Features:*\n"
            "• Search movies on TeraBox\n"
            "• Get direct download links\n"
            "• Premium plans available\n\n"
            "🔍 *Usage:*\n"
            "• In group: Just type the movie name\n"
                    "• In this bot: Use /start <movie_name>\n\n"
            "⭐ *Premium:*\n"
            "• Unlimited searches\n"
            "• Faster results\n\n"
            f"📢 Channel: {CHANNEL_LINK}"
        )
        await update.message.reply_text(welcome_text, parse_mode="Markdown")


def build_results_keyboard(results: list, page: int) -> InlineKeyboardMarkup:
    """Build keyboard with result buttons that directly open TeraBox links"""
    keyboard = []
    
    # Add result buttons (max 5 per page)
    results_per_page = 5
    start_idx = page * results_per_page
    end_idx = min(start_idx + results_per_page, len(results))
    
    for i in range(start_idx, end_idx):
        result = results[i]
        title = clean_title(result["title"])
        link = result["link"]
        # Truncate title if too long
        if len(title) > 40:
            title = title[:37] + "..."
        keyboard.append([InlineKeyboardButton(f"📥 {i+1}. {title}", url=link)])
    
    # Add navigation buttons if there are more results
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data="fm_prev"))
    if end_idx < len(results):
        nav_row.append(InlineKeyboardButton("Next ➡️", callback_data="fm_next"))
    if nav_row:
        keyboard.append(nav_row)
    
    return InlineKeyboardMarkup(keyboard)


async def fm_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback queries in file manager bot"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    # Handle verify join
    if data == "fm_verify_join":
        try:
            member = await context.bot.get_chat_member(CHANNEL_ID, user_id)
            if member.status in ["left", "kicked"]:
                await query.edit_message_text("⚠️ Please join the channel first!")
            else:
                await query.edit_message_text("✅ Verified! You can now use the bot.")
        except Exception as e:
            print(f"[Verify Error] {e}")
            await query.edit_message_text("⚠️ Error verifying membership.")
        return
    
    # Handle movie request
    if data.startswith("fm_request_"):
        parts = data.split("_")
        movie_name = "_".join(parts[2:-1])
        request_user_id = int(parts[-1])
        
        if user_id != request_user_id:
            await query.edit_message_text("⚠️ You can only request movies for yourself.")
            return
        
        add_movie_request(user_id, query.from_user.username or "unknown", movie_name)
        await query.edit_message_text(f"✅ Movie request submitted: {movie_name}\n\nWe'll notify you when it's added!")
        return
    
    # Handle navigation
    if data == "fm_next":
        if user_id in fm_user_sessions:
            session = fm_user_sessions[user_id]
            session["page"] += 1
            keyboard = build_results_keyboard(session["results"], session["page"])
            await query.edit_message_reply_markup(reply_markup=keyboard)
        return
    
    if data == "fm_prev":
        if user_id in fm_user_sessions:
            session = fm_user_sessions[user_id]
            if session["page"] > 0:
                session["page"] -= 1
            keyboard = build_results_keyboard(session["results"], session["page"])
            await query.edit_message_reply_markup(reply_markup=keyboard)
        return


# ── Main ─────────────────────────────────────────────────────────────────────

import threading

def run_file_manager_bot():
    """Run the file manager bot in a separate thread"""
    try:
        fm_app = ApplicationBuilder().token(FILE_MANAGER_BOT_TOKEN).build()
        
        # Add handlers for file manager bot
        fm_app.add_handler(CommandHandler("start", fm_start_command))
        fm_app.add_handler(CallbackQueryHandler(fm_callback_handler))
        
        print("📁 File Manager Bot running...", flush=True)
        fm_app.run_polling(allowed_updates=["message", "callback_query"])
    except Exception as e:
        print(f"[File Manager Bot Error] {e}", flush=True)


def run_main_bot():
    """Run the main movie search bot"""
    try:
        app = ApplicationBuilder().token(BOT_TOKEN).build()
        
        # Message handler for movie search
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        # Callback query handler
        app.add_handler(CallbackQueryHandler(handle_callback_query))
        
        # Chat member handler for welcome messages
        app.add_handler(ChatMemberHandler(handle_chat_member_update, ChatMemberHandler.CHAT_MEMBER))
        
        # Admin commands
        app.add_handler(CommandHandler("admin", admin_command))
        app.add_handler(CommandHandler("stats", stats_command))
        app.add_handler(CommandHandler("addlink", add_link_command))
        app.add_handler(CommandHandler("deletelink", delete_link_command))
        app.add_handler(CommandHandler("clearcache", clear_cache_command))
        
        print("🎬 Movie Search Bot running...", flush=True)
        app.run_polling(allowed_updates=["message", "callback_query", "chat_member", "my_chat_member"])
    except Exception as e:
        print(f"[Main Bot Error] {e}", flush=True)


def main():
    """Main entry point - run both bots in separate threads"""
    print("🚀 Starting bots...", flush=True)
    
    # Start file manager bot in a separate thread
    fm_thread = threading.Thread(target=run_file_manager_bot, daemon=True)
    fm_thread.start()
    print("✅ File Manager Bot thread started", flush=True)
    
    # Run main bot in the main thread
    print("🎯 Starting Main Bot...", flush=True)
    run_main_bot()


if __name__ == "__main__":
    main()
