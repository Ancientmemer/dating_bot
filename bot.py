import re
import logging
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from pymongo import MongoClient

# ================= CONFIG =================
BOT_TOKEN = "5167240865:AAEZfAYWp3_OpAvLO39mvtIg9NuJW9rlxy4"
MONGO_URI = "mongodb+srv://Ramanan:Ramanan@cluster0.sibj7v6.mongodb.net/?appName=Cluster0"
OWNER_ID = 6936341505
LOG_CHANNEL_ID = -1003500086789

MATCH_COST = 8
REFERRAL_REWARD = 2

# =========================================
logging.basicConfig(level=logging.INFO)

client = MongoClient(MONGO_URI)
db = client["datingbot"]
users = db.users
bans = db.bans

random_queue, male_queue, female_queue = [], [], []

# ================= UI =================

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

def clean_text(t):
    return not re.search(r"(http|https|t\.me|@)", t.lower())

def remove_from_queues(uid):
    for q in (random_queue, male_queue, female_queue):
        if uid in q:
            q.remove(uid)

# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if bans.find_one({"user_id": uid}):
        return

    user = users.find_one({"user_id": uid})

    if not user:
        ref = None
        if context.args and context.args[0].startswith("ref_"):
            ref = int(context.args[0][4:])

        users.insert_one({
            "user_id": uid,
            "coins": 0,
            "state": "COUNTRY",
            "blocked": [],
            "chat_with": None,
            "ref_by": ref,
            "ref_credited": False
        })

        if ref and users.find_one({"user_id": ref}):
            users.update_one(
                {"user_id": ref},
                {"$inc": {"coins": REFERRAL_REWARD}}
            )

        await context.bot.send_message(
            LOG_CHANNEL_ID,
            f"🆕 New user started\nUser ID: {uid}"
        )

        await update.message.reply_text("🌍 Select your country:")
        await send_countries(update, context, 0)
    else:
        await update.message.reply_text("Welcome back 👋", reply_markup=main_menu())

# ================= COUNTRY =================

COUNTRIES = ["India","USA","UK","Canada","Australia","Germany","France","Italy","Spain","Brazil","Mexico","Japan","China","Korea"]

async def send_countries(update, context, page):
    per_page = 6
    start = page * per_page
    btns = [[InlineKeyboardButton(c, callback_data=f"country_{c}")]
            for c in COUNTRIES[start:start+per_page]]

    nav = []
    if start > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"cpage_{page-1}"))
    if start+per_page < len(COUNTRIES):
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"cpage_{page+1}"))
    if nav:
        btns.append(nav)

    await update.message.reply_text("Choose country:", reply_markup=InlineKeyboardMarkup(btns))

async def country_handler(update, context):
    q = update.callback_query
    await q.answer()

    if q.data.startswith("cpage_"):
        await send_countries(q, context, int(q.data.split("_")[1]))
        return

    users.update_one(
        {"user_id": q.from_user.id},
        {"$set": {"country": q.data.split("_")[1], "state": "NAME"}}
    )
    await q.message.reply_text("✍️ Enter your name:")

# ================= PROFILE =================

async def profile_handler(update, context):
    u = users.find_one({"user_id": update.effective_user.id})
    if not u:
        return

    if u["state"] == "NAME":
        users.update_one({"user_id": u["user_id"]}, {"$set": {"name": update.message.text, "state": "GENDER"}})
        await update.message.reply_text(
            "Select gender:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Male", callback_data="gender_Male"),
                 InlineKeyboardButton("Female", callback_data="gender_Female")]
            ])
        )

    elif u["state"] == "ABOUT":
        if not clean_text(update.message.text):
            await update.message.reply_text("❌ Links not allowed.")
            return
        users.update_one({"user_id": u["user_id"]}, {"$set": {"about": update.message.text, "state": "DONE"}})
        await update.message.reply_text("✅ Profile completed!", reply_markup=main_menu())

async def gender_handler(update, context):
    q = update.callback_query
    await q.answer()
    users.update_one(
        {"user_id": q.from_user.id},
        {"$set": {"gender": q.data.split("_")[1], "state": "ABOUT"}}
    )
    await q.message.reply_text("Write about yourself:")

# ================= MATCHING =================

async def try_match(queue, context):
    if len(queue) < 2:
        return
    a, b = queue.pop(0), queue.pop(0)
    users.update_one({"user_id": a}, {"$set": {"chat_with": b}})
    users.update_one({"user_id": b}, {"$set": {"chat_with": a}})
    await context.bot.send_message(a, "🎉 Connected!", reply_markup=chat_menu())
    await context.bot.send_message(b, "🎉 Connected!", reply_markup=chat_menu())

async def random_chat(update, context):
    uid = update.effective_user.id
    remove_from_queues(uid)
    random_queue.append(uid)
    await update.message.reply_text("🔍 Searching...", reply_markup=chat_menu())
    await try_match(random_queue, context)

async def find_male(update, context):
    uid = update.effective_user.id
    u = users.find_one({"user_id": uid})
    if u["coins"] < MATCH_COST:
        await update.message.reply_text("❌ Not enough coins.")
        return
    users.update_one({"user_id": uid}, {"$inc": {"coins": -MATCH_COST}})
    remove_from_queues(uid)
    male_queue.append(uid)
    await update.message.reply_text("🔍 Searching male...", reply_markup=chat_menu())
    await try_match(male_queue, context)

async def find_female(update, context):
    uid = update.effective_user.id
    u = users.find_one({"user_id": uid})
    if u["coins"] < MATCH_COST:
        await update.message.reply_text("❌ Not enough coins.")
        return
    users.update_one({"user_id": uid}, {"$inc": {"coins": -MATCH_COST}})
    remove_from_queues(uid)
    female_queue.append(uid)
    await update.message.reply_text("🔍 Searching female...", reply_markup=chat_menu())
    await try_match(female_queue, context)

# ================= CHAT CONTROLS =================

async def stop_chat(update, context):
    uid = update.effective_user.id
    u = users.find_one({"user_id": uid})
    partner = u.get("chat_with")
    remove_from_queues(uid)

    if partner:
        users.update_one({"user_id": partner}, {"$set": {"chat_with": None}})
        await context.bot.send_message(partner, "❌ Chat ended.", reply_markup=main_menu())

    users.update_one({"user_id": uid}, {"$set": {"chat_with": None}})
    await update.message.reply_text("❌ Chat stopped.", reply_markup=main_menu())

async def next_chat(update, context):
    await stop_chat(update, context)
    await random_chat(update, context)

async def block_report(update, context):
    uid = update.effective_user.id
    u = users.find_one({"user_id": uid})
    partner = u.get("chat_with")
    if partner:
        users.update_one({"user_id": uid}, {"$addToSet": {"blocked": partner}})
        await stop_chat(update, context)

async def unblock_users(update, context):
    u = users.find_one({"user_id": update.effective_user.id})
    bl = u.get("blocked", [])
    if not bl:
        await update.message.reply_text("🚫 No blocked users.")
        return

    txt = "🚫 Blocked Users:\n"
    for i, uid in enumerate(bl, 1):
        name = users.find_one({"user_id": uid}).get("name", "User")
        txt += f"{i}. {name}\n"
    txt += "\nSend number to unblock."
    users.update_one({"user_id": u["user_id"]}, {"$set": {"state": "UNBLOCK"}})
    await update.message.reply_text(txt)

# ================= ADMIN =================

async def broadcast(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    msg = " ".join(context.args)
    for u in users.find():
        try:
            await context.bot.send_message(u["user_id"], msg)
        except:
            pass

async def ban(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    uid = int(context.args[0])
    bans.insert_one({"user_id": uid})
    await update.message.reply_text("User banned.")

async def unban(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    uid = int(context.args[0])
    bans.delete_one({"user_id": uid})
    await update.message.reply_text("User unbanned.")

# ================= RELAY =================

async def relay(update, context):
    u = users.find_one({"user_id": update.effective_user.id})

    if u.get("state") == "UNBLOCK":
        idx = int(update.message.text) - 1
        blocked = u["blocked"]
        if 0 <= idx < len(blocked):
            blocked.pop(idx)
            users.update_one({"user_id": u["user_id"]}, {"$set": {"blocked": blocked, "state": "DONE"}})
            await update.message.reply_text("✅ User unblocked.", reply_markup=main_menu())
        return

    partner = u.get("chat_with")
    if partner:
        await context.bot.send_message(partner, update.message.text)

# ================= MAIN =================

app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("broadcast", broadcast))
app.add_handler(CommandHandler("ban", ban))
app.add_handler(CommandHandler("unban", unban))

app.add_handler(CallbackQueryHandler(country_handler, pattern="^country_|^cpage_"))
app.add_handler(CallbackQueryHandler(gender_handler, pattern="^gender_"))

app.add_handler(MessageHandler(filters.Regex("^🔀 Random Chat$"), random_chat))
app.add_handler(MessageHandler(filters.Regex("^👨🏻 Find Male$"), find_male))
app.add_handler(MessageHandler(filters.Regex("^👧🏻 Find Female$"), find_female))
app.add_handler(MessageHandler(filters.Regex("^📢 Refer & Earn$"), refer_earn := refer_earn if False else None))
app.add_handler(MessageHandler(filters.Regex("^🪙 Coins$"), coins := coins if False else None))
app.add_handler(MessageHandler(filters.Regex("^⏭️ Next$"), next_chat))
app.add_handler(MessageHandler(filters.Regex("^❌ Stop Chat$"), stop_chat))
app.add_handler(MessageHandler(filters.Regex("^🚫 Block & Report$"), block_report))
app.add_handler(MessageHandler(filters.Regex("^🚫 Unblock Users$"), unblock_users))

app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, profile_handler))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, relay))

app.run_polling()
