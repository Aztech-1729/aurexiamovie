# config.py

BOT_TOKEN = "8786743669:AAGjGPpp4YP7VVqnVl3cQlqIiO6HBNfJiCI"

# Image search settings
IMAGE_SEARCH_ENABLED = True
IMAGE_CACHE_EXPIRY_DAYS = 7

# Max results toh send
MAX_RESULTS = 10

# Tor proxy for DDG rate limit bypass
TOR_PROXY = "socks5://127.0.0.1:9050"

# MongoDB
MONGO_URI = "mongodb+srv://aztech:ayazahmed1122@cluster0.mhuaw3q.mongodb.net/aurexiamovie_db?retryWrites=true&w=majority"

# Auto-clear cache older than this many days (7 = 1 week)
CACHE_EXPIRY_DAYS = 7

# Channel where bot is added as admin
CHANNEL_ID = -1003621021609
CHANNEL_LINK = "https://t.me/aurexia_store"

# Main group where bot works
MAIN_GROUP_ID = -1003518388523
GROUP_LINK = "https://t.me/aurexia_movies"

# Admin IDs
ADMIN_IDS = [8234531267, 6670166083]

# QR Code Image URL (use full Telegram file_id or URL)
QR_IMAGE_URL = "https://i.ibb.co/zTgkHmxy/photo-2026-03-23-10-56-22.jpg"

# UPI Payment ID
UPI_ID = "aurexia-kaushal222@fam"

# Premium Plans
PREMIUM_PLANS = {
    "silver": {
        "name": "SILVER PLAN",
        "emoji": "🥈",
        "days": 60,
        "price": "45 ₹",
        "description": "✔️ 2 MONTHS - 45 ₹🔥"
    },
    "gold": {
        "name": "GOLD PLAN",
        "emoji": "🥇",
        "days": 180,
        "price": "100 ₹",
        "description": "✔️ 6 MONTHS - 100 ₹ 🔥"
    },
    "diamond": {
        "name": "DIAMOND PLAN",
        "emoji": "💎",
        "days": 365,
        "price": "200 ₹",
        "description": "✔️ 12 MONTHS - 200 ₹ 🔥"
    },
    "lifetime": {
        "name": "LIFETIME PLAN",
        "emoji": "😆",
        "days": 36500,
        "price": "500 ₹",
        "description": "✔️ TILL DEATH - 500 ₹ 🔥"
    }
}

# Plans Message
PLANS_MESSAGE = """PLANS WE OFFER⬇️⬇️⬇️
▬▬▬▬▬▬▬▬▬▬▬▬▬
SILVER PLAN 🥈
✔️ 2 MONTHS - 45 ₹🔥
▬▬▬▬▬▬▬▬▬▬▬▬▬
GOLD PLAN 🥇
✔️ 6 MONTHS - 100 ₹ 🔥
▬▬▬▬▬▬▬▬▬▬▬▬▬
DIAMOND PLAN 💎
✔️ 12 MONTHS - 200 ₹ 🔥
▬▬▬▬▬▬▬▬▬▬▬▬▬
LIFETIME PLAN 😆
✔️ TILL DEATH - 500 ₹ 🔥
▬▬▬▬▬▬▬▬▬▬▬▬▬
🔖 DIRECT VIDEO FILES OF BOTH MOVIES / WEBSERIES.
🔖 NO SUCH TERABOX LINK OPENER ISSUE .
🔖 WATCH UNLIMITED CONTENT WITHOUT ADS.
🔖 FAST RESPONSE TIME 24/7 SUPPORT."""

# Daily free search limit
DAILY_FREE_SEARCHES = 3

# Group message ID for /plan command
PLAN_MESSAGE_GROUP_ID = -1003518388523
PLAN_MESSAGE_ID = 347

# Premium Bot Configuration (runs combined with main bot)
PREMIUM_BOT_USERNAME = "Premium_aurabot"
PREMIUM_BOT_TOKEN = "8678251766:AAEBHCqVE9IS6aOv23AERKHnuhnhEME3Nao"
PREMIUM_BOT_ID = 8678251766

# Welcome Message (for new members joining the group)
WELCOME_MESSAGE = """👋 Hey {user_name}!

Hi✋😎🤚
WELCOME TO 🎬
▬▬▬▬▬▬▬▬▬▬
𝐌𝐎𝐕𝐈𝐄𝐒 𝐋𝐎𝐎𝐓𝐄𝐑𝐀 𝐆𝐑𝐎𝐔𝐏 ▬▬▬▬▬▬▬▬▬▬
🔍 FIND YOUR FAVOURITE MOVIES AND WEBSERIES HERE 🚀
▬▬▬▬▬▬▬▬▬▬
🔖 𝙳𝙸𝚁𝙴𝙲𝚃 𝚅𝙸𝙳𝙴𝙾 𝙵𝙸𝙻𝙴𝚂 𝙾𝙵 𝙱𝙾𝚃𝙷 𝙼𝙾𝚅𝙸𝙴𝚂 / 𝚆𝙴𝙱𝚂𝙴𝚁𝙸𝙴𝚂.
🔖 𝙽𝙾 𝚂𝚄𝙲𝙷 𝚃𝙴𝚁𝙰𝙱𝙾𝚇 𝙻𝙸𝙽𝙺 𝙾𝙿𝙴𝙽𝙴𝚁 𝙸𝚂𝚂𝚄𝙴 .
🔖 𝚆𝙰𝚃𝙲𝙷 𝚄𝙽𝙻𝙸𝙼𝙸𝚃𝙴𝙳 𝙲𝙾𝙽𝚃𝙴𝙽𝚃 𝚆𝙸𝚃𝙷𝙾𝚄𝚃 𝙰𝙳𝚂.
🔖 𝙵𝙰𝚂𝚃 𝚁𝙴𝚂𝙿𝙾𝙽𝚂𝙴 𝚃𝙸𝙼𝙴 𝟸𝟺/𝟽 𝚂𝚄𝙿𝙿𝙾𝚁𝚃.
▬▬▬▬▬▬▬▬▬▬
🔍 HOW IT WORKS :
1.𝙹𝙾𝙸𝙽 𝙾𝚄𝚁 𝙾𝙵𝙵𝙸𝙲𝙸𝙰𝙻 𝙶𝚁𝙾𝚄𝙿
👉 @aurexia_movies
2. 𝚂𝙴𝙽𝙳 𝙰𝙽𝚈 𝙼𝙾𝚅𝙸𝙴𝚂 𝙾𝚁 𝚂𝙴𝚁𝙸𝙴𝚂 𝙽𝙰𝙼𝙴 🎥
3. 𝙶𝙴𝚃 𝚆𝙾𝚁𝙺𝙸𝙽𝙶 𝙻𝙸𝙽𝙺𝚂 𝙸𝙽𝚂𝚃𝙰𝙽𝚃𝙻𝚈 ⚡
4. 𝙴𝙽𝙹𝙾𝚈 𝚄𝙽𝙻𝙸𝙼𝙸𝚃𝙴𝙳 𝙴𝙽𝚃𝙴𝚁𝚃𝙰𝙸𝙽𝙼𝙴𝙽𝚃 🍿✨🔥
▬▬▬▬▬▬▬▬▬▬
📢 OUR OFFICIAL CHANNEL:
👉 @Aurexia_Store

👑 OWNER : 
👉 @Kcs320"""
