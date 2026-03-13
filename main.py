import asyncio
import logging
import os
import html
import time
import json
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (
    Message, CallbackQuery, ReplyKeyboardMarkup, 
    KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.base import StorageKey
from aiogram.filters import CommandStart, Command
from mcstatus import JavaServer

# --- Конфигурация ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "") 
MAIN_ADMIN_ID = int(os.getenv("MAIN_ADMIN_ID", 0))
MOD_GROUP_ID = int(os.getenv("MOD_GROUP_ID", 0))
_thread_id = os.getenv("MOD_THREAD_ID", "")
MOD_THREAD_ID = int(_thread_id) if _thread_id and _thread_id.lower() != "none" else None

CHANNEL_ID = os.getenv("CHANNEL_ID", "") 
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://t.me/misacraft1")

SERVER_IP = "play.misacraft.online"
SERVER_VERSION = "1.21.10"
DONATE_LINK = "https://site.misacraft.online/"
RULES_LINK = "https://site.misacraft.online/"
DISCORD_LINK = "https://discord.gg/69Jf7R4JFF"

USERS_FILE = "users.txt"
TICKETS_JSON = "active_tickets.json"

TICKET_COOLDOWN = 300 
STATUS_COOLDOWN = 10  
user_cooldowns = {}    
status_cooldowns = {}  

# --- Хранение данных ---
def save_active_ticket(user_id: int, data: dict):
    tickets = {}
    if os.path.exists(TICKETS_JSON):
        try:
            with open(TICKETS_JSON, "r", encoding="utf-8") as f:
                tickets = json.load(f)
        except: pass
    tickets[str(user_id)] = data
    with open(TICKETS_JSON, "w", encoding="utf-8") as f:
        json.dump(tickets, f, ensure_ascii=False, indent=4)

def remove_active_ticket(user_id: int):
    if not os.path.exists(TICKETS_JSON): return
    try:
        with open(TICKETS_JSON, "r", encoding="utf-8") as f:
            tickets = json.load(f)
        if str(user_id) in tickets:
            del tickets[str(user_id)]
            with open(TICKETS_JSON, "w", encoding="utf-8") as f:
                json.dump(tickets, f, ensure_ascii=False, indent=4)
    except: pass

def get_all_active_tickets() -> dict:
    if not os.path.exists(TICKETS_JSON): return {}
    try:
        with open(TICKETS_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except: return {}

def add_user(user_id: int):
    users = set()
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r") as f:
                users = set(line.strip() for line in f if line.strip())
        except: pass
    if str(user_id) not in users:
        with open(USERS_FILE, "a") as f:
            f.write(f"{user_id}\n")

def get_all_users() -> list:
    if not os.path.exists(USERS_FILE): return []
    try:
        with open(USERS_FILE, "r") as f:
            return [int(uid) for uid in f.read().splitlines() if uid.strip().isdigit()]
    except: return []

# --- Состояния ---
class SupportStates(StatesGroup):
    waiting_for_question = State()
    in_ticket = State()

class AdminStates(StatesGroup):
    waiting_for_reply = State()
    waiting_for_broadcast = State()

# --- Клавиатуры ---
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🌐 Статус сервера"), KeyboardButton(text="ℹ️ FAQ")],
        [KeyboardButton(text="🆘 Написать в поддержку")]
    ],
    resize_keyboard=True
)

in_ticket_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🌐 Статус сервера"), KeyboardButton(text="ℹ️ FAQ")],
        [KeyboardButton(text="🔒 Закрыть обращение")]
    ],
    resize_keyboard=True
)

faq_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="🔗 Как подключиться?", callback_data="faq_connect")],
    [InlineKeyboardButton(text="📜 Правила сервера", url=RULES_LINK)],
    [InlineKeyboardButton(text="💎 Донат и услуги", url=DONATE_LINK)],
    [InlineKeyboardButton(text="👾 Наш Discord", url=DISCORD_LINK)]
])

def get_take_ticket_kb(user_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🙋‍♂️ Взять обращение", callback_data=f"take_ticket_{user_id}")]
    ])

def get_admin_ticket_kb(user_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Написать ответ", callback_data=f"reply_to_{user_id}")],
        [InlineKeyboardButton(text="❌ Завершить диалог", callback_data=f"close_ticket_{user_id}")]
    ])

def get_subscribe_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться на MisaCraft", url=CHANNEL_LINK)],
        [InlineKeyboardButton(text="🔄 Проверить подписку", callback_data="check_sub")]
    ])

# --- Проверки ---
async def is_subscribed(user_id: int, bot: Bot):
    if not CHANNEL_ID or user_id == MAIN_ADMIN_ID: return True
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status not in ['left', 'kicked']
    except: return True

# --- Обработчики ---
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
    current = await state.get_state()
    if current in [SupportStates.waiting_for_question.state, SupportStates.in_ticket.state]:
        data = await state.get_data()
        mod_id = data.get("mod_id")
        try:
            await bot.send_message(mod_id or MOD_GROUP_ID, f"⚠️ Игрок <code>{message.from_user.id}</code> нажал /start.", 
                                 message_thread_id=MOD_THREAD_ID if not mod_id else None, parse_mode="HTML")
        except: pass
    await state.clear()
    add_user(message.from_user.id)
    await message.answer(f"Привет, {html.escape(message.from_user.first_name)}! 👋\nДобро пожаловать в <b>MisaCraft</b>.", reply_markup=main_kb, parse_mode="HTML")

@router.message(F.text == "🌐 Статус сервера")
async def server_status(message: Message, bot: Bot):
    uid = message.from_user.id
    if uid != MAIN_ADMIN_ID and uid in status_cooldowns:
        if time.time() - status_cooldowns[uid] < STATUS_COOLDOWN:
            await message.answer(f"⏳ Подождите еще {int(STATUS_COOLDOWN - (time.time() - status_cooldowns[uid]))} сек.", parse_mode="HTML")
            return
    if not await is_subscribed(uid, bot):
        await message.answer("🛑 Нужна подписка!", reply_markup=get_subscribe_kb(), parse_mode="HTML")
        return
    status_cooldowns[uid] = time.time()
    t = await message.answer("🔄 <i>Опрашиваю сервер...</i>", parse_mode="HTML")
    try:
        server = await JavaServer.async_lookup(SERVER_IP)
        q = await server.async_status()
        await t.edit_text(f"🟢 <b>MisaCraft ONLINE!</b>\n👥 Игроков: <code>{q.players.online}/{q.players.max}</code>\n📍 IP: <code>{SERVER_IP}</code>", parse_mode="HTML")
    except: await t.edit_text("🔴 <b>Сервер выключен.</b>", parse_mode="HTML")

@router.message(F.text == "ℹ️ FAQ")
async def faq(message: Message):
    await message.answer("📚 <b>База знаний</b>", reply_markup=faq_kb, parse_mode="HTML")

@router.callback_query(F.data == "faq_connect")
async def faq_conn(callback: CallbackQuery):
    await callback.message.answer(f"🎮 <b>Как зайти?</b>\nIP: <code>{SERVER_IP}</code>\nВерсия: <code>{SERVER_VERSION}</code>", parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "check_sub")
async def check_sub(callback: CallbackQuery, bot: Bot):
    if await is_subscribed(callback.from_user.id, bot):
        await callback.message.delete()
        await callback.message.answer("✅ Подписка подтверждена!", reply_markup=main_kb, parse_mode="HTML")
    else: await callback.answer("❌ Вы не подписаны!", show_alert=True)

# --- Тикеты ---
@router.message(F.text == "🆘 Написать в поддержку")
async def ticket_init(message: Message, state: FSMContext, bot: Bot):
    if not await is_subscribed(message.from_user.id, bot):
        await message.answer("🛑 Нужна подписка.", reply_markup=get_subscribe_kb(), parse_mode="HTML")
        return
    if message.from_user.id != MAIN_ADMIN_ID and message.from_user.id in user_cooldowns:
        if time.time() - user_cooldowns[message.from_user.id] < TICKET_COOLDOWN:
            await message.answer("⏳ Подождите перед новым тикетом.", parse_mode="HTML")
            return
    await state.set_state(SupportStates.waiting_for_question)
    await message.answer("📝 Опишите проблему:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True))

@router.message(SupportStates.waiting_for_question)
async def process_ticket_start(message: Message, state: FSMContext, bot: Bot):
    if message.text == "❌ Отмена":
        await state.clear(); await message.answer("🔙 Отменено.", reply_markup=main_kb, parse_mode="HTML"); return
    user_id = message.from_user.id
    user_cooldowns[user_id] = time.time()
    await message.answer("✅ <b>Тикет создан!</b> Ожидайте модератора.", reply_markup=in_ticket_kb, parse_mode="HTML")
    await state.set_state(SupportStates.in_ticket)
    h = f"🚨 <b>НОВЫЙ ТИКЕТ</b>\n👤 {html.escape(message.from_user.full_name)}\n🆔 ID: <code>{user_id}</code>\n➖➖➖➖➖➖"
    await bot.send_message(MOD_GROUP_ID, h, message_thread_id=MOD_THREAD_ID, parse_mode="HTML")
    sent = await message.copy_to(MOD_GROUP_ID, message_thread_id=MOD_THREAD_ID, reply_markup=get_take_ticket_kb(user_id))
    t_data = {"mod_id": None, "ticket_msg_id": sent.message_id}
    save_active_ticket(user_id, t_data); await state.update_data(**t_data)

@router.message(SupportStates.in_ticket)
async def ticket_chat(message: Message, state: FSMContext, bot: Bot):
    if message.text == "🔒 Закрыть обращение":
        data = await state.get_data(); mod_id = data.get("mod_id")
        if not mod_id and data.get("ticket_msg_id"):
            try: await bot.edit_reply_markup(MOD_GROUP_ID, data.get("ticket_msg_id"), reply_markup=None)
            except: pass
        await state.clear(); remove_active_ticket(message.from_user.id)
        await message.answer("🔒 <b>Диалог завершен.</b>", reply_markup=main_kb, parse_mode="HTML")
        try: await bot.send_message(mod_id or MOD_GROUP_ID, f"🔒 Игрок <code>{message.from_user.id}</code> закрыл тикет.", 
                                 message_thread_id=MOD_THREAD_ID if not mod_id else None, parse_mode="HTML")
        except: pass
        return
    data = await state.get_data(); mod = data.get("mod_id")
    if not mod: await message.answer("⏳ <b>Тикет в очереди.</b>", parse_mode="HTML"); return
    try: await message.copy_to(mod)
    except: pass

# --- Модерация ---
@router.callback_query(F.data.startswith("take_ticket_"))
async def mod_take(callback: CallbackQuery, bot: Bot):
    p_id = int(callback.data.split("_")[2]); m_id = callback.from_user.id
    p_key = StorageKey(bot_id=callback.bot.id, chat_id=p_id, user_id=p_id)
    p_state = FSMContext(storage=dp.storage, key=p_key)
    if await p_state.get_state() != SupportStates.in_ticket.state:
        await callback.answer("⚠️ Тикет неактивен.", show_alert=True)
        try: await callback.message.edit_reply_markup(reply_markup=None)
        except: pass
        return
    try: await bot.send_message(m_id, f"✅ Ты взял тикет <code>{p_id}</code>.", reply_markup=get_admin_ticket_kb(p_id), parse_mode="HTML")
    except: await callback.answer("❌ Нажми /start в ЛС бота!", show_alert=True); return
    p_data = await p_state.get_data(); p_data["mod_id"] = m_id
    save_active_ticket(p_id, p_data); await p_state.update_data(mod_id=m_id)
    try: await callback.message.edit_reply_markup(reply_markup=None)
    except: pass
    m_name = html.escape(callback.from_user.first_name)
    try:
        if callback.message.text: await callback.message.edit_text(callback.message.text + f"\n\n✅ Взял: {m_name}", parse_mode="HTML")
        elif callback.message.caption: await callback.message.edit_caption(caption=callback.message.caption + f"\n\n✅ Взял: {m_name}", parse_mode="HTML")
        else: await callback.message.reply(f"✅ Взял: {m_name}", parse_mode="HTML")
    except: pass
    await callback.answer("Тикет твой!")

@router.callback_query(F.data.startswith("reply_to_"))
async def admin_reply_init(callback: CallbackQuery, state: FSMContext, bot: Bot):
    p_id = int(callback.data.split("_")[2])
    p_key = StorageKey(bot_id=callback.bot.id, chat_id=p_id, user_id=p_id)
    if await FSMContext(storage=dp.storage, key=p_key).get_state() != SupportStates.in_ticket.state:
        await callback.answer("⚠️ Тикет закрыт.", show_alert=True); return
    await state.update_data(reply_to=p_id); await state.set_state(AdminStates.waiting_for_reply)
    await callback.message.answer(f"✍️ Ответ для <code>{p_id}</code>:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_admin_reply")]]), parse_mode="HTML")
    await callback.answer()

@router.message(AdminStates.waiting_for_reply)
async def admin_send(message: Message, state: FSMContext, bot: Bot):
    p_id = (await state.get_data()).get("reply_to")
    if not p_id: return
    p_key = StorageKey(bot_id=message.bot.id, chat_id=p_id, user_id=p_id)
    if await FSMContext(storage=dp.storage, key=p_key).get_state() != SupportStates.in_ticket.state:
        await message.answer("❌ Игрок закрыл тикет."); await state.clear(); return
    try:
        await bot.send_message(p_id, "👨‍💻 <b>ОТВЕТ ПОДДЕРЖКИ:</b>", parse_mode="HTML")
        await message.copy_to(p_id); await message.answer("✅ Доставлено!", parse_mode="HTML")
    except: await message.answer("❌ Ошибка доставки.")
    await state.clear()

@router.callback_query(F.data == "cancel_admin_reply")
async def cancel_reply(callback: CallbackQuery, state: FSMContext):
    await state.clear(); await callback.message.edit_text("🔙 Отменено.", parse_mode="HTML")

@router.callback_query(F.data.startswith("close_ticket_"))
async def admin_close(callback: CallbackQuery, bot: Bot):
    p_id = int(callback.data.split("_")[2])
    p_key = StorageKey(bot_id=callback.bot.id, chat_id=p_id, user_id=p_id)
    await FSMContext(storage=dp.storage, key=p_key).clear(); remove_active_ticket(p_id)
    await callback.message.edit_text(f"🔒 Тикет <code>{p_id}</code> закрыт.", parse_mode="HTML")
    try: await bot.send_message(p_id, "🔒 Поддержка завершила диалог.", reply_markup=main_kb, parse_mode="HTML")
    except: pass

# --- Рассылка ---
@router.message(Command("broadcast"))
async def broadcast_init(message: Message, state: FSMContext):
    if message.from_user.id != MAIN_ADMIN_ID: return
    await message.answer("📣 Введите рассылку (или 'отмена'):", parse_mode="HTML")
    await state.set_state(AdminStates.waiting_for_broadcast)

@router.message(AdminStates.waiting_for_broadcast)
async def broadcast_exec(message: Message, state: FSMContext, bot: Bot):
    if message.text and message.text.lower() == 'отмена':
        await state.clear(); await message.answer("🔙 Отменено."); return
    ids = get_all_users()
    await message.answer(f"🚀 Рассылка на {len(ids)} чел...")
    for uid in ids:
        try: await message.copy_to(uid); await asyncio.sleep(0.05)
        except: pass
    await message.answer("✅ Готово!"); await state.clear()

# --- Запуск ---
async def main():
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    tickets = get_all_active_tickets()
    print(f"🔄 Восстановление {len(tickets)} тикетов...")
    for uid_str, t_data in tickets.items():
        uid = int(uid_str); s_key = StorageKey(bot_id=bot.id, chat_id=uid, user_id=uid)
        ctx = FSMContext(storage=dp.storage, key=s_key)
        await ctx.set_state(SupportStates.in_ticket); await ctx.update_data(**t_data)
        if t_data.get("mod_id"):
            try: await bot.send_message(t_data["mod_id"], f"🔄 Тикет <code>{uid}</code> восстановлен.", reply_markup=get_admin_ticket_kb(uid), parse_mode="HTML")
            except: pass
    print("🤖 БОТ ЗАПУЩЕН!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try: asyncio.run(main())
    except: pass
