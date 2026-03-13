import asyncio
import logging
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (
    Message, CallbackQuery, ReplyKeyboardMarkup, 
    KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.base import StorageKey
from aiogram.filters import CommandStart, Command
from mcstatus import JavaServer
import os
import html
import time

# ==========================================
# ⚙️ НАСТРОЙКИ (БЕРУТСЯ ИЗ ХОСТИНГА ДЛЯ БЕЗОПАСНОСТИ)
# ==========================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "ВАШ_ТОКЕН") 

# ID главного админа
MAIN_ADMIN_ID = int(os.getenv("MAIN_ADMIN_ID", 123456789))

# ID группы модераторов
MOD_GROUP_ID = int(os.getenv("MOD_GROUP_ID", -1000000000000))

# ID ветки (топика) в группе модераторов
_thread_id = os.getenv("MOD_THREAD_ID", "")
MOD_THREAD_ID = int(_thread_id) if _thread_id and _thread_id.lower() != "none" else None

# Настройки обязательной подписки
CHANNEL_ID = os.getenv("CHANNEL_ID", "") # ID канала, например -100123456789 (оставь пустым, если проверка не нужна)
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://t.me/Misacraft")

# Информация о сервере
SERVER_IP = "play.misacraft.online"
SERVER_VERSION = "1.21.10"
DONATE_LINK = "https://site.misacraft.online/"
RULES_LINK = "https://site.misacraft.online/"
DISCORD_LINK = "https://discord.gg/69Jf7R4JFF"
USERS_FILE = "users.txt"

# Настройки антиспама
TICKET_COOLDOWN = 300  # Задержка между тикетами в секундах (300 = 5 минут)
STATUS_COOLDOWN = 10   # Задержка для проверки статуса сервера (10 секунд)
user_cooldowns = {}    # Словарь для хранения времени последнего тикета
status_cooldowns = {}  # Словарь для хранения времени последней проверки статуса

# Функция для сохранения ID пользователей
def add_user(user_id: int):
    users = set()
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r") as f:
            users = set(f.read().splitlines())
    if str(user_id) not in users:
        with open(USERS_FILE, "a") as f:
            f.write(f"{user_id}\n")

# Функция для получения всех ID
def get_all_users() -> list:
    if not os.path.exists(USERS_FILE):
        return []
    with open(USERS_FILE, "r") as f:
        return [int(uid) for uid in f.read().splitlines() if uid.strip()]

# ==========================================
# 🗂 ИНИЦИАЛИЗАЦИЯ
# ==========================================
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()

# ==========================================
# ⌨️ КЛАВИАТУРЫ
# ==========================================
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🌐 Статус сервера"), KeyboardButton(text="ℹ️ FAQ")],
        [KeyboardButton(text="🆘 Написать в поддержку")]
    ],
    resize_keyboard=True,
    input_field_placeholder="Выберите действие..."
)

in_ticket_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🌐 Статус сервера"), KeyboardButton(text="ℹ️ FAQ")],
        [KeyboardButton(text="🔒 Закрыть обращение")]
    ],
    resize_keyboard=True,
    input_field_placeholder="Вы в диалоге с поддержкой..."
)

faq_kb = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Как подключиться?", callback_data="faq_connect")],
        [InlineKeyboardButton(text="📜 Правила сервера", url=RULES_LINK)],
        [InlineKeyboardButton(text="💎 Донат и привилегии", url=DONATE_LINK)]
    ]
)

# Кнопка для группы модераторов (чтобы забрать тикет себе)
def get_take_ticket_kb(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🙋‍♂️ Взять обращение", callback_data=f"take_ticket_{user_id}")]
        ]
    )

# Кнопки для модератора в ЛС (ответить / закрыть)
def get_admin_ticket_kb(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✍️ Ответить", callback_data=f"reply_to_{user_id}")],
            [InlineKeyboardButton(text="❌ Закрыть тикет", callback_data=f"close_ticket_{user_id}")]
        ]
    )

# Кнопка для подписки
def get_subscribe_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📢 Подписаться на канал", url=CHANNEL_LINK)],
            [InlineKeyboardButton(text="🔄 Я подписался!", callback_data="check_sub")]
        ]
    )

# Функция проверки подписки
async def is_subscribed(user_id: int, bot: Bot) -> bool:
    if not CHANNEL_ID:
        return True # Если канал не настроен, пускаем всех
    if user_id == MAIN_ADMIN_ID:
        return True # Главного админа пускаем всегда
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        if member.status in ['left', 'kicked']:
            return False
        return True
    except Exception as e:
        logging.error(f"Ошибка проверки подписки: {e}")
        return True # Если бот не админ в канале, пускаем, чтобы не сломать бота

# ==========================================
# 🚦 СОСТОЯНИЯ (FSM)
# ==========================================
class SupportStates(StatesGroup):
    waiting_for_question = State()
    in_ticket = State() 

class AdminStates(StatesGroup):
    waiting_for_reply = State()
    waiting_for_broadcast = State()

# ==========================================
# 🎮 ОБРАБОТЧИКИ БОТА
# ==========================================

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
    # Проверка 2: Побег из тикета
    current_state = await state.get_state()
    if current_state in [SupportStates.waiting_for_question.state, SupportStates.in_ticket.state]:
        if current_state == SupportStates.in_ticket.state:
            player_data = await state.get_data()
            mod_id = player_data.get("mod_id")
            ticket_msg_id = player_data.get("ticket_msg_id")
            
            target_id = mod_id if mod_id else MOD_GROUP_ID
            thread_id = None if mod_id else MOD_THREAD_ID
            
            # Убираем кнопку из группы модераторов
            if ticket_msg_id and not mod_id:
                try:
                    await bot.edit_message_reply_markup(chat_id=target_id, message_id=ticket_msg_id, reply_markup=None)
                except: pass
            
            try:
                await bot.send_message(chat_id=target_id, message_thread_id=thread_id, text=f"⚠️ Игрок <code>{message.from_user.id}</code> покинул обращение (вернулся в меню).", parse_mode="HTML")
            except: pass

    await state.clear()
    add_user(message.from_user.id)
    
    # Безопасно обрабатываем имя пользователя, чтобы спецсимволы не ломали бота
    safe_name = html.escape(message.from_user.first_name)
    
    welcome_text = (
        f"👋 Привет, {safe_name}!\n\n"
        f"Добро пожаловать в службу поддержки <b>Misacraft</b> ⛏\n\n"
        f"🔹 Здесь ты можешь узнать статус сервера, найти ответы на частые вопросы или связаться с администрацией.\n\n"
        f"👇 Выбирай нужное действие в меню ниже:"
    )
    await message.answer(welcome_text, reply_markup=main_kb, parse_mode="HTML")

# --- Скрытая команда для получения ID чата ---
@router.message(Command("getid"))
async def cmd_getid(message: Message):
    text = f"ID этого чата: <code>{message.chat.id}</code>\n"
    if message.message_thread_id:
        text += f"ID этой ветки (топика): <code>{message.message_thread_id}</code>\n"
    text += "\n<i>(Скопируйте нужные числа)</i>"
    await message.answer(text, parse_mode="HTML")

@router.message(F.text == "ℹ️ FAQ")
async def show_faq(message: Message):
    text = "📚 <b>База знаний Misacraft</b>\n\nВыбери интересующий раздел:"
    await message.answer(text, reply_markup=faq_kb, parse_mode="HTML")

@router.callback_query(F.data == "faq_connect")
async def faq_connect_answer(callback: CallbackQuery):
    text = (
        f"🎮 <b>Как начать играть?</b>\n\n"
        f"У нас работает привязка аккаунта - для игры нужно выполнить пару шагов:\n\n"
        f"1️⃣ Зайди в наш Discord.\n"
        f"2️⃣ Подключись к серверу Minecraft по IP: <code>{SERVER_IP}</code> (Версия: <code>{SERVER_VERSION}</code>).\n"
        f"3️⃣ Сервер покажет тебе на экране специальный код.\n"
        f"4️⃣ Отправь этот код нашему боту в Discord.\n"
        f"5️⃣ Готово! Теперь ты можешь играть 🎉\n\n"
        f"💡 <i>Зайти можно как с лицензии, так и с пиратки.</i>"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="👾 Наш Discord", url=DISCORD_LINK)]])
    await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "check_sub")
async def check_sub_callback(callback: CallbackQuery, bot: Bot):
    if await is_subscribed(callback.from_user.id, bot):
        await callback.message.delete()
        await callback.message.answer("✅ <b>Спасибо за подписку!</b> Теперь тебе доступны все функции бота.", reply_markup=main_kb, parse_mode="HTML")
    else:
        await callback.answer("❌ Ты еще не подписался на канал!", show_alert=True)

@router.message(F.text == "🌐 Статус сервера")
async def server_status(message: Message, bot: Bot):
    user_id = message.from_user.id
    current_time = time.time()
    
    # Проверка антиспама для статуса (главный админ игнорирует)
    if user_id != MAIN_ADMIN_ID and user_id in status_cooldowns:
        time_passed = current_time - status_cooldowns[user_id]
        if time_passed < STATUS_COOLDOWN:
            seconds_left = int(STATUS_COOLDOWN - time_passed)
            await message.answer(f"⏳ Не так быстро! Подождите еще <b>{seconds_left} сек.</b>", parse_mode="HTML")
            return

    if not await is_subscribed(message.from_user.id, bot):
        await message.answer(
            "🛑 <b>Доступ закрыт!</b>\n\n"
            "Чтобы проверять статус сервера, пожалуйста, подпишись на наш Telegram-канал новостей.",
            reply_markup=get_subscribe_kb(),
            parse_mode="HTML"
        )
        return

    # Записываем время проверки (активируем задержку)
    status_cooldowns[user_id] = current_time

    wait_msg = await message.answer("🔄 <i>Опрашиваю сервер...</i>", parse_mode="HTML")
    try:
        server = await JavaServer.async_lookup(SERVER_IP)
        status = await server.async_status()
        text = (
            f"🟢 <b>Misacraft работает стабильно!</b>\n\n"
            f"👥 Игроков онлайн: <code>{status.players.online}/{status.players.max}</code>\n"
            f"IP: <code>{SERVER_IP}</code>\n"
            f"🔥 <i>Заходи, ждем тебя!</i>"
        )
    except Exception as e:
        text = (
            f"🔴 <b>Сервер сейчас недоступен</b>\n\n"
            f"Возможно, идут технические работы или сервер перезагружается.\n"
            f"IP: <code>{SERVER_IP}</code>\n\n"
            f"⏳ <i>Попробуй проверить статус немного позже.</i>"
        )
    await wait_msg.edit_text(text, parse_mode="HTML")

# --- Раздел Поддержки (Тикеты) ---
@router.message(F.text == "🆘 Написать в поддержку")
async def ask_support(message: Message, state: FSMContext, bot: Bot):
    if not await is_subscribed(message.from_user.id, bot):
        await message.answer(
            "🛑 <b>Доступ закрыт!</b>\n\n"
            "Чтобы обращаться в поддержку, пожалуйста, подпишись на наш Telegram-канал новостей.",
            reply_markup=get_subscribe_kb(),
            parse_mode="HTML"
        )
        return

    user_id = message.from_user.id
    current_time = time.time()
    
    # Проверка антиспама: главный админ игнорирует задержку
    if user_id != MAIN_ADMIN_ID and user_id in user_cooldowns:
        time_passed = current_time - user_cooldowns[user_id]
        if time_passed < TICKET_COOLDOWN:
            minutes_left = int((TICKET_COOLDOWN - time_passed) // 60)
            seconds_left = int((TICKET_COOLDOWN - time_passed) % 60)
            
            # Формируем красивый текст со временем
            time_str = ""
            if minutes_left > 0:
                time_str += f"{minutes_left} мин. "
            time_str += f"{seconds_left} сек."
            
            await message.answer(
                f"⏳ <b>Антиспам-защита:</b> Вы создаете обращения слишком часто.\n\n"
                f"Подождите еще {time_str}, прежде чем открыть новый тикет.",
                parse_mode="HTML"
            )
            return

    await message.answer(
        "📝 <b>Создание обращения</b>\n\n"
        "Опиши свою проблему или задай вопрос максимально подробно. Если нужно - прикрепи скриншот (отправляй фото сразу с текстом).\n\n"
        "💡 <i>Чем детальнее ты опишешь ситуацию, тем быстрее мы сможем помочь.</i>\n\n"
        "Нажми «❌ Отмена», если передумал.",
        reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True),
        parse_mode="HTML"
    )
    await state.set_state(SupportStates.waiting_for_question)

@router.message(F.text == "❌ Отмена")
async def cancel_action(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🔙 <i>Действие отменено.</i> Возвращаю в главное меню.", reply_markup=main_kb, parse_mode="HTML")

@router.message(F.text == "🔒 Закрыть обращение")
async def close_ticket_user(message: Message, state: FSMContext, bot: Bot):
    current_state = await state.get_state()
    if current_state == SupportStates.in_ticket.state:
        player_data = await state.get_data()
        mod_id = player_data.get("mod_id")
        ticket_msg_id = player_data.get("ticket_msg_id")
        
        target_id = mod_id if mod_id else MOD_GROUP_ID
        thread_id = None if mod_id else MOD_THREAD_ID

        # Проверка 3: Убираем призрачную кнопку "Взять обращение"
        if ticket_msg_id and not mod_id:
            try:
                await bot.edit_message_reply_markup(chat_id=target_id, message_id=ticket_msg_id, reply_markup=None)
            except Exception:
                pass

        await state.clear()
        await message.answer("✅ <b>Обращение закрыто.</b>\n\nЕсли появятся новые вопросы - смело пиши снова!", reply_markup=main_kb, parse_mode="HTML")
        try:
            await bot.send_message(chat_id=target_id, message_thread_id=thread_id, text=f"🔒 Игрок <code>{message.from_user.id}</code> самостоятельно закрыл свое обращение.", parse_mode="HTML")
        except:
            pass
    else:
        await message.answer("У вас нет активных обращений.", reply_markup=main_kb)

@router.message(SupportStates.waiting_for_question)
async def process_support_question(message: Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id
    username = f"@{message.from_user.username}" if message.from_user.username else "Без юзернейма"
    
    # Фиксируем время создания тикета (активируем задержку для игрока)
    user_cooldowns[user_id] = time.time()
    
    await message.answer(
        "✅ <b>Обращение успешно создано!</b>\n\n"
        "Администрация уже получила твое сообщение. Обычно мы отвечаем в течение дня.\n"
        "<i>Пожалуйста, дождись ответа модератора, прежде чем отправлять дополнительные материалы.</i>",
        reply_markup=in_ticket_kb,
        parse_mode="HTML"
    )
    await state.set_state(SupportStates.in_ticket)
    
    safe_name = html.escape(message.from_user.full_name)
    
    header_text = (
        f"🚨 <b>Новый тикет поддержки</b>\n\n"
        f"👤 <b>Пользователь:</b> {safe_name} ({username})\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
        f"➖➖➖➖➖➖➖➖➖➖"
    )
    try:
        # Отправляем информационную шапку
        await bot.send_message(chat_id=MOD_GROUP_ID, message_thread_id=MOD_THREAD_ID, text=header_text, parse_mode="HTML")
        
        # Копируем само сообщение (текст, фото, видео, голосовое, кружок) и вешаем кнопку "Взять тикет"
        sent_msg = await message.copy_to(
            chat_id=MOD_GROUP_ID, 
            message_thread_id=MOD_THREAD_ID, 
            reply_markup=get_take_ticket_kb(user_id)
        )
        
        # Сохраняем ID сообщения для Проверки 3
        await state.update_data(mod_id=None, ticket_msg_id=sent_msg.message_id)
    except Exception as e:
        logging.error(f"Ошибка отправки в группу модераторов: {e}")
        await state.update_data(mod_id=None)

@router.message(SupportStates.in_ticket)
async def process_additional_ticket_message(message: Message, state: FSMContext, bot: Bot):
    player_data = await state.get_data()
    mod_id = player_data.get("mod_id")
    
    # Строгий режим: запрещаем спамить до того, как модератор возьмет тикет
    if not mod_id:
        await message.answer(
            "⏳ <b>Ваше обращение еще в очереди.</b>\n\n"
            "Пожалуйста, дождитесь, пока модератор подключится к диалогу, прежде чем присылать дополнительные файлы или сообщения.",
            parse_mode="HTML"
        )
        return
        
    target_id = mod_id
    thread_id = None # Отправляем строго в ЛС модератору
    
    try:
        # Умно копируем любое сообщение напрямую модератору
        await message.copy_to(chat_id=target_id, message_thread_id=thread_id)
        await message.answer("📨 <i>Сообщение доставлено модератору.</i>", parse_mode="HTML")
    except Exception:
        pass

# --- Система модераторов: Взятие тикета ---
@router.callback_query(F.data.startswith("take_ticket_"))
async def mod_take_ticket(callback: CallbackQuery, bot: Bot):
    player_id = int(callback.data.split("_")[2])
    mod_id = callback.from_user.id
    mod_username = f"@{callback.from_user.username}" if callback.from_user.username else callback.from_user.first_name
    safe_mod_username = html.escape(mod_username)
    
    # Получаем доступ к состоянию игрока
    player_state = FSMContext(storage=dp.storage, key=StorageKey(bot_id=bot.id, chat_id=player_id, user_id=player_id))
    
    # ПРОВЕРКА: Открыт ли еще тикет со стороны игрока?
    current_state = await player_state.get_state()
    if current_state != SupportStates.in_ticket.state:
        await callback.answer("⚠️ Игрок уже закрыл или отменил это обращение!", show_alert=True)
        # Убираем кнопку из чата, так как тикет уже неактуален
        original_text = callback.message.text or callback.message.caption or "Новое обращение"
        safe_original = html.escape(original_text)
        edited_text = f"{safe_original}\n\n❌ <i>Тикет был закрыт игроком.</i>"
        try:
            if callback.message.photo:
                await callback.message.edit_caption(caption=edited_text, reply_markup=None, parse_mode="HTML")
            else:
                await callback.message.edit_text(text=edited_text, reply_markup=None, parse_mode="HTML")
        except Exception:
            pass
        return

    player_data = await player_state.get_data()
    
    # Проверяем, не взял ли тикет кто-то другой
    if player_data.get("mod_id"):
        await callback.answer("⚠️ Этот тикет уже взял другой администратор!", show_alert=True)
        return

    # Пробуем написать модератору в ЛС
    try:
        await bot.send_message(
            chat_id=mod_id,
            text=f"✅ <b>Ты взял в работу обращение от ID <code>{player_id}</code>!</b>\nТеперь все новые сообщения от него будут приходить сюда (в ЛС).",
            reply_markup=get_admin_ticket_kb(player_id),
            parse_mode="HTML"
        )
    except Exception:
        await callback.answer("❌ Ошибка! Бот не может написать тебе в ЛС. Сначала перейди в бота и нажми /start !", show_alert=True)
        return

    # Закрепляем модератора за игроком
    await player_state.update_data(mod_id=mod_id)
    
    # Изменяем сообщение в группе модераторов
    original_text = callback.message.text or callback.message.caption or "Новое обращение"
    safe_original = html.escape(original_text)
    edited_text = f"{safe_original}\n\n✅ <i>Взял в работу:</i> {safe_mod_username}"
    
    try:
        if callback.message.photo:
            await callback.message.edit_caption(caption=edited_text, reply_markup=None, parse_mode="HTML")
        else:
            await callback.message.edit_text(text=edited_text, reply_markup=None, parse_mode="HTML")
    except Exception:
        pass
        
    await callback.answer("Тикет успешно закреплен за тобой!")

# --- Ответ администратора ---
@router.callback_query(F.data.startswith("reply_to_"))
async def admin_start_reply(callback: CallbackQuery, state: FSMContext, bot: Bot):
    player_id = int(callback.data.split("_")[2])
    
    # Проверка 5: Открыт ли еще тикет со стороны игрока?
    user_state = FSMContext(storage=dp.storage, key=StorageKey(bot_id=bot.id, chat_id=player_id, user_id=player_id))
    if await user_state.get_state() != SupportStates.in_ticket.state:
        await callback.answer("⚠️ Поздно! Игрок уже закрыл или покинул этот тикет.", show_alert=True)
        return

    await state.update_data(reply_to_user=player_id)
    await state.set_state(AdminStates.waiting_for_reply)
    
    # Проверка 4: Красивая кнопка отмены
    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить ответ", callback_data="cancel_admin_reply")]
    ])
    
    await callback.message.answer(
        f"✍️ Напиши ответ для пользователя <code>{player_id}</code>.\n"
        f"<i>(Можно прикрепить фото)</i>", 
        reply_markup=cancel_kb,
        parse_mode="HTML"
    )
    await callback.answer()

# Обработчик кнопки "Отменить ответ" (Проверка 4)
@router.callback_query(F.data == "cancel_admin_reply", AdminStates.waiting_for_reply)
async def cancel_admin_reply(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("🔙 <i>Отправка ответа отменена.</i>", parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data.startswith("close_ticket_"))
async def admin_close_ticket(callback: CallbackQuery, bot: Bot):
    player_id = int(callback.data.split("_")[2])
    
    user_state = FSMContext(storage=dp.storage, key=StorageKey(bot_id=bot.id, chat_id=player_id, user_id=player_id))
    await user_state.clear()

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.reply(f"🔒 <b>Тикет #<code>{player_id}</code> успешно закрыт.</b>", parse_mode="HTML")
    await callback.answer("Тикет закрыт")

    try:
        mod_name = html.escape(callback.from_user.first_name)
        await bot.send_message(chat_id=MOD_GROUP_ID, message_thread_id=MOD_THREAD_ID, text=f"🔒 Модератор <b>{mod_name}</b> завершил работу с тикетом от <code>{player_id}</code>.", parse_mode="HTML")
    except:
        pass

    try:
        await bot.send_message(
            chat_id=player_id, 
            text=(
                "🔒 <b>Диалог с поддержкой завершен.</b>\n\n"
                "Надеемся, мы смогли тебе помочь! Если проблема осталась или появились новые вопросы - можешь создать новое обращение."
            ),
            reply_markup=main_kb,
            parse_mode="HTML"
        )
    except:
        pass

@router.message(AdminStates.waiting_for_reply)
async def process_admin_reply(message: Message, state: FSMContext, bot: Bot):
    if message.text and message.text.lower() == 'отмена':
        await state.clear()
        await message.answer("🔙 <i>Отправка ответа отменена.</i>", parse_mode="HTML")
        return

    data = await state.get_data()
    player_id = data.get("reply_to_user")
    
    # Проверка 5 (доп): Открыт ли еще тикет прямо перед отправкой?
    user_state = FSMContext(storage=dp.storage, key=StorageKey(bot_id=bot.id, chat_id=player_id, user_id=player_id))
    if await user_state.get_state() != SupportStates.in_ticket.state:
        await message.answer("⚠️ <b>Ошибка:</b> Игрок уже закрыл этот тикет. Ваш ответ не доставлен.", parse_mode="HTML")
        await state.clear()
        return
    
    try:
        # Предупреждаем игрока, что это ответ от админа
        await bot.send_message(chat_id=player_id, text="👨‍💻 <b>Ответ от администрации:</b>", parse_mode="HTML")
        # Копируем само сообщение админа (текст, фото, кружочек, видео, голосовое)
        await message.copy_to(chat_id=player_id)
        await message.answer("✅ <b>Ответ отправлен!</b>\n<i>(Тикет остается открытым, игрок может ответить)</i>", parse_mode="HTML")
    except Exception as e:
        await message.answer(f"❌ Ошибка отправки.\n{e}")
    
    await state.clear()

# --- Рассылка всем пользователям ---
@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext):
    if message.from_user.id != MAIN_ADMIN_ID:
        return
    
    await message.answer(
        "📣 <b>Настройка рассылки</b>\n\n"
        "Отправь сообщение (текст, фото, видео, голосовое), которое получат <b>все</b> пользователи бота.\n"
        "<i>(Для отмены напиши <code>отмена</code>)</i>",
        parse_mode="HTML"
    )
    await state.set_state(AdminStates.waiting_for_broadcast)

@router.message(AdminStates.waiting_for_broadcast)
async def process_broadcast(message: Message, state: FSMContext):
    if message.text and message.text.lower() == 'отмена':
        await state.clear()
        await message.answer("🔙 <i>Рассылка отменена.</i>", parse_mode="HTML")
        return

    users = get_all_users()
    if not users:
        await message.answer("⚠️ <b>База пользователей пуста.</b> В бот еще никто не заходил.", parse_mode="HTML")
        await state.clear()
        return

    await message.answer(f"🚀 <i>Запускаю рассылку для {len(users)} пользователей... Это может занять какое-то время.</i>", parse_mode="HTML")
    
    success_count = 0
    error_count = 0
    
    for user_id in users:
        try:
            # Копируем любое сообщение целиком
            await message.copy_to(chat_id=user_id)
            success_count += 1
            await asyncio.sleep(0.05)
        except Exception:
            error_count += 1

    await message.answer(
        f"✅ <b>Рассылка успешно завершена!</b>\n\n"
        f"📈 <b>Статистика:</b>\n"
        f"├ Доставлено: <code>{success_count}</code>\n"
        f"└ Заблокировали бота: <code>{error_count}</code>",
        parse_mode="HTML"
    )
    await state.clear()

# ==========================================
# 🚀 ЗАПУСК
# ==========================================
async def main():
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    print("Бот Мисакрафт успешно запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    import sys
    if 'ipykernel' in sys.modules:  
        import nest_asyncio
        nest_asyncio.apply()
        asyncio.run(main())
    else:
        asyncio.run(main())
