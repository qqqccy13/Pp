#!/usr/bin/env python3
import logging
import asyncio
import datetime
import os
import json
import sqlite3
import random
import string
import nest_asyncio
import requests
import re
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
import telegram.error
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler,
    ConversationHandler,
)

nest_asyncio.apply()

# =====================================================================
# Logging Configuration
# =====================================================================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# =====================================================================
# Global Configuration Variables
# =====================================================================
ADMIN_ID = 8109736174                  # Admin's numeric ID
CUSTOM_AMOUNT = 1
MANDATORY_CHANNEL = "@food_center_Channel"  # First mandatory channel
MANDATORY_CHANNEL_2 = "@Zerocode_TM"          # Second mandatory channel

# Global modifiable product prices dictionary with an initial product.
PRODUCT_PRICES = {"🍔کد 170/300 اسنپ فود🍕": 30000}

# =====================================================================
# Conversation States for User and Admin Tasks
# =====================================================================
ADMIN_BROADCAST_MESSAGE = 90
ADMIN_ADD_AMOUNT = 10
ADMIN_ADD_USERID = 11
ADMIN_SUB_AMOUNT = 20
ADMIN_SUB_USERID = 21
ADMIN_UNBLOCK_USERID = 30
ADMIN_BAN_USERID = 40
ADMIN_MESSAGE_USERID = 50
ADMIN_MESSAGE_TEXT = 51
ADMIN_BALANCE_USERID = 60
ADMIN_RECENT_PURCHASES_USERID = 70
ADD_CODE_SERVICE = 80
ADD_CODE_FILEPATH = 81
CHARGE_CUSTOM_INPUT = 200
ADD_BUTTON_NAME = 300
ADD_BUTTON_PRICE = 301
REMOVE_BUTTON_SELECT = 310
INCREASE_PRODUCT_SELECT = 400
INCREASE_PRODUCT_INPUT = 401
DECREASE_PRODUCT_SELECT = 500
DECREASE_PRODUCT_INPUT = 501
ADMIN_DELETE_CODE_SERVICE = 600
ADMIN_DELETE_CODE_INPUT = 601
GIFT_CODE_INPUT = 1000

# New states for Gift Creation with new capability (manual & random)
ADMIN_CREATE_GIFT_AMOUNT = 700
ADMIN_CREATE_GIFT_USAGE = 701
ADMIN_GIFT_CHOICE = 702
RANDOM_WINNER_COUNT = 710
RANDOM_CREDIT_AMOUNT = 711

# State for user search conversation
SEARCH_USER_INPUT = 1100

# Added constant for admin forward message conversation
ADMIN_FORWARD_MESSAGE = 800

# NEW: States for Renaming Button Capability (do not remove any line)
RENAME_BUTTON_SELECT = 320
RENAME_BUTTON_INPUT = 321

# NEW: States for TRX Payment Flow (New Feature - do not reduce any lines)
TRX_PAYMENT_MENU = 1500
TRX_CUSTOM_INPUT = 1501

# =====================================================================
# Global Dictionaries and Sets for Data Storage
# =====================================================================
USER_BALANCES = {}                     # user_id -> current balance
USER_CHARGED = {}                      # user_id -> total charged amount
USER_PURCHASED = {}                    # user_id -> total purchased count
USER_RECENT_PURCHASES = {}             # user_id -> list of tuples (timestamp, product)
BANNED_USERS = {}                      # user_id -> True if banned (همچنین در دیتابیس ذخیره می‌شود)
SERVICE_CODES = {}                     # product name -> list of available codes
SERVICE_FILE_PATH = {}                 # product name -> file path
REGISTERED_USERS = set()               # Users who started the bot (for broadcast)
BOT_ACTIVE = True                      # Global bot status
gift_codes = {}                        # Gift codes dictionary

# New globals to track gift code usage per user
USER_GIFT_USAGE = {}                   # user_id -> number of times gift code redeemed
USER_LAST_GIFT_CODE = {}               # user_id -> last gift code redeemed

# Global dictionary for storing user info (username)
USER_INFO = {}                         # user_id -> username

# New global to track charge transactions: list of tuples (timestamp, user_id, amount)
charge_history = []

# =====================================================================
# Database Functions using SQLite
# =====================================================================
db = None

def init_db():
    global db
    db = sqlite3.connect("user_data.db", check_same_thread=False)
    cursor = db.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER,
            charged INTEGER,
            purchased INTEGER,
            recent_purchases TEXT
        )
    """)
    # NEW: Create table for banned users
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS banned_users (
            user_id INTEGER PRIMARY KEY
        )
    """)
    db.commit()

def load_user_data():
    global USER_BALANCES, USER_CHARGED, USER_PURCHASED, USER_RECENT_PURCHASES
    cursor = db.cursor()
    cursor.execute("SELECT user_id, balance, charged, purchased, recent_purchases FROM users")
    rows = cursor.fetchall()
    for row in rows:
        user_id, balance, charged, purchased, recent_purchases_text = row
        USER_BALANCES[user_id] = balance
        USER_CHARGED[user_id] = charged
        USER_PURCHASED[user_id] = purchased
        try:
            USER_RECENT_PURCHASES[user_id] = json.loads(recent_purchases_text) if recent_purchases_text else []
        except Exception:
            USER_RECENT_PURCHASES[user_id] = []

def save_all_user_data():
    cursor = db.cursor()
    for user_id in USER_BALANCES.keys():
        balance = USER_BALANCES.get(user_id, 0)
        charged = USER_CHARGED.get(user_id, 0)
        purchased = USER_PURCHASED.get(user_id, 0)
        recent_purchases = USER_RECENT_PURCHASES.get(user_id, [])
        recent_purchases_str = json.dumps(recent_purchases, ensure_ascii=False)
        cursor.execute(
            "INSERT OR REPLACE INTO users (user_id, balance, charged, purchased, recent_purchases) VALUES (?, ?, ?, ?, ?)",
            (user_id, balance, charged, purchased, recent_purchases_str)
        )
    db.commit()

# NEW: Database utility functions for banned users
def load_banned_users():
    global BANNED_USERS
    cursor = db.cursor()
    cursor.execute("SELECT user_id FROM banned_users")
    rows = cursor.fetchall()
    for (user_id,) in rows:
        BANNED_USERS[user_id] = True

def add_banned_user(user_id: int):
    cursor = db.cursor()
    cursor.execute("INSERT OR IGNORE INTO banned_users (user_id) VALUES (?)", (user_id,))
    db.commit()
    BANNED_USERS[user_id] = True

def remove_banned_user(user_id: int):
    cursor = db.cursor()
    cursor.execute("DELETE FROM banned_users WHERE user_id = ?", (user_id,))
    db.commit()
    if user_id in BANNED_USERS:
        del BANNED_USERS[user_id]

def get_banned_users(offset: int, limit: int = 10):
    cursor = db.cursor()
    cursor.execute("SELECT user_id FROM banned_users ORDER BY user_id LIMIT ? OFFSET ?", (limit, offset))
    rows = cursor.fetchall()
    return [row[0] for row in rows]

def count_banned_users():
    cursor = db.cursor()
    cursor.execute("SELECT COUNT(*) FROM banned_users")
    (count,) = cursor.fetchone()
    return count

# =====================================================================
# Persistence Functions for Registered Users and User TXT file
# =====================================================================
def load_registered_users():
    global REGISTERED_USERS
    if os.path.exists("registered_users.txt"):
        with open("registered_users.txt", "r", encoding="utf-8") as f:
            for line in f:
                uid_line = line.strip()
                if uid_line:
                    try:
                        uid = int(uid_line)
                        REGISTERED_USERS.add(uid)
                    except ValueError:
                        continue

def save_registered_user(uid):
    if uid not in REGISTERED_USERS:
        with open("registered_users.txt", "a", encoding="utf-8") as f:
            f.write(str(uid) + "\n")
        REGISTERED_USERS.add(uid)

def write_users_txt():
    """Write all users info into user.txt in the format:
    user_id - username - balance"""
    with open("user.txt", "w", encoding="utf-8") as f:
        for uid in REGISTERED_USERS:
            username = USER_INFO.get(uid, "نامشخص")
            balance = USER_BALANCES.get(uid, 0)
            f.write(f"{uid} - {username} - {balance}\n")

# =====================================================================
# Helper Functions for Keyboards
# =====================================================================
def get_main_menu_keyboard():
    keyboard = [
        [KeyboardButton("خرید محصول 🛍")],
        [KeyboardButton("👤 حساب کاربری"), KeyboardButton("شارژ حساب 💳")],
        [KeyboardButton("پشتیبانی 👨‍💻"), KeyboardButton("📣 کانال های ما")],
        [KeyboardButton("🎁کد هدیه🎁")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_inline_main_menu():
    inline_keyboard = [
        [InlineKeyboardButton("منوی اصلی 🏠", callback_data="menu_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard)

def get_admin_panel_keyboard():
    keyboard = [
        [InlineKeyboardButton("➕افزودن اعتبار کاربر", callback_data="admin_add_credit"),
         InlineKeyboardButton("➖کم کردن اعتبار کاربر", callback_data="admin_subtract_credit")],
        [InlineKeyboardButton("🟢آزاد کردن کاربر", callback_data="admin_unblock"),
         InlineKeyboardButton("🔴بن کردن کاربر", callback_data="admin_ban")],
        [InlineKeyboardButton("📥پیام به کاربر", callback_data="admin_message")],
        [InlineKeyboardButton("💰 موجودی کاربر", callback_data="admin_balance")],
        [InlineKeyboardButton("🛍خرید های اخیر کاربر", callback_data="admin_recent_purchases")],
        [InlineKeyboardButton("🎫افزودن کد", callback_data="admin_add_code")],
        [InlineKeyboardButton("🗑حذف کد تخفیف", callback_data="admin_delete_code")],
        [InlineKeyboardButton("📧ارسال پیام همگانی", callback_data="admin_broadcast")],
        [InlineKeyboardButton("📤فوروارد همگانی", callback_data="admin_forward")],
        [InlineKeyboardButton("➕افزودن دکمه", callback_data="admin_add_button"),
         InlineKeyboardButton("➖کم کردن دکلمه", callback_data="admin_remove_button")],
        [InlineKeyboardButton("تغییر نام دکمه✏️", callback_data="admin_rename_button")],
        [InlineKeyboardButton("💵کم کردن قیمت ها", callback_data="admin_decrease_price"),
         InlineKeyboardButton("🪙بالا بردن قیمت ها", callback_data="admin_increase_price")],
        [InlineKeyboardButton("🟢روشن کردن ربات", callback_data="admin_turn_on_bot"),
         InlineKeyboardButton("🔴خاموش کردن ربات", callback_data="admin_turn_off_bot")],
        [InlineKeyboardButton("📊آمار", callback_data="admin_stats")],
        [InlineKeyboardButton("🎁ساخت کد هدیه", callback_data="admin_create_gift")],
        [InlineKeyboardButton("👤فایل txt کاربران", callback_data="admin_users_txt")],
        [InlineKeyboardButton("☎️فایل شماره ی کاربران", callback_data="admin_phone_file")],
        [InlineKeyboardButton("💾بکاپ دیتابیس", callback_data="admin_backup_db")],
        # NEW: Button for showing banned users list
        [InlineKeyboardButton("📊لیست کاربران مسدود شده", callback_data="admin_banned_list_0")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_charge_keyboard():
    keyboard = [
        [InlineKeyboardButton("10000", callback_data="charge_10000"),
         InlineKeyboardButton("20000", callback_data="charge_20000")],
        [InlineKeyboardButton("50000", callback_data="charge_50000"),
         InlineKeyboardButton("مبلغ دلخواه", callback_data="charge_custom")],
        [InlineKeyboardButton("منوی اصلی 🏠", callback_data="menu_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_user_profile_keyboard():
    keyboard = [
        [InlineKeyboardButton("شارژ حساب 💳", callback_data="profile_charge")],
        [InlineKeyboardButton("منوی اصلی 🏠", callback_data="menu_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_product_purchase_keyboard():
    buttons = []
    for product in PRODUCT_PRICES.keys():
        buttons.append([InlineKeyboardButton(product, callback_data=f"buy_{product}")])
    buttons.append([InlineKeyboardButton("منوی اصلی 🏠", callback_data="menu_main")])
    return InlineKeyboardMarkup(buttons)

# ---------------------------------------------------------------------
# Updated: Helper Function for Membership Keyboard with Three Inline Buttons
# ---------------------------------------------------------------------
def get_membership_keyboard():
    # Three inline buttons (glass style) each on a separate row.
    keyboard = [
        [InlineKeyboardButton("food center | کد تخفیف اسنپ فود", url="https://t.me/food_center_Channel")],
        [InlineKeyboardButton("𝗭𝗘𝗥𝗢𝗖𝗢𝗗𝗘™ | کد تخفیف", url="https://t.me/Zerocode_TM")],
        [InlineKeyboardButton("تایید عضویت ✅", callback_data="confirm_membership")]
    ]
    return InlineKeyboardMarkup(keyboard)

# New helper: Cancel keyboard for admin conversations
def get_admin_cancel_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("انصراف❌", callback_data="admin_cancel")]])

# NEW: Helper function for Payment Method selection (New Feature)
def get_payment_method_keyboard():
    keyboard = [
        [InlineKeyboardButton("کارت به کارت 💳", callback_data="card_payment")],
        [InlineKeyboardButton("پرداخت ارزی 💵", callback_data="crypto_payment")]
    ]
    return InlineKeyboardMarkup(keyboard)

# NEW: Helper function for TRX Payment initiation button
def get_trx_initial_keyboard():
    keyboard = [[InlineKeyboardButton("پرداخت با Trx(ترون)🔴", callback_data="trx_payment")]]
    return InlineKeyboardMarkup(keyboard)

# NEW: Helper function for TRX Payment Options (Fixed amounts and Custom)
def get_trx_option_keyboard():
    keyboard = [
       [InlineKeyboardButton("10000", callback_data="trx_10000")],
       [InlineKeyboardButton("20000", callback_data="trx_20000")],
       [InlineKeyboardButton("30000", callback_data="trx_30000")],
       [InlineKeyboardButton("50000", callback_data="trx_50000")],
       [InlineKeyboardButton("مبلغ دلخواه", callback_data="trx_custom")]
    ]
    return InlineKeyboardMarkup(keyboard)

# =====================================================================
# Membership Check Functions
# =====================================================================
async def check_membership(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    missing_channel = None
    # Check both mandatory channels. If any one is missing, prompt the user.
    for channel in [MANDATORY_CHANNEL, MANDATORY_CHANNEL_2]:
        try:
            member = await context.bot.get_chat_member(channel, user_id)
            if member.status not in ["member", "administrator", "creator"]:
                missing_channel = channel
                break
        except Exception as e:
            logger.error(f"Error checking channel {channel} for user {user_id}: {e}")
            missing_channel = channel
            break

    if missing_channel:
        user_first_name = update.effective_user.first_name
        text = f"کاربر {user_first_name} لطفا در کانال زیر عضو شید و سپس از ربات استفاده کنید✅"
        # Construct the link based on the channel string (assumes channel starts with '@')
        if missing_channel.startswith('@'):
            link = f"https://t.me/{missing_channel[1:]}"
        else:
            link = missing_channel
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(missing_channel, url=link)]])
        if update.message:
            await update.message.reply_text(text, reply_markup=keyboard)
        elif update.callback_query:
            try:
                await update.callback_query.edit_message_text(text, reply_markup=keyboard)
            except telegram.error.BadRequest as e_edit:
                logger.error(f"Error editing membership message: {e_edit}")
                await context.bot.send_message(chat_id=user_id, text=text, reply_markup=keyboard)
        return False
    return True

# New Callback Handler for Confirming Membership in Both Channels (using get_membership_keyboard)
async def confirm_membership_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    # After confirmation, check membership for both channels
    if await check_membership(update, context):
        try:
            await query.edit_message_text("عضویت شما تایید شد. خوش آمدید!", reply_markup=get_main_menu_keyboard())
        except telegram.error.BadRequest as e:
            logger.error(f"Error editing confirmation message: {e}")
            await context.bot.send_message(chat_id=query.from_user.id, text="عضویت شما تایید شد. خوش آمدید!", reply_markup=get_main_menu_keyboard())

async def membership_check_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if await check_membership(update, context):
        try:
            await query.edit_message_text("عضویت شما تایید شد. خوش آمدید!", reply_markup=get_main_menu_keyboard())
        except telegram.error.BadRequest as e:
            logger.error(f"Error editing message: {e}")
            await context.bot.send_message(
                chat_id=query.from_user.id,
                text="عضویت شما تایید شد. خوش آمدید!",
                reply_markup=get_main_menu_keyboard()
            )
    else:
        user_first_name = update.effective_user.first_name
        text = f"👤کاربر {user_first_name} جهت استفاده از ربات باید در کانال زیر عضو باشید✅"
        try:
            await query.edit_message_text(text, reply_markup=get_membership_keyboard())
        except telegram.error.BadRequest as e:
            logger.error(f"Error editing membership reminder: {e}")
            await context.bot.send_message(
                chat_id=query.from_user.id,
                text=text,
                reply_markup=get_membership_keyboard()
            )

# =====================================================================
# New: Contact Handler for Card-to-Card Payment (Phone Sharing capability)
# =====================================================================
async def contact_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    contact = update.message.contact
    if not contact:
        return
    phone = contact.phone_number.strip()
    # Check for valid Iranian phone starting with "98" or "+98"
    if phone.startswith("+98") or phone.startswith("98"):
        try:
            with open("phone.txt", "a", encoding="utf-8") as f:
                f.write(f"USER : {user.id} | Phone : {phone}\n")
        except Exception as e:
            logger.error(f"خطا در ذخیره فایل phone.txt: {e}")
        await update.message.reply_text(
            f"شماره ی {phone} ثبت شد ! هم اکنون میتوانید حساب خود را شارژ کنید ✅",
            reply_markup=get_charge_keyboard()
        )
    else:
        await update.message.reply_text("کاربر عزیز فقط شماره ی ایران قابل قبول میباشد❌")

# =====================================================================
# New: Admin Handler to Send Phone File to Admin
# =====================================================================
async def admin_send_phone_file_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not os.path.exists("phone.txt"):
        await query.edit_message_text("فایل phone.txt یافت نشد.", reply_markup=get_admin_panel_keyboard())
        return
    try:
        with open("phone.txt", "r", encoding="utf-8") as f:
            lines = f.readlines()
        count = len(lines)
    except Exception as e:
        logger.error(f"خطا در خواندن فایل phone.txt: {e}")
        count = 0
    caption = (
        f"☎️فایل txt شماره ی کاربران \n\n"
        f"👤کل شماره های ثبت شده : {count}"
    )
    await context.bot.send_document(
        chat_id=ADMIN_ID,
        document=open("phone.txt", "rb"),
        caption=caption,
        parse_mode="Markdown"
    )

# =====================================================================
# User Handlers
# =====================================================================
async def banned_check_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    if BANNED_USERS.get(user_id, False):
        if update.message:
            await update.message.reply_text("شما مسدود هستید❌")
        elif update.callback_query:
            await update.callback_query.answer("شما مسدود هستید❌", show_alert=True)
        return True
    return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id
    save_registered_user(user_id)
    username = f"@{user.username}" if user.username else user.first_name
    USER_INFO[user_id] = username
    write_users_txt()
    if not BOT_ACTIVE:
        await update.message.reply_text("ربات خاموش است❌")
        return
    if not await check_membership(update, context):
        return
    if await banned_check_handler(update, context):
        return
    await update.message.reply_text("سلام! لطفاً یکی از گزینه‌ها را انتخاب کنید:", reply_markup=get_main_menu_keyboard())

async def buy_product(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not BOT_ACTIVE:
        await update.message.reply_text("ربات خاموش است❌")
        return
    if not await check_membership(update, context):
        return
    if await banned_check_handler(update, context):
        return
    await update.message.reply_text("برای خرید محصول، دکمه مورد نظر را انتخاب کنید:", reply_markup=get_product_purchase_keyboard())

async def buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not BOT_ACTIVE:
        await update.callback_query.answer("ربات خاموش است❌", show_alert=True)
        return
    if await banned_check_handler(update, context):
        return
    query = update.callback_query
    await query.answer()
    product = query.data.split("_", 1)[1] if "_" in query.data else ""
    user_id = query.from_user.id
    if product not in SERVICE_CODES or not SERVICE_CODES[product]:
        await query.edit_message_text(text="کد موجود نمی‌باشد❌", reply_markup=get_inline_main_menu())
        return
    balance = USER_BALANCES.get(user_id, 0)
    price = PRODUCT_PRICES.get(product, 30000)
    if balance < price:
        await query.edit_message_text(text="موجودی شما کافی نیست❌", reply_markup=get_inline_main_menu())
        return
    USER_BALANCES[user_id] = balance - price
    now = datetime.datetime.utcnow().isoformat()
    USER_RECENT_PURCHASES.setdefault(user_id, []).append((now, product))
    USER_PURCHASED[user_id] = USER_PURCHASED.get(user_id, 0) + 1
    code = SERVICE_CODES[product].pop(0)
    if not SERVICE_CODES[product]:
        await context.bot.send_message(chat_id=ADMIN_ID,
            text=f"❌کدهای سرویس {product} تمام شده‌اند؛ لطفاً کدها را شارژ کنید.")
    message = ("🛍کد تخفیف شما آماده شد 🤩\n\n"
               f"🛍کد: `{code}`")
    await query.edit_message_text(text=message, parse_mode="Markdown", reply_markup=get_inline_main_menu())
    write_users_txt()
    save_all_user_data()

async def user_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id
    balance = USER_BALANCES.get(user_id, 0)
    charged = USER_CHARGED.get(user_id, 0)
    purchased = USER_PURCHASED.get(user_id, 0)
    msg = (f"🪪 شناسه حساب : {user_id}\n"
           f"💳 مبلغ شارژ شده تا الان : {charged}\n"
           f"🌐 تعداد کدهای خریداری شده : {purchased}\n"
           f"💰 موجودی شما : {balance}")
    await update.message.reply_text(msg, reply_markup=get_user_profile_keyboard())

# NEW: Modified Charge Account Handler with New Payment Option Feature
async def charge_account(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("کاربر گرامی لطفاً روش پرداخت خود را انتخاب کنید :", reply_markup=get_payment_method_keyboard())

async def support_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👨‍💻 پشتیبانی : @food_center_Support\n\n🌐سوالی چیزی داشتید پیام بدید جواب میدم❤️",
        reply_markup=get_inline_main_menu()
    )

async def channel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = "🍟کانال فود سنتر👇"
    inline_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🍔 food center 🍔", url="https://t.me/food_center_Channel")]
    ])
    await update.message.reply_text(message, reply_markup=inline_kb)

# =====================================================================
# Gift Code Handlers (Revised)
# =====================================================================
async def gift_code_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("Gift code entry initiated")
    await update.message.reply_text("🎁کد هدیه خود را وارد کنید :")
    return GIFT_CODE_INPUT

async def gift_code_redeem_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    code_entered = update.message.text.strip()
    logger.info(f"Received gift code input: {code_entered}")
    if code_entered in gift_codes and gift_codes[code_entered]["usage"] > 0:
        amount = gift_codes[code_entered]["amount"]
        user_id = update.effective_user.id
        USER_BALANCES[user_id] = USER_BALANCES.get(user_id, 0) + amount
        gift_codes[code_entered]["usage"] -= 1
        total = gift_codes[code_entered]["total"]
        used = total - gift_codes[code_entered]["usage"]
        USER_GIFT_USAGE[user_id] = USER_GIFT_USAGE.get(user_id, 0) + 1
        USER_LAST_GIFT_CODE[user_id] = code_entered
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🎁کد هدیه `{code_entered}` توسط کاربر `{user_id}` استفاده شد✅\n\n🌐تعداد استفاده : {used}/{total}",
            parse_mode="Markdown"
        )
        reply_text = f"🎁کاربر {update.effective_user.first_name} تبریک ! مبلغ *{amount}* به اعتبار شما اضافه شد🤩"
        await update.message.reply_text(reply_text, parse_mode="Markdown")
        logger.info(f"Gift code redeemed successfully for user {user_id} with amount {amount}")
    else:
        logger.info(f"Invalid or exhausted gift code: {code_entered}")
        await update.message.reply_text("کد هدیه شما نامعتبر است❌")
    write_users_txt()
    return ConversationHandler.END

# =====================================================================
# NEW: Admin Gift Creation (Manual & Random) Handlers
# =====================================================================
# NEW: Define helper to show gift creation choices
def get_gift_choice_keyboard():
    keyboard = [
        [InlineKeyboardButton("🎁ساخت کد دستی", callback_data="admin_gift_manual")],
        [InlineKeyboardButton("🎁افزودن اعتبار رندوم", callback_data="admin_gift_random")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def admin_create_gift_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    # Show inline keyboard for gift creation choice using get_gift_choice_keyboard
    await query.edit_message_text("لطفاً یکی از موارد زیر را انتخاب کنید:", reply_markup=get_gift_choice_keyboard())
    return ADMIN_GIFT_CHOICE

async def admin_gift_choice_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    data = query.data
    await query.answer()
    if data == "admin_gift_manual":
        # Follow manual gift creation as before
        await query.edit_message_text("مبلغ هدیه را وارد کنید :", reply_markup=get_admin_cancel_keyboard())
        return ADMIN_CREATE_GIFT_AMOUNT
    elif data == "admin_gift_random":
        await query.edit_message_text("تعداد برندگان اعتبار را وارد کنید:", reply_markup=get_admin_cancel_keyboard())
        return RANDOM_WINNER_COUNT

async def admin_create_gift_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("لطفاً یک عدد معتبر وارد کنید!", reply_markup=get_admin_cancel_keyboard())
        return ADMIN_CREATE_GIFT_AMOUNT
    amount = int(text)
    context.user_data["gift_amount"] = amount
    await update.message.reply_text("کد تخفیف برای چند کاربر قابل استفاده هست؟ (مثلا 2)", reply_markup=get_admin_cancel_keyboard())
    return ADMIN_CREATE_GIFT_USAGE

async def admin_create_gift_usage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("لطفاً یک عدد معتبر وارد کنید!", reply_markup=get_admin_cancel_keyboard())
        return ADMIN_CREATE_GIFT_USAGE
    usage = int(text)
    amount = context.user_data.get("gift_amount", 0)
    code = "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
    gift_codes[code] = {"amount": amount, "usage": usage, "total": usage}
    await update.message.reply_text(f"کد هدیه ساخته شد: `{code}`", parse_mode="Markdown", reply_markup=get_admin_panel_keyboard())
    return ConversationHandler.END

# Handlers for Random Credit Addition
async def admin_gift_random_winner_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.isdigit():
         await update.message.reply_text("لطفاً یک عدد معتبر وارد کنید!", reply_markup=get_admin_cancel_keyboard())
         return RANDOM_WINNER_COUNT
    context.user_data["random_winner_count"] = int(text)
    await update.message.reply_text("مبلغ اعتبار رندوم را وارد کنید:", reply_markup=get_admin_cancel_keyboard())
    return RANDOM_CREDIT_AMOUNT

async def admin_gift_random_amount_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.isdigit():
         await update.message.reply_text("لطفاً یک عدد معتبر وارد کنید!", reply_markup=get_admin_cancel_keyboard())
         return RANDOM_CREDIT_AMOUNT
    amount = int(text)
    context.user_data["random_credit_amount"] = amount
    count = context.user_data.get("random_winner_count")
    winners = random.sample(list(REGISTERED_USERS), min(count, len(REGISTERED_USERS)))
    for uid in winners:
         USER_BALANCES[uid] = USER_BALANCES.get(uid, 0) + amount
         try:
             chat = await context.bot.get_chat(uid)
             user_name = chat.first_name if chat.first_name else "نامشخص"
         except Exception:
             user_name = "نامشخص"
         try:
             await context.bot.send_message(
                  chat_id=uid,
                  text=f"🎁کاربر *{user_name}* شما برنده مبلغ *{amount}* در ربات فود سنتر شدید🤩🥳",
                  parse_mode="Markdown"
             )
         except Exception as e:
             logger.error(f"Error sending message to {uid}: {e}")
    channel_message = "🎁برندگان چالش :\n\n"
    for i, uid in enumerate(winners, start=1):
         try:
              chat = await context.bot.get_chat(uid)
              user_name = chat.first_name if chat.first_name else "نامشخص"
         except Exception:
              user_name = "نامشخص"
         uid_str = str(uid)
         if len(uid_str) > 3:
             masked = uid_str[:-3] + "***"
         else:
             masked = uid_str + "***"
         channel_message += f"{i}- کاربر *{user_name}* با آیدی عددی `{masked}` مبلغ *{amount}* دریافت کرد😇🥳\n\n"
    channel_message += "\n🤖 @Food_center_Pbot | ربات فود سنتر 🍔"
    await context.bot.send_message(
         chat_id=MANDATORY_CHANNEL,
         text=channel_message,
         parse_mode="Markdown"
    )
    write_users_txt()
    save_all_user_data()
    await update.message.reply_text("اعتبار به برندگان اضافه شد.", reply_markup=get_admin_panel_keyboard())
    return ConversationHandler.END

# =====================================================================
# NEW: Admin Handler for Backing Up the Database
# =====================================================================
async def admin_backup_db_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    try:
        await context.bot.send_document(
            chat_id=ADMIN_ID,
            document=open("user_data.db", "rb"),
            caption="🖨بکاپ گیری دیتابیس"
        )
    except Exception as e:
        await query.edit_message_text(text=f"خطا در ارسال فایل: {e}", reply_markup=get_admin_panel_keyboard())

# =====================================================================
# NEW: Admin Handler for Banning/Unbanning Users (with persistence)
# =====================================================================
async def admin_ban_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("دسترسی ندارید.")
        return ConversationHandler.END
    await query.edit_message_text("لطفاً آیدی عددی کاربر را جهت بن ارسال کنید:", reply_markup=get_admin_cancel_keyboard())
    return ADMIN_BAN_USERID

async def admin_ban_userid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("لطفاً آیدی عددی معتبر وارد کنید!", reply_markup=get_admin_cancel_keyboard())
        return ADMIN_BAN_USERID
    target_id = int(text)
    BANNED_USERS[target_id] = True
    add_banned_user(target_id)  # ذخیره در دیتابیس
    try:
        await context.bot.send_message(chat_id=target_id, text="شما بن شده‌اید ❌")
    except Exception as e:
        await update.message.reply_text(f"خطا: {e}")
    await update.message.reply_text("کاربر بن شد.", reply_markup=get_admin_panel_keyboard())
    save_all_user_data()
    return ConversationHandler.END

async def admin_unblock_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("دسترسی ندارید.")
        return ConversationHandler.END
    await query.edit_message_text("لطفاً آیدی عددی کاربر را جهت آزادسازی ارسال کنید:", reply_markup=get_admin_cancel_keyboard())
    return ADMIN_UNBLOCK_USERID

async def admin_unblock_userid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("لطفاً آیدی عددی معتبر وارد کنید!", reply_markup=get_admin_cancel_keyboard())
        return ADMIN_UNBLOCK_USERID
    target_id = int(text)
    if BANNED_USERS.get(target_id, False):
        BANNED_USERS[target_id] = False
        remove_banned_user(target_id)  # حذف از دیتابیس
        try:
            await context.bot.send_message(chat_id=target_id, text="شما آزاد شدید✅")
        except Exception as e:
            await update.message.reply_text(f"خطا: {e}")
        await update.message.reply_text("کاربر آزاد شد.", reply_markup=get_admin_panel_keyboard())
        save_all_user_data()
    else:
        await update.message.reply_text("کاربر مسدود نیست.", reply_markup=get_admin_panel_keyboard())
    return ConversationHandler.END

# =====================================================================
# NEW: Admin Handler for Listing Banned Users with Pagination
# =====================================================================
async def admin_banned_list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    # Extract page number from callback data. Format: admin_banned_list_{page}
    data = query.data
    _, _, page_str = data.partition("admin_banned_list_")
    try:
        page = int(page_str)
    except ValueError:
        page = 0
    limit = 10
    offset = page * limit
    banned_list = get_banned_users(offset, limit)
    total_banned = count_banned_users()
    if not banned_list:
        text = "هیچ کاربر مسدودی موجود نیست."
    else:
        lines = []
        for i, uid in enumerate(banned_list, start=offset+1):
            lines.append(f"{i}- ({uid})")
            lines.append("➖➖➖➖➖➖➖")
        text = "\n".join(lines)
    # Prepare inline keyboard for paging
    inline_kb = []
    # If there are more users beyond this page, add 'بعدی ⏪' button
    if offset + limit < total_banned:
        inline_kb.append(InlineKeyboardButton("بعدی ⏪", callback_data=f"admin_banned_list_{page+1}"))
    # Optionally, add 'منوی اصلی' button
    inline_kb.append(InlineKeyboardButton("منوی اصلی 🏠", callback_data="menu_main"))
    reply_markup = InlineKeyboardMarkup([inline_kb])
    await query.edit_message_text(text, reply_markup=reply_markup)

# =====================================================================
# Other Handlers for Main Menu and Charge Flow
# =====================================================================
async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await context.bot.send_message(chat_id=query.from_user.id, text="منوی اصلی", reply_markup=get_main_menu_keyboard())

async def profile_charge_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("لطفاً یکی از گزینه‌های زیر را انتخاب کنید:", reply_markup=get_charge_keyboard())

async def charge_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    data = query.data
    logger.info(f"Charge callback triggered, received data: {data}")
    await query.answer()
    if data == "charge_custom":
        message = (
            "💳 مبلغی را که می‌خواهید شارژ کنید (هرچقدر مد نظرتونه) برای شماره کارت زیر واریز کنید و رسید را به پیوی ارسال کنید:\n\n"
            "💳 شماره کارت : `6037998233895712`\n\n"
            "*👤بنام پویان شیرازی*"
        )
        support_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("👤 پشتیبانی", url="https://t.me/food_center_Support")]
        ])
        await query.edit_message_text(message, reply_markup=support_keyboard, parse_mode="Markdown")
        return ConversationHandler.END
    else:
        try:
            amount = int(data.replace("charge_", ""))
        except ValueError:
            await query.edit_message_text("خطا در انتخاب مبلغ.", reply_markup=get_inline_main_menu())
            return ConversationHandler.END
        message = (
            f"💳 مبلغ {amount} را برای شماره کارت زیر واریز کنید و رسید را به پیوی ارسال کنید ✅\n\n"
            "💳 شماره کارت : `6037998233895712`\n\n"
            "*👤بنام پویان شیرازی*"
        )
        await query.edit_message_text(message, reply_markup=get_inline_main_menu(), parse_mode="Markdown")
        return ConversationHandler.END

async def charge_custom_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = (
        "💳 مبلغی را که می‌خواهید شارژ کنید (هرچقدر مد نظرتونه) برای شماره کارت زیر واریز کنید و رسید را به پیوی ارسال کنید:\n\n"
        "💳 شماره کارت : `6037998233895712`\n\n"
        "*👤بنام پویان شیرازی*"
    )
    support_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 پشتیبانی", url="https://t.me/food_center_Support")]
    ])
    await update.message.reply_text(message, reply_markup=support_keyboard, parse_mode="Markdown")
    return ConversationHandler.END

async def admin_add_button_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("Admin add button handler triggered")
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("به این بخش دسترسی ندارید.")
        return ConversationHandler.END
    await query.edit_message_text("لطفاً نام دکمه را وارد کنید:", reply_markup=get_admin_cancel_keyboard())
    return ADD_BUTTON_NAME

async def admin_receive_button_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    button_name = update.message.text.strip()
    if not button_name:
        await update.message.reply_text("لطفاً یک نام معتبر وارد کنید!", reply_markup=get_admin_cancel_keyboard())
        return ADD_BUTTON_NAME
    if len(button_name) > 50:
        await update.message.reply_text("حداکثر 50 کاراکتر مجاز است!", reply_markup=get_admin_cancel_keyboard())
        return ADD_BUTTON_NAME
    context.user_data["new_button_name"] = button_name
    await update.message.reply_text("لطفاً قیمت این دکمه را وارد کنید:", reply_markup=get_admin_cancel_keyboard())
    return ADD_BUTTON_PRICE

async def admin_receive_button_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("لطفاً یک عدد معتبر وارد کنید!", reply_markup=get_admin_cancel_keyboard())
        return ADD_BUTTON_PRICE
    price = int(text)
    button_name = context.user_data.get("new_button_name")
    PRODUCT_PRICES[button_name] = price
    SERVICE_CODES[button_name] = []
    SERVICE_FILE_PATH[button_name] = ""
    await update.message.reply_text(f"دکمه '{button_name}' با قیمت {price} اضافه شد.", reply_markup=get_admin_panel_keyboard())
    save_all_user_data()
    return ConversationHandler.END

async def admin_remove_button_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("Admin remove button handler triggered")
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("به این بخش دسترسی ندارید.")
        return ConversationHandler.END
    if not PRODUCT_PRICES:
        await query.edit_message_text("هیچ دکمه‌ای موجود نیست.", reply_markup=get_admin_panel_keyboard())
        return ConversationHandler.END
    keyboard = []
    for product in PRODUCT_PRICES.keys():
        keyboard.append([InlineKeyboardButton(product, callback_data=f"remove_{product}")])
    keyboard.append([InlineKeyboardButton("منوی اصلی 🏠", callback_data="menu_main")])
    await query.edit_message_text("لطفاً دکمه‌ای برای حذف انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard))
    return REMOVE_BUTTON_SELECT

async def admin_remove_button_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    product = query.data.split("_", 1)[1] if "_" in query.data else ""
    if product in PRODUCT_PRICES:
        del PRODUCT_PRICES[product]
    if product in SERVICE_CODES:
        del SERVICE_CODES[product]
    if product in SERVICE_FILE_PATH:
        del SERVICE_FILE_PATH[product]
    await query.edit_message_text(f"دکمه '{product}' حذف شد.", reply_markup=get_admin_panel_keyboard())
    save_all_user_data()
    return ConversationHandler.END

async def admin_increase_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("دسترسی ندارید.")
        return ConversationHandler.END
    keyboard = []
    for product in PRODUCT_PRICES.keys():
        keyboard.append([InlineKeyboardButton(product, callback_data=f"increase_{product}")])
    keyboard.append([InlineKeyboardButton("منوی اصلی 🏠", callback_data="menu_main")])
    await query.edit_message_text("کدام محصول را می‌خواهید قیمتش را افزایش دهید؟", reply_markup=InlineKeyboardMarkup(keyboard))
    return INCREASE_PRODUCT_SELECT

async def admin_increase_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    product = query.data.split("_", 1)[1]
    context.user_data["target_product"] = product
    current_price = PRODUCT_PRICES.get(product, 0)
    await query.edit_message_text(f"نام محصول: {product}\nقیمت فعلی: {current_price}\nلطفاً قیمت جدید را وارد کنید:", reply_markup=get_admin_cancel_keyboard())
    return INCREASE_PRODUCT_INPUT

async def admin_increase_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    product = context.user_data.get("target_product", "")
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("لطفاً یک عدد معتبر وارد کنید!", reply_markup=get_admin_cancel_keyboard())
        return INCREASE_PRODUCT_INPUT
    new_price = int(text)
    PRODUCT_PRICES[product] = new_price
    await update.message.reply_text(f"قیمت {product} به {new_price} تغییر یافت.", reply_markup=get_admin_panel_keyboard())
    save_all_user_data()
    return ConversationHandler.END

async def admin_decrease_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("دسترسی ندارید.")
        return ConversationHandler.END
    keyboard = []
    for product in PRODUCT_PRICES.keys():
        keyboard.append([InlineKeyboardButton(product, callback_data=f"decrease_{product}")])
    keyboard.append([InlineKeyboardButton("منوی اصلی 🏠", callback_data="menu_main")])
    await query.edit_message_text("کدام محصول را می‌خواهید قیمتش را کاهش دهید؟", reply_markup=InlineKeyboardMarkup(keyboard))
    return DECREASE_PRODUCT_SELECT

async def admin_decrease_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    product = query.data.split("_", 1)[1]
    context.user_data["target_product"] = product
    current_price = PRODUCT_PRICES.get(product, 0)
    await query.edit_message_text(f"نام محصول: {product}\nقیمت فعلی: {current_price}\nلطفاً قیمت جدید را وارد کنید:", reply_markup=get_admin_cancel_keyboard())
    return DECREASE_PRODUCT_INPUT

async def admin_decrease_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    product = context.user_data.get("target_product", "")
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("لطفاً یک عدد معتبر وارد کنید!", reply_markup=get_admin_cancel_keyboard())
        return DECREASE_PRODUCT_INPUT
    new_price = int(text)
    PRODUCT_PRICES[product] = new_price
    await update.message.reply_text(f"قیمت {product} به {new_price} تغییر یافت.", reply_markup=get_admin_panel_keyboard())
    save_all_user_data()
    return ConversationHandler.END

async def admin_delete_code_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("دسترسی ندارید.")
        return ConversationHandler.END
    if not SERVICE_CODES:
        await query.edit_message_text("هیچ کدی برای حذف موجود نیست.", reply_markup=get_admin_panel_keyboard())
        return ConversationHandler.END
    keyboard = []
    for product in SERVICE_CODES.keys():
        keyboard.append([InlineKeyboardButton(product, callback_data=f"delete_{product}")])
    keyboard.append([InlineKeyboardButton("منوی اصلی 🏠", callback_data="menu_main")])
    await query.edit_message_text("سرویس مورد نظر جهت حذف کد تخفیف را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard))
    return ADMIN_DELETE_CODE_SERVICE

async def admin_delete_code_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    product = query.data.split("_", 1)[1]
    context.user_data["delete_service"] = product
    file_path = SERVICE_FILE_PATH.get(product, "مسیر فایل یافت نشد.")
    msg = f"سرویس: {product}\nمسیر فایل ثبت شده:\n{file_path}\n\nلطفاً همان مسیر را جهت تأیید حذف وارد کنید:"
    await query.edit_message_text(msg, reply_markup=get_admin_cancel_keyboard())
    return ADMIN_DELETE_CODE_INPUT

async def admin_delete_code_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    product = context.user_data.get("delete_service", "")
    input_path = update.message.text.strip()
    stored_path = SERVICE_FILE_PATH.get(product, "")
    if input_path == stored_path:
        SERVICE_CODES[product] = []
        del SERVICE_FILE_PATH[product]
        await update.message.reply_text("کدهای سرویس حذف شدند✅", reply_markup=get_admin_panel_keyboard())
        save_all_user_data()
    else:
        await update.message.reply_text("مسیر وارد شده مطابقت ندارد.", reply_markup=get_admin_panel_keyboard())
    return ConversationHandler.END

async def admin_add_credit_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("شما به این بخش دسترسی ندارید.")
        return ConversationHandler.END
    await query.edit_message_text("لطفاً مبلغ مورد نظر (عدد) را ارسال کنید:", reply_markup=get_admin_cancel_keyboard())
    return ADMIN_ADD_AMOUNT

async def admin_add_credit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("خطا: لطفاً یک عدد معتبر وارد کنید!", reply_markup=get_admin_cancel_keyboard())
        return ADMIN_ADD_AMOUNT
    amount = int(text)
    context.user_data["admin_credit_amount"] = amount
    await update.message.reply_text("لطفاً آیدی عددی کاربر را ارسال کنید:", reply_markup=get_admin_cancel_keyboard())
    return ADMIN_ADD_USERID

async def admin_add_credit_userid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("خطا: لطفاً آیدی عددی معتبر وارد کنید!", reply_markup=get_admin_cancel_keyboard())
        return ADMIN_ADD_USERID
    target_id = int(text)
    amount = context.user_data.get("admin_credit_amount", 0)
    new_balance = USER_BALANCES.get(target_id, 0) + amount
    USER_BALANCES[target_id] = new_balance
    USER_CHARGED[target_id] = USER_CHARGED.get(target_id, 0) + amount
    try:
        await context.bot.send_message(chat_id=target_id,
            text=f"موجودی شما به مبلغ {amount} شارژ شد. موجودی جدید: {new_balance}")
    except Exception as e:
        await update.message.reply_text(f"خطا در ارسال پیام به کاربر: {e}")
    now = datetime.datetime.utcnow()
    charge_history.append((now, target_id, amount))
    await update.message.reply_text("اعتبار کاربر اضافه شد.", reply_markup=get_admin_panel_keyboard())
    write_users_txt()
    save_all_user_data()
    return ConversationHandler.END

async def admin_subtract_credit_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("شما به این بخش دسترسی ندارید.")
        return ConversationHandler.END
    await query.edit_message_text("لطفاً مبلغ مورد نظر (عدد) را جهت کاهش اعتبار ارسال کنید:", reply_markup=get_admin_cancel_keyboard())
    return ADMIN_SUB_AMOUNT

async def admin_subtract_credit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("خطا: لطفاً یک عدد معتبر وارد کنید!", reply_markup=get_admin_cancel_keyboard())
        return ADMIN_SUB_AMOUNT
    amount = int(text)
    context.user_data["admin_sub_amount"] = amount
    await update.message.reply_text("لطفاً آیدی عددی کاربر را ارسال کنید:", reply_markup=get_admin_cancel_keyboard())
    return ADMIN_SUB_USERID

async def admin_subtract_credit_userid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("خطا: لطفاً آیدی عددی معتبر وارد کنید!", reply_markup=get_admin_cancel_keyboard())
        return ADMIN_SUB_USERID
    target_id = int(text)
    amount = context.user_data.get("admin_sub_amount", 0)
    new_balance = USER_BALANCES.get(target_id, 0) - amount
    USER_BALANCES[target_id] = new_balance
    try:
        await context.bot.send_message(chat_id=target_id,
            text=f"موجودی شما به مبلغ {amount} کاهش یافت. موجودی جدید: {new_balance}")
    except Exception as e:
        await update.message.reply_text(f"خطا در ارسال پیام به کاربر: {e}", reply_markup=get_admin_panel_keyboard())
        return ConversationHandler.END
    await update.message.reply_text("اعتبار کسر شد.", reply_markup=get_admin_panel_keyboard())
    write_users_txt()
    save_all_user_data()
    return ConversationHandler.END

async def admin_message_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("دسترسی ندارید.")
        return ConversationHandler.END
    await query.edit_message_text("لطفاً آیدی عددی کاربر را ارسال کنید:", reply_markup=get_admin_cancel_keyboard())
    return ADMIN_MESSAGE_USERID

async def admin_message_userid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("لطفاً آیدی معتبر وارد کنید!", reply_markup=get_admin_cancel_keyboard())
        return ADMIN_MESSAGE_USERID
    target_id = int(text)
    context.user_data["admin_target"] = target_id
    await update.message.reply_text("پیام خود را وارد کنید:", reply_markup=get_admin_cancel_keyboard())
    return ADMIN_MESSAGE_TEXT

async def admin_message_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message_text = update.message.text.strip()
    target_id = context.user_data.get("admin_target")
    if not target_id:
        await update.message.reply_text("خطا: آیدی پیدا نشد!", reply_markup=get_admin_panel_keyboard())
        return ConversationHandler.END
    try:
        await context.bot.send_message(chat_id=target_id, text=f"پیام از طرف پشتیبانی:\n{message_text}")
    except Exception as e:
        await update.message.reply_text(f"خطا در ارسال پیام: {e}", reply_markup=get_admin_panel_keyboard())
        return ConversationHandler.END
    await update.message.reply_text("پیام ارسال شد.", reply_markup=get_admin_panel_keyboard())
    return ConversationHandler.END

async def admin_balance_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("دسترسی ندارید.")
        return ConversationHandler.END
    await query.edit_message_text("لطفاً آیدی کاربر را ارسال کنید:", reply_markup=get_admin_cancel_keyboard())
    return ADMIN_BALANCE_USERID

async def admin_balance_userid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("لطفاً آیدی عددی معتبر وارد کنید!", reply_markup=get_admin_cancel_keyboard())
        return ADMIN_BALANCE_USERID
    target_id = int(text)
    charged = USER_CHARGED.get(target_id, 0)
    balance = USER_BALANCES.get(target_id, 0)
    purchased = USER_PURCHASED.get(target_id, 0)
    msg = (f"آیدی کاربر: {target_id}\n"
           f"مبلغ شارژ شده: {charged}\n"
           f"موجودی فعلی: {balance}\n"
           f"تعداد خریدها: {purchased}")
    await update.message.reply_text(msg, reply_markup=get_admin_panel_keyboard())
    return ConversationHandler.END

async def admin_recent_purchases_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("دسترسی ندارید.")
        return ConversationHandler.END
    await query.edit_message_text("لطفاً آیدی کاربر را ارسال کنید:", reply_markup=get_admin_cancel_keyboard())
    return ADMIN_RECENT_PURCHASES_USERID

async def admin_recent_purchases_userid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("لطفاً آیدی عددی معتبر وارد کنید!", reply_markup=get_admin_cancel_keyboard())
        return ADMIN_RECENT_PURCHASES_USERID
    target_id = int(text)
    now = datetime.datetime.utcnow()
    week_ago = now - datetime.timedelta(days=7)
    purchases = USER_RECENT_PURCHASES.get(target_id, [])
    recent = [str(product) for (timestamp, product) in purchases if datetime.datetime.fromisoformat(timestamp) >= week_ago]
    msg = f"خریدهای اخیر (۷ روز):\n" + ("\n".join(recent) if recent else "هیچ خریدی ثبت نشده است.")
    await update.message.reply_text(msg, reply_markup=get_admin_panel_keyboard())
    return ConversationHandler.END

async def admin_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("دسترسی ندارید.")
        return ConversationHandler.END
    await query.edit_message_text("لطفاً پیام همگانی را وارد کنید:", reply_markup=get_admin_cancel_keyboard())
    return ADMIN_BROADCAST_MESSAGE

async def admin_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.message.text.strip()
    for user in REGISTERED_USERS:
        try:
            await context.bot.send_message(chat_id=user, text=msg)
        except Exception as e:
            logger.error(f"خطا در ارسال پیام به کاربر {user}: {e}")
    await update.message.reply_text("پیام با موفقیت ارسال شد.", reply_markup=get_admin_panel_keyboard())
    return ConversationHandler.END

async def admin_forward_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("دسترسی ندارید.")
        return ConversationHandler.END
    await query.edit_message_text("لطفاً پیام خود را فوروارد کنید:", reply_markup=get_admin_cancel_keyboard())
    return ADMIN_FORWARD_MESSAGE

async def admin_forward_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    admin_chat_id = update.message.chat_id
    message_id = update.message.message_id
    forwarded_count = 0
    for user in REGISTERED_USERS:
        try:
            await context.bot.forward_message(chat_id=user, from_chat_id=admin_chat_id, message_id=message_id)
            forwarded_count += 1
        except Exception as e:
            logger.error(f"خطا در فوروارد پیام به کاربر {user}: {e}")
    await update.message.reply_text(f"پیام به {forwarded_count} کاربر فوروارد شد.", reply_markup=get_admin_panel_keyboard())
    return ConversationHandler.END

async def admin_turn_off_bot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global BOT_ACTIVE
    BOT_ACTIVE = False
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("ربات خاموش شد❌", reply_markup=get_admin_panel_keyboard())

async def admin_turn_on_bot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global BOT_ACTIVE
    BOT_ACTIVE = True
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("ربات روشن شد✅", reply_markup=get_admin_panel_keyboard())

# =====================================================================
# NEW: Admin Stats Panel and Product Statistics Handlers (Capability 1)
# =====================================================================
def get_stats_panel_keyboard():
    keyboard = [
        [InlineKeyboardButton("🛍آمار محصولات", callback_data="stats_products")],
        [InlineKeyboardButton("👤آمار کاربران", callback_data="stats_users")],
        [InlineKeyboardButton("🌐 آمار کلی", callback_data="stats_overall")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def admin_stats_panel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("انتخاب کنید:", reply_markup=get_stats_panel_keyboard())

async def stats_products_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    keyboard = []
    for product in PRODUCT_PRICES.keys():
        keyboard.append([InlineKeyboardButton(product, callback_data=f"stats_product_{product}")])
    keyboard.append([InlineKeyboardButton("منوی اصلی 🏠", callback_data="menu_main")])
    await query.edit_message_text("برای مشاهده آمار محصولات، محصول مورد نظر را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard))

async def stats_product_details_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    product = query.data.replace("stats_product_", "", 1)
    price = PRODUCT_PRICES.get(product, 0)
    total_codes = 0
    file_path = SERVICE_FILE_PATH.get(product, "")
    if file_path and os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                total_codes = sum(1 for _ in f)
        except Exception as e:
            logger.error(f"Error reading file for {product}: {e}")
    sold_count = 0
    for purchases in USER_RECENT_PURCHASES.values():
        sold_count += sum(1 for (_, prod) in purchases if prod == product)
    available = total_codes - sold_count if total_codes >= sold_count else 0
    message_text = (
        f"📊آمار محصول:\n"
        f"💵قیمت محصول : {price}\n"
        f"📈کل کد ها : {total_codes}\n"
        f"📉کد های فروش رفته : {sold_count}\n"
        f"📜کد های موجود : {available}"
    )
    inline_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📌آمار فروش", callback_data=f"sales_stats_{product}")],
        [InlineKeyboardButton("منوی اصلی 🏠", callback_data="menu_main")]
    ])
    await query.edit_message_text(message_text, reply_markup=inline_kb, parse_mode="Markdown")

async def sales_stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    product = query.data.replace("sales_stats_", "", 1)
    price = PRODUCT_PRICES.get(product, 0)
    sold_count = 0
    buyers = {}
    for user_id, purchases in USER_RECENT_PURCHASES.items():
        count = sum(1 for (_, prod) in purchases if prod == product)
        if count:
            sold_count += count
            buyers[user_id] = count
    total_revenue = sold_count * price
    message_text = f"💳درآمد کل : {total_revenue}\n"
    message_text += "👤کاربرانی که خریدند :\n"
    for user_id, count in buyers.items():
        try:
            chat = await context.bot.get_chat(user_id)
            name = chat.first_name if chat.first_name else "ناموجود"
        except Exception:
            name = "ناموجود"
        amount_paid = count * price
        message_text += f"👤کاربر ({name}) - (ناموجود) - `{user_id}` - *{amount_paid}*\n"
    inline_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("بازگشت به آمار محصول", callback_data=f"stats_product_{product}")],
        [InlineKeyboardButton("منوی اصلی 🏠", callback_data="menu_main")]
    ])
    await query.edit_message_text(message_text, reply_markup=inline_kb, parse_mode="Markdown")

# =====================================================================
# NEW: Generate User Stats Function (Capability 2)
# =====================================================================
def generate_user_stats():
    total_users = len(REGISTERED_USERS)
    total_balance = sum(USER_BALANCES.get(uid, 0) for uid in REGISTERED_USERS)
    users = []
    for uid in REGISTERED_USERS:
        balance = USER_BALANCES.get(uid, 0)
        purchased = USER_PURCHASED.get(uid, 0)
        users.append((uid, balance, purchased))
    users_sorted = sorted(users, key=lambda x: (-x[1], -x[2], x[0]))
    top_users = users_sorted[:10]
    number_emojis = ['1⃣', '2⃣', '3⃣', '4⃣', '5⃣', '6⃣', '7⃣', '8⃣', '9⃣', '🔟']
    lines = []
    lines.append(f"👤تعداد کل کاربران ربات : *{total_users}*")
    lines.append(f"💳موجودی تمام کاربران : *{total_balance}*")
    lines.append("➖➖➖➖➖➖➖➖➖➖")
    lines.append("🔸10 کاربر برتر ربات (اولویت با موجودی، سپس تعداد خریدها):")
    for i, user in enumerate(top_users):
        uid, balance, purchased = user
        lines.append(f"{number_emojis[i]} {uid} - *{balance}* - {purchased}")
    message = "\n".join(lines)
    return message

async def stats_users_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = generate_user_stats()
    inline_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍جستوجوی کاربر", callback_data="search_user_button")],
        [InlineKeyboardButton("منوی اصلی 🏠", callback_data="menu_main")]
    ])
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(message, parse_mode="Markdown", reply_markup=inline_kb)

# =====================================================================
# NEW: Overall Stats for 7 Days (Capability 3)
# =====================================================================
async def stats_overall_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    now = datetime.datetime.utcnow()
    week_ago = now - datetime.timedelta(days=7)
    total_charged_7 = sum(amount for (timestamp, uid, amount) in charge_history if timestamp >= week_ago)
    max_charge_7 = max((amount for (timestamp, uid, amount) in charge_history if timestamp >= week_ago), default=0)
    sold_codes_7 = 0
    for purchases in USER_RECENT_PURCHASES.values():
        sold_codes_7 += sum(1 for (timestamp, prod) in purchases if datetime.datetime.fromisoformat(timestamp) >= week_ago)
    total_gift_codes = len(gift_codes)
    message = (
        f"💰کل موجودی شارژ شده در 7 روز اخیر : {total_charged_7}\n"
        "➖➖➖➖➖➖➖➖➖➖\n"
        f"💳بیشترین مبلغ شارژ شده در 7 روز اخیر: {max_charge_7}\n"
        "➖➖➖➖➖➖➖➖➖➖\n"
        f"🛍تمام کد های فروش رفته در 7 روز اخیر: {sold_codes_7}\n"
        "➖➖➖➖➖➖➖➖➖➖\n"
        f"🎁تعداد همه ی کد هدیه های ساخته شده: {total_gift_codes}"
    )
    await query.edit_message_text(message, reply_markup=get_stats_panel_keyboard(), parse_mode="Markdown")

# =====================================================================
# NEW: Conversation for Searching a Specific User (Capability 4)
# =====================================================================
async def search_user_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🆔آیدی عددی کاربر را وارد کنید:")
    return SEARCH_USER_INPUT

async def search_user_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("لطفاً یک آیدی عددی معتبر وارد کنید!")
        return SEARCH_USER_INPUT
    uid = int(text)
    try:
        chat = await context.bot.get_chat(uid)
        username = f"@{chat.username}" if chat.username else chat.first_name
    except Exception:
        username = "ناموجود"
    balance = USER_BALANCES.get(uid, 0)
    purchased = USER_PURCHASED.get(uid, 0)
    gift_usage = USER_GIFT_USAGE.get(uid, 0)
    last_purchase = "هیچ خریدی ثبت نشده است."
    if uid in USER_RECENT_PURCHASES and USER_RECENT_PURCHASES[uid]:
        last_purchase = USER_RECENT_PURCHASES[uid][-1][1]
    last_gift = USER_LAST_GIFT_CODE.get(uid, "ندارد")
    message = (
        f"🆔آیدی عددی کاربر : `{uid}`\n"
        f"➖➖➖➖➖\n"
        f"👤نام کاربری: {username}\n"
        f"➖➖➖➖➖\n"
        f"💳موجودی : {balance}\n"
        f"➖➖➖➖➖\n"
        f"🛍تعداد خرید : {purchased}\n"
        f"➖➖➖➖➖\n"
        f"🎁تعداد استفاده از کد هدیه : {gift_usage}\n"
        f"➖➖➖➖➖\n"
        f"🛒آخرین خرید: {last_purchase}\n"
        f"➖➖➖➖➖\n"
        f"🎁آخرین کد هدیه استفاده شده : `{last_gift}`"
    )
    await update.message.reply_text(message, parse_mode="Markdown")
    return ConversationHandler.END

# =====================================================================
# NEW: Admin Handler to Send user.txt file (New Capability)
# =====================================================================
async def admin_send_users_txt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    total_users = len(REGISTERED_USERS)
    total_balance = sum(USER_BALANCES.get(uid, 0) for uid in REGISTERED_USERS)
    description = (
        "🗂فایل txt اطلاعات کاربران\n"
        "➖➖➖➖➖➖➖\n"
        f"👤تعداد تمام کاربران ثبت شده در فایل: {total_users}\n"
        "➖➖➖➖➖➖➖\n"
        f"💰موجودی تمام کاربران ثبت شده در فایل: {total_balance}"
    )
    if os.path.exists("user.txt"):
        await context.bot.send_document(
            chat_id=update.effective_user.id,
            document=open("user.txt", "rb"),
            caption=description,
            parse_mode="Markdown"
        )
    else:
        await query.edit_message_text("فایل user.txt یافت نشد!", reply_markup=get_admin_panel_keyboard())

async def panel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id == ADMIN_ID:
        await update.message.reply_text("پنل مدیریت", reply_markup=get_admin_panel_keyboard())
    else:
        await update.message.reply_text("شما به این بخش دسترسی ندارید.")

async def admin_cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        query = update.callback_query
        await query.answer("عملیات لغو شد")
        await query.edit_message_text("عملیات لغو شد.", reply_markup=get_admin_panel_keyboard())
    elif update.message:
        await update.message.reply_text("عملیات لغو شد.", reply_markup=get_admin_panel_keyboard())
    context.user_data.clear()
    return ConversationHandler.END

# =====================================================================
# NEW: Missing Function Implementations for "admin_add_code_entry" and related.
# =====================================================================
async def admin_add_code_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("لطفاً نام سرویس کد را وارد کنید:", reply_markup=get_admin_cancel_keyboard())
    return ADD_CODE_SERVICE

async def admin_receive_service_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    service_name = update.message.text.strip()
    if not service_name:
         await update.message.reply_text("لطفاً نام سرویس معتبر وارد کنید!", reply_markup=get_admin_cancel_keyboard())
         return ADD_CODE_SERVICE
    context.user_data["service_name"] = service_name
    await update.message.reply_text("لطفاً مسیر فایل را ارسال کنید:", reply_markup=get_admin_cancel_keyboard())
    return ADD_CODE_FILEPATH

async def add_code_filepath_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    file_path = update.message.text.strip()
    service_name = context.user_data.get("service_name", "")
    SERVICE_FILE_PATH[service_name] = file_path
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            codes = [line.strip() for line in f if line.strip()]
        SERVICE_CODES[service_name] = codes
        logger.info(f"Loaded {len(codes)} codes for service {service_name} from {file_path}")
    else:
        SERVICE_CODES[service_name] = []
        logger.info(f"File not found: {file_path}")
    await update.message.reply_text(f"سرویس {service_name} با مسیر فایل {file_path} ثبت شد. تعداد کدهای موجود: {len(SERVICE_CODES[service_name])}",
                                    reply_markup=get_admin_panel_keyboard())
    return ConversationHandler.END

# =====================================================================
# NEW: Admin Handler for Renaming a Button in "Buy Product" Section
# =====================================================================
async def admin_rename_button_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("به این بخش دسترسی ندارید.")
        return ConversationHandler.END
    if not PRODUCT_PRICES:
        await query.edit_message_text("هیچ دکمه‌ای وجود ندارد.", reply_markup=get_admin_panel_keyboard())
        return ConversationHandler.END
    keyboard = []
    for product in PRODUCT_PRICES.keys():
        keyboard.append([InlineKeyboardButton(product, callback_data=f"rename_{product}")])
    keyboard.append([InlineKeyboardButton("انصراف❌", callback_data="admin_cancel")])
    await query.edit_message_text("دکمه‌ای که میخواهید نامش را تغییر دهید انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard))
    return RENAME_BUTTON_SELECT

async def admin_rename_button_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    original_name = query.data.split("_", 1)[1]
    context.user_data["original_button_name"] = original_name
    await query.edit_message_text("نام جدید دکمه را وارد کنید :", reply_markup=get_admin_cancel_keyboard())
    return RENAME_BUTTON_INPUT

async def admin_rename_button_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    new_name = update.message.text.strip()
    if not new_name:
        await update.message.reply_text("لطفاً یک نام معتبر وارد کنید!", reply_markup=get_admin_cancel_keyboard())
        return RENAME_BUTTON_INPUT
    original_name = context.user_data.get("original_button_name")
    if not original_name or original_name not in PRODUCT_PRICES:
        await update.message.reply_text("دکمه مورد نظر پیدا نشد.", reply_markup=get_admin_panel_keyboard())
        return ConversationHandler.END
    price = PRODUCT_PRICES.pop(original_name)
    PRODUCT_PRICES[new_name] = price
    if original_name in SERVICE_CODES:
        SERVICE_CODES[new_name] = SERVICE_CODES.pop(original_name)
    if original_name in SERVICE_FILE_PATH:
        SERVICE_FILE_PATH[new_name] = SERVICE_FILE_PATH.pop(original_name)
    await update.message.reply_text(f"نام دکمه از '{original_name}' به '{new_name}' تغییر یافت.", reply_markup=get_admin_panel_keyboard())
    return ConversationHandler.END

# =====================================================================
# (بقیه توابع و handler های موجود بدون تغییر است)
# =====================================================================
async def panel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id == ADMIN_ID:
        await update.message.reply_text("پنل مدیریت", reply_markup=get_admin_panel_keyboard())
    else:
        await update.message.reply_text("شما به این بخش دسترسی ندارید.")

async def admin_cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        query = update.callback_query
        await query.answer("عملیات لغو شد")
        await query.edit_message_text("عملیات لغو شد.", reply_markup=get_admin_panel_keyboard())
    elif update.message:
        await update.message.reply_text("عملیات لغو شد.", reply_markup=get_admin_panel_keyboard())
    context.user_data.clear()
    return ConversationHandler.END

# ===================== NEW FEATURE: TRX Payment Flow =====================
async def card_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    message = (
        f"👤کاربر {user.first_name} جهت جلوگیری از فیشینگ باید شماره ی خود را به اشتراک بگذارید ✅\n\n"
        "🌐*توجه داشته باشید هیچ فردی به شماره ی شما دسترسی ندارد و شماره پیش ما محفوظ میماند!*"
    )
    contact_button = KeyboardButton("اشتراک گذاری شماره", request_contact=True)
    reply_markup = ReplyKeyboardMarkup([[contact_button]], resize_keyboard=True, one_time_keyboard=True)
    await query.edit_message_text("لطفاً به پیام پایین پاسخ دهید.")
    await context.bot.send_message(chat_id=user.id, text=message, reply_markup=reply_markup, parse_mode="Markdown")

async def crypto_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("برای پرداخت ارزی، لطفاً بر روی دکمه زیر کلیک کنید:", reply_markup=get_trx_initial_keyboard())

async def trx_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("لطفاً یک گزینه از موارد زیر را انتخاب کنید:", reply_markup=get_trx_option_keyboard())
    return TRX_PAYMENT_MENU

async def trx_fixed_amount_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data
    fixed_amount = int(data.split("_")[1])
    try:
        url = 'https://api.nobitex.ir/market/stats'
        payload = {'srcCurrency': 'trx', 'dstCurrency': 'irt'}
        response = requests.post(url, data=payload)
        response.raise_for_status()
        data_api = response.json()
        price = float(data_api['stats']['trx-irt']['latest'])
    except Exception as e:
        await query.edit_message_text("❌ خطا در دریافت قیمت ترون. لطفاً بعداً امتحان کنید.", parse_mode="Markdown", reply_markup=get_inline_main_menu())
        return ConversationHandler.END
    rial_amount = fixed_amount * 10
    trx_amount = (rial_amount / price) * 1.1  # اضافه کردن ۱۰٪ ترون
    user_first_name = update.effective_user.first_name
    message = (
        f"🌐کاربر {user_first_name} لطفاً مبلغ *{trx_amount:.4f}* TRX را به ولت زیر انتقال دهید و هش تراکنش را به پیوی ادمین ارسال کنید✅\n\n"
        "🔺ولت : `TDCLoTL67gqThYBz69qXDo7nwvg7vEqDM1`"
    )
    support_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👤پشتیبانی", url="https://t.me/food_center_Support")]
    ])
    await query.edit_message_text(message, parse_mode="Markdown", reply_markup=support_keyboard)
    return ConversationHandler.END

async def trx_custom_amount_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("لطفاً مبلغ مورد نظر (بین 15000 تا 1000000 تومان) را وارد کنید:", reply_markup=get_admin_cancel_keyboard())
    return TRX_CUSTOM_INPUT

async def trx_custom_amount_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    try:
        custom_amount = float(text)
    except ValueError:
        await update.message.reply_text("❌ لطفاً یک عدد معتبر وارد کنید!")
        return TRX_CUSTOM_INPUT
    if not (15000 <= custom_amount <= 1000000):
        await update.message.reply_text("کاربر عزیز مبلغ شما باید عددی بین 15000 تا 1000000 باشد🔴")
        return TRX_CUSTOM_INPUT
    try:
        url = 'https://api.nobitex.ir/market/stats'
        payload = {'srcCurrency': 'trx', 'dstCurrency': 'irt'}
        response = requests.post(url, data=payload)
        response.raise_for_status()
        data_api = response.json()
        price = float(data_api['stats']['trx-irt']['latest'])
    except Exception as e:
        await update.message.reply_text("❌ خطا در دریافت قیمت ترون. لطفاً بعداً امتحان کنید.", parse_mode="Markdown", reply_markup=get_inline_main_menu())
        return ConversationHandler.END
    rial_amount = custom_amount * 10
    trx_amount = (rial_amount / price) * 1.1
    user_first_name = update.effective_user.first_name
    message = (
        f"🌐کاربر {user_first_name} لطفاً مبلغ *{trx_amount:.4f}* TRX را به ولت زیر انتقال دهید و هش تراکنش را به پیوی ادمین ارسال کنید✅\n\n"
        "🔺ولت : `TDCLoTL67gqThYBz69qXDo7nwvg7vEqDM1`"
    )
    support_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👤پشتیبانی", url="https://t.me/food_center_Support")]
    ])
    await update.message.reply_text(message, parse_mode="Markdown", reply_markup=support_keyboard)
    return ConversationHandler.END

# =====================================================================
# Membership, Admin, and Other Handlers (unchanged parts)
# =====================================================================
async def panel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id == ADMIN_ID:
        await update.message.reply_text("پنل مدیریت", reply_markup=get_admin_panel_keyboard())
    else:
        await update.message.reply_text("شما به این بخش دسترسی ندارید.")

async def admin_cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        query = update.callback_query
        await query.answer("عملیات لغو شد")
        await query.edit_message_text("عملیات لغو شد.", reply_markup=get_admin_panel_keyboard())
    elif update.message:
        await update.message.reply_text("عملیات لغو شد.", reply_markup=get_admin_panel_keyboard())
    context.user_data.clear()
    return ConversationHandler.END

if __name__ == '__main__':
    async def main():
        init_db()
        load_user_data()
        load_registered_users()
        load_banned_users()  # بارگذاری کاربران مسدود ذخیره شده از دیتابیس
        application = Application.builder().token("7648152793:AAFKcpf87FqEevQ0GPViokkt8N_j9FG5Uv4").build()
        
        # ---------------- User Handlers ----------------
        application.add_handler(CommandHandler("start", start))
        application.add_handler(MessageHandler(filters.Regex("^خرید محصول 🛍$"), buy_product))
        application.add_handler(CallbackQueryHandler(buy_callback, pattern="^buy_"))
        application.add_handler(MessageHandler(filters.Regex("^👤 حساب کاربری$"), user_profile))
        application.add_handler(MessageHandler(filters.Regex("^شارژ حساب 💳$"), charge_account))
        application.add_handler(MessageHandler(filters.Regex("^پشتیبانی 👨‍💻$"), support_handler))
        application.add_handler(MessageHandler(filters.Regex("^📣 کانال های ما$"), channel_handler))
        application.add_handler(MessageHandler(filters.CONTACT, contact_handler))
        
        gift_code_conv = ConversationHandler(
            entry_points=[MessageHandler(filters.Regex("^🎁کد هدیه🎁$"), gift_code_handler)],
            states={
                GIFT_CODE_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, gift_code_redeem_handler)]
            },
            fallbacks=[
                CallbackQueryHandler(admin_cancel_handler, pattern="^admin_cancel$"),
                CommandHandler("cancel", admin_cancel_handler)
            ]
        )
        application.add_handler(gift_code_conv)
        
        application.add_handler(CallbackQueryHandler(charge_callback, pattern="^charge_"))
        application.add_handler(CallbackQueryHandler(main_menu_handler, pattern="^menu_main$"))
        application.add_handler(CallbackQueryHandler(profile_charge_callback, pattern="^profile_charge$"))
        application.add_handler(CallbackQueryHandler(membership_check_callback, pattern="^check_membership$"))
        # Register new membership confirmation handler
        application.add_handler(CallbackQueryHandler(confirm_membership_callback, pattern="^confirm_membership$"))
        
        # ---------------- Admin Panel Command ----------------
        application.add_handler(CommandHandler("panel", panel_handler))
        
        admin_add_code_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(admin_add_code_entry, pattern="^admin_add_code$")],
            states={
                ADD_CODE_SERVICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_receive_service_name)],
                ADD_CODE_FILEPATH: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_code_filepath_handler)]
            },
            fallbacks=[
                CallbackQueryHandler(admin_cancel_handler, pattern="^admin_cancel$"),
                CommandHandler("cancel", admin_cancel_handler)
            ]
        )
        application.add_handler(admin_add_code_conv)
        
        admin_add_credit_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(admin_add_credit_start, pattern="^admin_add_credit$")],
            states={
                ADMIN_ADD_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_credit_amount)],
                ADMIN_ADD_USERID: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_credit_userid)]
            },
            fallbacks=[
                CallbackQueryHandler(admin_cancel_handler, pattern="^admin_cancel$"),
                CommandHandler("cancel", admin_cancel_handler)
            ]
        )
        application.add_handler(admin_add_credit_conv)
        
        admin_subtract_credit_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(admin_subtract_credit_start, pattern="^admin_subtract_credit$")],
            states={
                ADMIN_SUB_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_subtract_credit_amount)],
                ADMIN_SUB_USERID: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_subtract_credit_userid)]
            },
            fallbacks=[
                CallbackQueryHandler(admin_cancel_handler, pattern="^admin_cancel$"),
                CommandHandler("cancel", admin_cancel_handler)
            ]
        )
        application.add_handler(admin_subtract_credit_conv)
        
        admin_unblock_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(admin_unblock_start, pattern="^admin_unblock$")],
            states={
                ADMIN_UNBLOCK_USERID: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_unblock_userid)]
            },
            fallbacks=[
                CallbackQueryHandler(admin_cancel_handler, pattern="^admin_cancel$"),
                CommandHandler("cancel", admin_cancel_handler)
            ]
        )
        application.add_handler(admin_unblock_conv)
        
        admin_ban_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(admin_ban_start, pattern="^admin_ban$")],
            states={
                ADMIN_BAN_USERID: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_ban_userid)]
            },
            fallbacks=[
                CallbackQueryHandler(admin_cancel_handler, pattern="^admin_cancel$"),
                CommandHandler("cancel", admin_cancel_handler)
            ]
        )
        application.add_handler(admin_ban_conv)
        
        admin_message_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(admin_message_start, pattern="^admin_message$")],
            states={
                ADMIN_MESSAGE_USERID: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_message_userid)],
                ADMIN_MESSAGE_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_message_text)]
            },
            fallbacks=[
                CallbackQueryHandler(admin_cancel_handler, pattern="^admin_cancel$"),
                CommandHandler("cancel", admin_cancel_handler)
            ]
        )
        application.add_handler(admin_message_conv)
        
        admin_balance_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(admin_balance_start, pattern="^admin_balance$")],
            states={
                ADMIN_BALANCE_USERID: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_balance_userid)]
            },
            fallbacks=[
                CallbackQueryHandler(admin_cancel_handler, pattern="^admin_cancel$"),
                CommandHandler("cancel", admin_cancel_handler)
            ]
        )
        application.add_handler(admin_balance_conv)
        
        admin_recent_purchases_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(admin_recent_purchases_start, pattern="^admin_recent_purchases$")],
            states={
                ADMIN_RECENT_PURCHASES_USERID: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_recent_purchases_userid)]
            },
            fallbacks=[
                CallbackQueryHandler(admin_cancel_handler, pattern="^admin_cancel$"),
                CommandHandler("cancel", admin_cancel_handler)
            ]
        )
        application.add_handler(admin_recent_purchases_conv)
        
        admin_broadcast_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(admin_broadcast_start, pattern="^admin_broadcast$")],
            states={
                ADMIN_BROADCAST_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_broadcast_message)]
            },
            fallbacks=[
                CallbackQueryHandler(admin_cancel_handler, pattern="^admin_cancel$"),
                CommandHandler("cancel", admin_cancel_handler)
            ]
        )
        application.add_handler(admin_broadcast_conv)
        
        admin_forward_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(admin_forward_start, pattern="^admin_forward$")],
            states={
                ADMIN_FORWARD_MESSAGE: [MessageHandler(filters.ALL & ~filters.COMMAND, admin_forward_message)]
            },
            fallbacks=[
                CallbackQueryHandler(admin_cancel_handler, pattern="^admin_cancel$"),
                CommandHandler("cancel", admin_cancel_handler)
            ]
        )
        application.add_handler(admin_forward_conv)
        
        admin_increase_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(admin_increase_start, pattern="^admin_increase_price$")],
            states={
                INCREASE_PRODUCT_SELECT: [CallbackQueryHandler(admin_increase_select, pattern="^increase_")],
                INCREASE_PRODUCT_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_increase_input)]
            },
            fallbacks=[
                CallbackQueryHandler(admin_cancel_handler, pattern="^admin_cancel$"),
                CommandHandler("cancel", admin_cancel_handler)
            ]
        )
        application.add_handler(admin_increase_conv)
        
        admin_decrease_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(admin_decrease_start, pattern="^admin_decrease_price$")],
            states={
                DECREASE_PRODUCT_SELECT: [CallbackQueryHandler(admin_decrease_select, pattern="^decrease_")],
                DECREASE_PRODUCT_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_decrease_input)]
            },
            fallbacks=[
                CallbackQueryHandler(admin_cancel_handler, pattern="^admin_cancel$"),
                CommandHandler("cancel", admin_cancel_handler)
            ]
        )
        application.add_handler(admin_decrease_conv)
        
        admin_delete_code_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(admin_delete_code_start, pattern="^admin_delete_code$")],
            states={
                ADMIN_DELETE_CODE_SERVICE: [CallbackQueryHandler(admin_delete_code_select, pattern="^delete_")],
                ADMIN_DELETE_CODE_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_delete_code_input)]
            },
            fallbacks=[
                CallbackQueryHandler(admin_cancel_handler, pattern="^admin_cancel$"),
                CommandHandler("cancel", admin_cancel_handler)
            ]
        )
        application.add_handler(admin_delete_code_conv)
        
        admin_create_gift_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(admin_create_gift_start, pattern="^admin_create_gift$")],
            states={
                ADMIN_GIFT_CHOICE: [CallbackQueryHandler(admin_gift_choice_selection, pattern="^admin_gift_(manual|random)$")],
                ADMIN_CREATE_GIFT_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_create_gift_amount)],
                ADMIN_CREATE_GIFT_USAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_create_gift_usage)],
                RANDOM_WINNER_COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_gift_random_winner_count)],
                RANDOM_CREDIT_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_gift_random_amount_handler)]
            },
            fallbacks=[
                CallbackQueryHandler(admin_cancel_handler, pattern="^admin_cancel$"),
                CommandHandler("cancel", admin_cancel_handler)
            ]
        )
        application.add_handler(admin_create_gift_conv)
        
        search_user_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(search_user_start, pattern="^search_user_button$")],
            states={
                SEARCH_USER_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_user_input)]
            },
            fallbacks=[
                CallbackQueryHandler(admin_cancel_handler, pattern="^admin_cancel$"),
                CommandHandler("cancel", admin_cancel_handler)
            ]
        )
        application.add_handler(search_user_conv)
        
        # ---------------- Conversation Handlers for Button Management ----------------
        admin_add_button_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(admin_add_button_start, pattern="^admin_add_button$")],
            states={
                ADD_BUTTON_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_receive_button_name)],
                ADD_BUTTON_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_receive_button_price)]
            },
            fallbacks=[
                CallbackQueryHandler(admin_cancel_handler, pattern="^admin_cancel$"),
                CommandHandler("cancel", admin_cancel_handler)
            ]
        )
        application.add_handler(admin_add_button_conv)
        
        admin_remove_button_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(admin_remove_button_start, pattern="^admin_remove_button$")],
            states={
                REMOVE_BUTTON_SELECT: [CallbackQueryHandler(admin_remove_button_select, pattern="^remove_")]
            },
            fallbacks=[
                CallbackQueryHandler(admin_cancel_handler, pattern="^admin_cancel$"),
                CommandHandler("cancel", admin_cancel_handler)
            ]
        )
        application.add_handler(admin_remove_button_conv)
        
        admin_rename_button_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(admin_rename_button_start, pattern="^admin_rename_button$")],
            states={
                RENAME_BUTTON_SELECT: [CallbackQueryHandler(admin_rename_button_select, pattern="^rename_")],
                RENAME_BUTTON_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_rename_button_input)]
            },
            fallbacks=[
                CallbackQueryHandler(admin_cancel_handler, pattern="^admin_cancel$"),
                CommandHandler("cancel", admin_cancel_handler)
            ]
        )
        application.add_handler(admin_rename_button_conv)
        
        application.add_handler(CallbackQueryHandler(admin_send_users_txt, pattern="^admin_users_txt$"))
        application.add_handler(CallbackQueryHandler(admin_send_phone_file_handler, pattern="^admin_phone_file$"))
        application.add_handler(CallbackQueryHandler(admin_turn_on_bot, pattern="^admin_turn_on_bot$"))
        application.add_handler(CallbackQueryHandler(admin_turn_off_bot, pattern="^admin_turn_off_bot$"))
        application.add_handler(CallbackQueryHandler(admin_stats_panel_handler, pattern="^admin_stats$"))
        application.add_handler(CallbackQueryHandler(stats_products_handler, pattern="^stats_products$"))
        application.add_handler(CallbackQueryHandler(stats_product_details_handler, pattern="^stats_product_"))
        application.add_handler(CallbackQueryHandler(sales_stats_handler, pattern="^sales_stats_"))
        application.add_handler(CallbackQueryHandler(stats_users_handler, pattern="^stats_users$"))
        application.add_handler(CallbackQueryHandler(stats_overall_handler, pattern="^stats_overall$"))
        application.add_handler(CallbackQueryHandler(admin_backup_db_handler, pattern="^admin_backup_db$"))
        # NEW: Handler for banned users list
        application.add_handler(CallbackQueryHandler(admin_banned_list_handler, pattern="^admin_banned_list_"))
        
        application.add_handler(CallbackQueryHandler(admin_cancel_handler, pattern="^admin_cancel$"))
        
        # ===================== NEW FEATURE: TRX Payment Flow =====================
        application.add_handler(CallbackQueryHandler(card_payment_handler, pattern="^card_payment$"))
        application.add_handler(CallbackQueryHandler(crypto_payment_handler, pattern="^crypto_payment$"))
        
        trx_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(trx_payment_handler, pattern="^trx_payment$")],
            states={
                TRX_PAYMENT_MENU: [
                    CallbackQueryHandler(trx_fixed_amount_handler, pattern="^trx_\\d+$"),
                    CallbackQueryHandler(trx_custom_amount_prompt, pattern="^trx_custom$")
                ],
                TRX_CUSTOM_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, trx_custom_amount_handler)]
            },
            fallbacks=[
                CallbackQueryHandler(admin_cancel_handler, pattern="^admin_cancel$"),
                CommandHandler("cancel", admin_cancel_handler)
            ]
        )
        application.add_handler(trx_conv)
        
        await application.run_polling()
    asyncio.run(main())