import re
import uuid
import logging
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from pymongo import MongoClient

# ================= CONFIG =================
BOT_TOKEN = "5167240865:AAGUNjnYI_GjEES0dbcE2GL4GpHZikWSaI0"
MONGO_URI = "mongodb+srv://Ramanan:Ramanan@cluster0.zl8rb8u.mongodb.net/?appName=Cluster0"
OWNER_ID = 6936341505
LOG_CHANNEL_ID = -1003500086789

# =========================================
logging.basicConfig(level=logging.INFO)

client = MongoClient(MONGO_URI)
db = client["datingbot"]
users = db.users
bans = db.bans

waiting_queue = []

# ================= UTILITIES =================

def main_menu():
    return ReplyKeyboardMarkup(
        [
            ["🔀 Random Chat"],
            ["👨🏻 Find Male", "👧🏻 Find Female"],
            ["📢 Refer & Earn", "🪙 Coins"],
            ["🚫 Unblock Users"]
        ],
        resize_keyboard=True
    )

def chat_menu():
    return ReplyKeyboardMarkup(
        [
            ["⏭️ Next", "❌ Stop Chat"],
            ["🚫 Block & Report"]
        ],
        resize_keyboard=True
    )

def clean_text(text):
    return not re.search(r"(http|https|t\.me|@)", text.lower())

# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if bans.find_one({"user_id": user_id}):
        return

    if not users.find_one({"user_id": user_id}):
        users.insert_one({
            "user_id": user_id,
            "coins": 0,
            "state": "COUNTRY",
            "blocked": [],
            "ref_by": context.args[0][4:] if context.args and context.args[0].startswith("ref_") else None
        })
        await context.bot.send_message(
            LOG_CHANNEL_ID,
            f"🆕 New user started bot\nUser ID: {user_id}"
        )
        await update.message.reply_text("🌍 Select your country:")
        await send_countries(update, context, 0)
    else:
        await update.message.reply_text("Welcome back 👋", reply_markup=main_menu())

# ================= COUNTRY =================

COUNTRIES = ["India", "USA", "UK", "Canada", "Australia", "Germany", "France",
             "Italy", "Spain", "Brazil", "Mexico", "Japan", "China", "Korea"]

async def send_countries(update, context, page):
    buttons = []
    per_page = 6
    start = page * per_page
    for c in COUNTRIES[start:start+per_page]:
        buttons.append([InlineKeyboardButton(c, callback_data=f"country_{c}")])
    nav = []
    if start > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"cpage_{page-1}"))
    if start + per_page < len(COUNTRIES):
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"cpage_{page+1}"))
    if nav:
        buttons.append(nav)

    await update.message.reply_text(
        "Choose your country:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def country_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data.startswith("cpage_"):
        await send_countries(query, context, int(query.data.split("_")[1]))
        return

    country = query.data.split("_", 1)[1]
    users.update_one(
        {"user_id": query.from_user.id},
        {"$set": {"country": country, "state": "NAME"}}
    )
    await query.message.reply_text("✍️ Enter your name:")

# ================= PROFILE STEPS =================

async def profile_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = users.find_one({"user_id": update.effective_user.id})
    state = user.get("state")

    if state == "NAME":
        users.update_one({"user_id": user["user_id"]}, {"$set": {"name": update.message.text, "state": "GENDER"}})
        await update.message.reply_text(
            "Select gender:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Male", callback_data="gender_Male"),
                 InlineKeyboardButton("Female", callback_data="gender_Female")]
            ])
        )

    elif state == "ABOUT":
        if not clean_text(update.message.text):
            await update.message.reply_text("❌ Links are not allowed.")
            return
        users.update_one({"user_id": user["user_id"]}, {"$set": {"about": update.message.text, "state": "PHOTO"}})
        await update.message.reply_text(
            "Upload profile photo or skip:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Skip", callback_data="skip_photo")]])
        )

async def gender_handler(update, context):
    query = update.callback_query
    await query.answer()
    users.update_one(
        {"user_id": query.from_user.id},
        {"$set": {"gender": query.data.split("_")[1], "state": "ABOUT"}}
    )
    await query.message.reply_text(
        "Write about yourself or skip:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Skip", callback_data="skip_about")]])
    )

async def skip_about(update, context):
    query = update.callback_query
    await query.answer()
    users.update_one({"user_id": query.from_user.id}, {"$set": {"state": "PHOTO"}})
    await query.message.reply_text(
        "Upload profile photo or skip:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Skip", callback_data="skip_photo")]])
    )

async def skip_photo(update, context):
    query = update.callback_query
    await query.answer()
    users.update_one({"user_id": query.from_user.id}, {"$set": {"state": "DONE"}})
    await query.message.reply_text("✅ Profile completed!", reply_markup=main_menu())

# ================= CHAT =================

async def random_chat(update, context):
    user_id = update.effective_user.id
    if user_id in waiting_queue:
        return
    waiting_queue.append(user_id)
    await update.message.reply_text("🔍 Searching for partner...", reply_markup=chat_menu())
    await try_match(context)

async def try_match(context):
    if len(waiting_queue) >= 2:
        u1 = waiting_queue.pop(0)
        u2 = waiting_queue.pop(0)
        users.update_one({"user_id": u1}, {"$set": {"chat_with": u2}})
        users.update_one({"user_id": u2}, {"$set": {"chat_with": u1}})
        await send_profile(context, u1, u2)
        await send_profile(context, u2, u1)

async def send_profile(context, sender, receiver):
    u = users.find_one({"user_id": receiver})
    text = f"👤 {u['name']}\n🌍 {u['country']}\n⚧ {u['gender']}"
    if u.get("about"):
        text += f"\n📝 {u['about']}"
    if u.get("photo"):
        await context.bot.send_photo(sender, u["photo"], caption=text)
    else:
        await context.bot.send_message(sender, text)

# ================= MESSAGE RELAY =================

async def relay(update, context):
    user = users.find_one({"user_id": update.effective_user.id})
    partner = user.get("chat_with")
    if partner:
        await context.bot.send_message(partner, update.message.text)

# ================= ADMIN =================

async def stats(update, context):
    if update.effective_user.id == OWNER_ID:
        await update.message.reply_text(f"Total users: {users.count_documents({})}")

# ================= MAIN =================

app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("stats", stats))

app.add_handler(CallbackQueryHandler(country_handler, pattern="^country_|^cpage_"))
app.add_handler(CallbackQueryHandler(gender_handler, pattern="^gender_"))
app.add_handler(CallbackQueryHandler(skip_about, pattern="^skip_about$"))
app.add_handler(CallbackQueryHandler(skip_photo, pattern="^skip_photo$"))

app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, profile_handler))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, relay))

app.run_polling()
