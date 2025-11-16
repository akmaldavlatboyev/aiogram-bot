import asyncio
import sqlite3
import logging
import os
import aiohttp
import html
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, CallbackQuery
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from dotenv import load_dotenv
from functools import wraps

# Sozlamalar
load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_IDS = [7384369025]  # Sizning ID ingiz

# Loggerni sozlash
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Botni yaratish
try:
    bot = Bot(token=BOT_TOKEN)
except Exception as e:
    logging.error(f"Bot yaratishda xatolik: {e}")
    exit(1)

dp = Dispatcher(storage=MemoryStorage())

# Xavfsizlik funksiyalari
def clean_input(text: str) -> str:
    """Xavfli belgilarni olib tashlash"""
    return html.escape(text.strip())

# Ma'lumotlar bazasi funksiyalari
def create_db():
    try:
        conn = sqlite3.connect('movies.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS movies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                file_id TEXT NOT NULL,
                created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE,
                username TEXT,
                full_name TEXT,
                joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                url TEXT,
                created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Dastlabki kanalni qo'shish
        cursor.execute('''
            INSERT OR IGNORE INTO channels (username, url) 
            VALUES (?, ?)
        ''', ('football_zoneX', 'https://t.me/football_zoneX'))
        
        conn.commit()
        conn.close()
        logging.info("Ma'lumotlar bazasi yaratildi")
    except Exception as e:
        logging.error(f"Ma'lumotlar bazasini yaratishda xatolik: {e}")

create_db()

# FSM holatlari
class AdminStates(StatesGroup):
    waiting_for_movie_title = State()
    waiting_for_movie_description = State()
    waiting_for_movie_file = State()
    waiting_for_broadcast = State()
    waiting_for_delete_movie = State()
    waiting_for_channel_username = State()
    waiting_for_channel_url = State()
    waiting_for_delete_channel = State()

# Helper funksiyalari
def get_admin_ids():
    return ADMIN_IDS

def get_channels():
    try:
        conn = sqlite3.connect('movies.db')
        cursor = conn.cursor()
        cursor.execute('SELECT username, url FROM channels')
        channels = cursor.fetchall()
        conn.close()
        return [{"username": channel[0], "url": channel[1]} for channel in channels]
    except:
        return []

def get_all_users():
    try:
        conn = sqlite3.connect('movies.db')
        cursor = conn.cursor()
        cursor.execute('SELECT user_id FROM users')
        users = [row[0] for row in cursor.fetchall()]
        conn.close()
        return users
    except:
        return []

def get_movies_list():
    try:
        conn = sqlite3.connect('movies.db')
        cursor = conn.cursor()
        cursor.execute('SELECT id, title FROM movies ORDER BY id')
        movies = cursor.fetchall()
        conn.close()
        return movies
    except:
        return []

def get_monthly_users():
    try:
        conn = sqlite3.connect('movies.db')
        cursor = conn.cursor()
        first_day_of_month = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        cursor.execute('SELECT COUNT(*) FROM users WHERE joined_date >= ?', (first_day_of_month.isoformat(),))
        monthly_users = cursor.fetchone()[0]
        conn.close()
        return monthly_users
    except:
        return 0

def get_total_users():
    try:
        conn = sqlite3.connect('movies.db')
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM users')
        total_users = cursor.fetchone()[0]
        conn.close()
        return total_users
    except:
        return 0

# Kanallarga obuna tekshirish
async def check_user_subscription(user_id: int):
    channels = get_channels()
    if not channels:
        return []
    
    not_subscribed = []
    for channel in channels:
        try:
            channel_username = channel['username']
            if channel_username.startswith('@'):
                channel_username = channel_username[1:]
            
            chat = await bot.get_chat(f"@{channel_username}")
            member = await chat.get_member(user_id)
            if member.status in ['left', 'kicked']:
                not_subscribed.append(channel)
        except Exception as e:
            logging.warning(f"Kanal tekshirishda xatolik {channel['username']}: {str(e)[:100]}")
            not_subscribed.append(channel)
    
    return not_subscribed

# Bot admin tekshirishi
async def is_bot_admin_in_channel(channel_username: str) -> bool:
    try:
        if channel_username.startswith('@'):
            channel_username = channel_username[1:]
        
        chat = await bot.get_chat(f"@{channel_username}")
        bot_member = await chat.get_member((await bot.get_me()).id)
        return bot_member.status in ['administrator', 'creator']
    except Exception as e:
        logging.error(f"Bot adminligini tekshirishda xatolik: {e}")
        return False

# Keyboardlar
def get_main_menu_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📝 Kino kodini kiritish")]
        ],
        resize_keyboard=True
    )

def get_admin_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎬 Kino qo'shish"), KeyboardButton(text="🗑 Kino o'chirish")],
            [KeyboardButton(text="📊 Statistika"), KeyboardButton(text="📢 Kanallar boshqaruvi")],
            [KeyboardButton(text="📨 Barchaga xabar yuborish"), KeyboardButton(text="📋 Kino ro'yxati")],
            [KeyboardButton(text="🔙 Asosiy menyu")]
        ],
        resize_keyboard=True
    )

def get_channels_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Kanal qo'shish"), KeyboardButton(text="🗑 Kanal o'chirish")],
            [KeyboardButton(text="📋 Kanallar ro'yxati"), KeyboardButton(text="🔙 Orqaga")]
        ],
        resize_keyboard=True
    )

def get_cancel_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="❌ Bekor qilish")]
        ],
        resize_keyboard=True
    )

# Asosiy menyu
async def show_main_menu(chat_id: int):
    try:
        await bot.send_message(
            chat_id, 
            "🎬 <b>Asosiy menyu</b>\n\nKino kodini kiriting:",
            parse_mode="HTML",
            reply_markup=get_main_menu_keyboard()
        )
    except Exception as e:
        logging.error(f"Main menu xatosi: {e}")

# Start komandasi
@dp.message(CommandStart())
async def start_handler(message: Message):
    user_id = message.from_user.id
    
    try:
        # Foydalanuvchini qo'shish
        conn = sqlite3.connect('movies.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO users (user_id, username, full_name, last_active) 
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ''', (user_id, message.from_user.username, clean_input(message.from_user.full_name)))
        conn.commit()
        conn.close()

    
        # Kanallarni tekshirish
        not_subscribed = await check_user_subscription(user_id)
        
        if not_subscribed:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[])
            for channel in not_subscribed:
                keyboard.inline_keyboard.append([
                    InlineKeyboardButton(text=f"📢 {channel['username']}", url=channel['url'])
                ])
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_subscription")
            ])
            await message.answer(
                "🎬 Xush kelibsiz! Botdan foydalanish uchun kanallarga obuna bo'ling:",
                reply_markup=keyboard
            )
        else:
            await show_main_menu(user_id)
            
    except Exception as e:
        logging.error(f"Start handler xatosi: {e}")
        await message.answer("Xush kelibsiz! Kino kodini kiriting.")

    # Adminlarga bildirishnoma yuborish

    for admin_id in get_admin_ids():
        try:
            await bot.send_message(
                admin_id,
                f"👤 Yangi foydalanuvchi botga kirdi:\n\n"
                f"🆔 ID: {user_id}\n"
                f"👤 Username: @{message.from_user.username if message.from_user.username else 'Yo\'q'}\n"
                f"📛 F.I.O: {clean_input(message.from_user.full_name)}"
            )
        except Exception as e:
            logging.warning(f"Adminga xabar yuborishda xatolik: {e}")
# Obunani tekshirish
@dp.callback_query(F.data == "check_subscription")
async def check_subscription(callback: CallbackQuery):
    user_id = callback.from_user.id
    try:
        not_subscribed = await check_user_subscription(user_id)
        
        if not_subscribed:
            await callback.answer("Hali obuna bo'lmagansiz!", show_alert=True)
        else:
            await callback.message.delete()
            await show_main_menu(user_id)
    except Exception as e:
        await callback.answer("Tekshirildi", show_alert=False)
        await show_main_menu(user_id)

# Admin tekshiruvi
def admin_required(func):
    @wraps(func)
    async def wrapper(message: Message, *args, **kwargs):
        if message.from_user.id not in get_admin_ids():
            await message.answer("❌ Siz admin emassiz!")
            return
        return await func(message, *args, **kwargs)
    return wrapper

# Admin paneli
@dp.message(Command("admin"))
@admin_required
async def admin_command_handler(message: Message):
    await message.answer("👨‍💻 Admin paneli", reply_markup=get_admin_keyboard())

# Kino qo'shish
@dp.message(F.text == "🎬 Kino qo'shish")
@admin_required
async def add_movie_button(message: Message, state: FSMContext):
    await state.set_state(AdminStates.waiting_for_movie_title)
    await message.answer("🎬 Kino nomini kiriting:", reply_markup=get_cancel_keyboard())

@dp.message(AdminStates.waiting_for_movie_title)
async def process_movie_title(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("❌ Amal bekor qilindi.", reply_markup=get_admin_keyboard())
        return
        
    await state.update_data(title=clean_input(message.text))
    await state.set_state(AdminStates.waiting_for_movie_description)
    await message.answer("📖 Kino tavsifini kiriting:", reply_markup=get_cancel_keyboard())

@dp.message(AdminStates.waiting_for_movie_description)
async def process_movie_description(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("❌ Amal bekor qilindi.", reply_markup=get_admin_keyboard())
        return
        
    await state.update_data(description=clean_input(message.text))
    await state.set_state(AdminStates.waiting_for_movie_file)
    await message.answer("🎥 Kino faylini yuboring (video):", reply_markup=get_cancel_keyboard())

@dp.message(AdminStates.waiting_for_movie_file, F.video)
async def process_movie_file(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("❌ Amal bekor qilindi.", reply_markup=get_admin_keyboard())
        return
    
    data = await state.get_data()
    
    conn = sqlite3.connect('movies.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO movies (title, description, file_id)
        VALUES (?, ?, ?)
    ''', (data['title'], data['description'], message.video.file_id))
    conn.commit()
    movie_id = cursor.lastrowid
    conn.close()
    
    await state.clear()
    await message.answer(
        f"✅ Kino muvaffaqiyatli qo'shildi!\n"
        f"🎬 Kino raqami: {movie_id}",
        reply_markup=get_admin_keyboard()
    )

# Kino o'chirish
@dp.message(F.text == "🗑 Kino o'chirish")
@admin_required
async def delete_movie_button(message: Message, state: FSMContext):
    await state.set_state(AdminStates.waiting_for_delete_movie)
    await message.answer("🗑 O'chirish uchun kino raqamini kiriting:", reply_markup=get_cancel_keyboard())

@dp.message(AdminStates.waiting_for_delete_movie)
async def process_delete_movie(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("❌ Amal bekor qilindi.", reply_markup=get_admin_keyboard())
        return
        
    try:
        movie_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Iltimos, faqat raqam kiriting!", reply_markup=get_admin_keyboard())
        await state.clear()
        return

    conn = sqlite3.connect('movies.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM movies WHERE id = ?', (movie_id,))
    movie = cursor.fetchone()

    if movie:
        cursor.execute('DELETE FROM movies WHERE id = ?', (movie_id,))
        conn.commit()
        await message.answer(
            f"✅ Kino muvaffaqiyatli o'chirildi!\n"
            f"🎬 Nomi: {movie[1]}\n"
            f"🔢 Raqami: {movie_id}",
            reply_markup=get_admin_keyboard()
        )
    else:
        await message.answer("❌ Bu raqamli kino topilmadi.", reply_markup=get_admin_keyboard())

    conn.close()
    await state.clear()

# Kino ro'yxati
@dp.message(F.text == "📋 Kino ro'yxati")
@admin_required
async def show_movies_list(message: Message):
    movies = get_movies_list()
    
    if not movies:
        await message.answer("📭 Hozircha hech qanday kino mavjud emas.")
        return
    
    text = "📋 <b>Kinolar ro'yxati:</b>\n\n"
    for movie in movies:
        text += f"🎬 <b>{movie[0]}</b> - {movie[1]}\n"
    
    if len(text) > 4000:
        parts = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for part in parts:
            await message.answer(part, parse_mode="HTML")
    else:
        await message.answer(text, parse_mode="HTML")

# Statistika
@dp.message(F.text == "📊 Statistika")
@admin_required
async def show_statistics(message: Message):
    monthly_users = get_monthly_users()
    total_users = get_total_users()
    
    conn = sqlite3.connect('movies.db')
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM movies')
    total_movies = cursor.fetchone()[0]
    conn.close()
    
    await message.answer(
        f"📊 <b>Bot statistikasi</b>\n\n"
        f"👥 Jami foydalanuvchilar: <b>{total_users}</b>\n"
        f"📈 Oylik obunachilar: <b>{monthly_users}</b>\n"
        f"🎬 Jami kinolar: <b>{total_movies}</b>",
        parse_mode="HTML"
    )

# Kanallar boshqaruvi
@dp.message(F.text == "📢 Kanallar boshqaruvi")
@admin_required
async def channels_management_button(message: Message):
    await message.answer("📢 Kanallar boshqaruvi", reply_markup=get_channels_keyboard())

# Kanal qo'shish
@dp.message(F.text == "➕ Kanal qo'shish")
@admin_required
async def add_channel_button(message: Message, state: FSMContext):
    await state.set_state(AdminStates.waiting_for_channel_username)
    await message.answer("📢 Kanal username ni kiriting (masalan: @kanal_nomi):", reply_markup=get_cancel_keyboard())

@dp.message(AdminStates.waiting_for_channel_username)
async def process_channel_username(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("❌ Amal bekor qilindi.", reply_markup=get_channels_keyboard())
        return
        
    username = clean_input(message.text)
    
    is_admin = await is_bot_admin_in_channel(username)
    if not is_admin:
        await message.answer("❌ Bot bu kanalda admin emas! Iltimos, avval botni kanalga admin qiling.")
        await state.clear()
        return
        
    await state.update_data(username=username)
    await state.set_state(AdminStates.waiting_for_channel_url)
    await message.answer("🔗 Kanal linkini kiriting:", reply_markup=get_cancel_keyboard())

@dp.message(AdminStates.waiting_for_channel_url)
async def process_channel_url(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("❌ Amal bekor qilindi.", reply_markup=get_channels_keyboard())
        return
        
    data = await state.get_data()
    
    conn = sqlite3.connect('movies.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO channels (username, url)
        VALUES (?, ?)
    ''', (data['username'], clean_input(message.text)))
    conn.commit()
    conn.close()
    
    await state.clear()
    await message.answer(
        f"✅ Kanal muvaffaqiyatli qo'shildi!\n"
        f"📢 Username: {data['username']}",
        reply_markup=get_channels_keyboard()
    )

# Kanal o'chirish
@dp.message(F.text == "🗑 Kanal o'chirish")
@admin_required
async def delete_channel_button(message: Message, state: FSMContext):
    await state.set_state(AdminStates.waiting_for_delete_channel)
    await message.answer("🗑 O'chirish uchun kanal username ni kiriting:", reply_markup=get_cancel_keyboard())

@dp.message(AdminStates.waiting_for_delete_channel)
async def process_delete_channel(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("❌ Amal bekor qilindi.", reply_markup=get_channels_keyboard())
        return
        
    username = clean_input(message.text.strip())
    
    conn = sqlite3.connect('movies.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM channels WHERE username = ?', (username,))
    channel = cursor.fetchone()

    if channel:
        cursor.execute('DELETE FROM channels WHERE username = ?', (username,))
        conn.commit()
        await message.answer(
            f"✅ Kanal muvaffaqiyatli o'chirildi!\n"
            f"📢 Username: {username}",
            reply_markup=get_channels_keyboard()
        )
    else:
        await message.answer("❌ Bu username li kanal topilmadi.", reply_markup=get_channels_keyboard())

    conn.close()
    await state.clear()

# Kanallar ro'yxati
@dp.message(F.text == "📋 Kanallar ro'yxati")
@admin_required
async def show_channels_list(message: Message):
    channels = get_channels()
    
    if not channels:
        await message.answer("📭 Hozircha hech qanday kanal mavjud emas.")
        return
    
    text = "📋 <b>Kanallar ro'yxati:</b>\n\n"
    for channel in channels:
        text += f"📢 {channel['username']}\n"
        text += f"🔗 {channel['url']}\n\n"
    
    await message.answer(text, parse_mode="HTML")

# Barchaga xabar yuborish
@dp.message(F.text == "📨 Barchaga xabar yuborish")
@admin_required
async def broadcast_message_button(message: Message, state: FSMContext):
    await state.set_state(AdminStates.waiting_for_broadcast)
    await message.answer("📨 Barcha foydalanuvchilarga yuboriladigan xabarni kiriting:", reply_markup=get_cancel_keyboard())

@dp.message(AdminStates.waiting_for_broadcast)
async def process_broadcast_message(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("❌ Amal bekor qilindi.", reply_markup=get_admin_keyboard())
        return
        
    users = get_all_users()
    success_count = 0
    fail_count = 0
    
    await message.answer(f"📨 Xabar {len(users)} ta foydalanuvchiga yuborilmoqda...")
    
    for user_id in users:
        try:
            await bot.send_message(user_id, f"📢 {clean_input(message.text)}")
            success_count += 1
            await asyncio.sleep(0.1)
        except Exception as e:
            fail_count += 1
    
    await state.clear()
    await message.answer(
        f"✅ Xabar yuborish yakunlandi!\n\n"
        f"✅ Muvaffaqiyatli: {success_count}\n"
        f"❌ Xatolik: {fail_count}",
        reply_markup=get_admin_keyboard()
    )

# Kino kodini kiritish tugmasini qayta ishlash
@dp.message(F.text == "📝 Kino kodini kiritish")
async def request_movie_code(message: Message):
    await message.answer("🎬 Iltimos, kino raqamini kiriting:")

# Kino raqamini qabul qilish
@dp.message(F.text & ~F.command)
async def handle_movie_number(message: Message):
    user_id = message.from_user.id
    text = message.text.strip()
    
    admin_buttons = [
        "🎬 Kino qo'shish", "🗑 Kino o'chirish", "📊 Statistika", "📢 Kanallar boshqaruvi",
        "📨 Barchaga xabar yuborish", "📋 Kino ro'yxati", "🔙 Asosiy menyu",
        "➕ Kanal qo'shish", "🗑 Kanal o'chirish", "📋 Kanallar ro'yxati", "🔙 Orqaga",
        "❌ Bekor qilish", "📝 Kino kodini kiritish"
    ]
    
    if text in admin_buttons:
        return
    
    if not text.isdigit():
        await message.answer("❌ Iltimos, faqat raqam kiriting!")
        return
    
    content_id = int(text)
    
    try:
        # Foydalanuvchi faolligini yangilash
        conn = sqlite3.connect('movies.db')
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
        
        # Kanallarga obuna tekshirish
        not_subscribed = await check_user_subscription(user_id)
        
        if not_subscribed:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[])
            for channel in not_subscribed:
                keyboard.inline_keyboard.append([
                    InlineKeyboardButton(text=f"📢 {channel['username']}", url=channel['url'])
                ])
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_subscription")
            ])
            await message.answer("❌ Iltimos, avval barcha kanallarga obuna bo'ling!", reply_markup=keyboard)
            return
        
        # Kino qidirish
        conn = sqlite3.connect('movies.db')
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM movies WHERE id = ?', (content_id,))
        movie = cursor.fetchone()
        conn.close()

        if movie:
            await bot.send_video(
                chat_id=user_id,
                video=movie[3],
                caption=f"🎬 {movie[1]}\n\n{movie[2]}\n\n🔢 Kino raqami: {movie[0]}"
            )
            return
        
        await message.answer("❌ Noto'g'ri raqam! Bu raqamli kino mavjud emas.")
        
    except Exception as e:
        logging.error(f"Movie search xatosi: {e}")
        await message.answer("❌ Xatolik yuz berdi. Qaytadan urinib ko'ring.")

# Bekor qilish
@dp.message(F.text == "❌ Bekor qilish")
async def cancel_handler(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is not None:
        await state.clear()
    
    if message.from_user.id in get_admin_ids():
        await message.answer("❌ Amal bekor qilindi.", reply_markup=get_admin_keyboard())
    else:
        await message.answer("❌ Amal bekor qilindi.", reply_markup=get_main_menu_keyboard())

# Orqaga tugmasi
@dp.message(F.text == "🔙 Orqaga")
async def back_handler(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is not None:
        await state.clear()
    
    if message.from_user.id in get_admin_ids():
        await message.answer("👨‍💻 Admin paneli", reply_markup=get_admin_keyboard())

# Asosiy menyuga qaytish
@dp.message(F.text == "🔙 Asosiy menyu")
async def back_to_main_handler(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is not None:
        await state.clear()
    
    await show_main_menu(message.from_user.id)

# Global error handler
@dp.error()
async def global_error_handler(event: types.ErrorEvent):
    logging.error(f"Global xatolik: {event.exception}", exc_info=True)
    
    try:
        if hasattr(event.update, 'message'):
            await event.update.message.answer("❌ Texnik xatolik yuz berdi. Iltimos, keyinroq urinib ko'ring.")
    except:
        pass

# Botni ishga tushirish
async def main():
    logging.info("Bot ishga tushmoqda...")
    
    try:
        bot_info = await bot.get_me()
        logging.info(f"Bot ishga tushdi: @{bot_info.username}")
        await dp.start_polling(bot, skip_updates=True)
        
    except Exception as e:
        logging.error(f"Bot ishga tushirishda xatolik: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Bot to'xtatildi")
    except Exception as e:
        logging.error(f"Global xatolik: {e}")