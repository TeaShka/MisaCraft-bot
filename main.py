import asyncio
import logging
import os
import html
import time
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (
    Message, CallbackQuery, ReplyKeyboardMarkup, 
    KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardRemove
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.base import StorageKey
from aiogram.filters import CommandStart, Command
from mcstatus import JavaServer

# ==========================================
# ⚙️ ГЛОБАЛЬНЫЕ НАСТРОЙКИ (ПЕРЕМЕННЫЕ)
# ==========================================
# Токен бота, полученный от @BotFather
BOT_TOKEN = os.getenv("BOT_TOKEN", "ВАШ_ТОКЕН") 

# ID главного администратора (имеет доступ к рассылке и обходит антиспам)
MAIN_ADMIN_ID = int(os.getenv("MAIN_ADMIN_ID", 0))

# ID группы, где сидят модераторы и принимают тикеты
MOD_GROUP_ID = int(os.getenv("MOD_GROUP_ID", 0))

# ID конкретной ветки (Topic ID) внутри группы, если она разделена на темы
_thread_id = os.getenv("MOD_THREAD_ID", "")
MOD_THREAD_ID = int(_thread_id) if _thread_id and _thread_id.lower() != "none" else None

# Настройки системы обязательной подписки на канал
CHANNEL_ID = os.getenv("CHANNEL_ID", "") 
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://t.me/misacraft1")

# Технические данные сервера Minecraft
SERVER_IP = "play.misacraft.online"
SERVER_VERSION = "1.21.10"
DONATE_LINK = "https://site.misacraft.online/"
RULES_LINK = "https://site.misacraft.online/"
DISCORD_LINK = "https://discord.gg/69Jf7R4JFF"
USERS_FILE = "users.txt"

# Конфигурация системы антиспама (задержки в секундах)
TICKET_COOLDOWN = 300  # Задержка между созданием новых тикетов (5 минут)
STATUS_COOLDOWN = 10   # Задержка на проверку статуса сервера (10 секунд)

# Словари для хранения временных меток (антиспам)
user_cooldowns = {}    
status_cooldowns = {}  

# ==========================================
# 📂 СИСТЕМА УЧЕТА ПОЛЬЗОВАТЕЛЕЙ
# ==========================================
def add_user(user_id: int):
    """Добавляет ID пользователя в базу данных (текстовый файл), если его там нет."""
    users = set()
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r") as f:
            users = set(line.strip() for line in f if line.strip())
    
    if str(user_id) not in users:
        with open(USERS_FILE, "a") as f:
            f.write(f"{user_id}\n")
        logging.info(f"Новый пользователь добавлен в базу: {user_id}")

def get_all_users() -> list:
    """Возвращает список всех ID пользователей из базы данных."""
    if not os.path.exists(USERS_FILE):
        return []
    with open(USERS_FILE, "r") as f:
        return [int(uid) for uid in f.read().splitlines() if uid.strip().isdigit()]

# ==========================================
# 🚦 СОСТОЯНИЯ (FSM)
# ==========================================
class SupportStates(StatesGroup):
    """Состояния для процесса общения с поддержкой."""
    waiting_for_question = State()  # Ожидание первого сообщения вопроса
    in_ticket = State()            # Активный диалог (тикет открыт)

class AdminStates(StatesGroup):
    """Состояния для административных функций."""
    waiting_for_reply = State()     # Ожидание текста ответа от админа
    waiting_for_broadcast = State() # Ожидание поста для массовой рассылки

# ==========================================
# ⌨️ КЛАВИАТУРЫ (ИНТЕРФЕЙС)
# ==========================================

# Главное меню бота (внизу под полем ввода)
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🌐 Статус сервера"), KeyboardButton(text="ℹ️ FAQ")],
        [KeyboardButton(text="🆘 Написать в поддержку")]
    ],
    resize_keyboard=True,
    input_field_placeholder="Выберите действие в меню..."
)

# Меню, которое видит игрок, когда у него открыт тикет
in_ticket_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🌐 Статус сервера"), KeyboardButton(text="ℹ️ FAQ")],
        [KeyboardButton(text="🔒 Закрыть обращение")]
    ],
    resize_keyboard=True,
    input_field_placeholder="Диалог с поддержкой активен..."
)

# Инлайн-кнопки для раздела FAQ
faq_kb = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Как подключиться к серверу?", callback_data="faq_connect")],
        [InlineKeyboardButton(text="📜 Правила нашего проекта", url=RULES_LINK)],
        [InlineKeyboardButton(text="💎 Донат и привилегии", url=DONATE_LINK)],
        [InlineKeyboardButton(text="👾 Наш Discord сервер", url=DISCORD_LINK)]
    ]
)

def get_take_ticket_kb(user_id: int) -> InlineKeyboardMarkup:
    """Кнопка для модераторов в общем чате, чтобы взять тикет."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🙋‍♂️ Взять обращение в работу", callback_data=f"take_ticket_{user_id}")]
    ])

def get_admin_ticket_kb(user_id: int) -> InlineKeyboardMarkup:
    """Кнопки управления тикетом для админа в личных сообщениях."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Написать ответ", callback_data=f"reply_to_{user_id}")],
        [InlineKeyboardButton(text="❌ Завершить диалог", callback_data=f"close_ticket_{user_id}")]
    ])

def get_subscribe_kb() -> InlineKeyboardMarkup:
    """Кнопка для проверки обязательной подписки на канал."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться на MisaCraft", url=CHANNEL_LINK)],
        [InlineKeyboardButton(text="🔄 Проверить подписку", callback_data="check_sub")]
    ])

# ==========================================
# 🛠 ТЕХНИЧЕСКИЕ ФУНКЦИИ
# ==========================================
async def is_subscribed(user_id: int, bot: Bot) -> bool:
    """Проверяет, подписан ли пользователь на обязательный канал."""
    if not CHANNEL_ID: 
        return True # Если канал не настроен, пускаем всех
    if user_id == MAIN_ADMIN_ID: 
        return True # Главный админ всегда имеет доступ
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        # Статусы 'left' и 'kicked' означают отсутствие подписки
        if member.status in ['left', 'kicked']:
            return False
        return True
    except Exception as e:
        logging.error(f"Ошибка при проверке подписки для {user_id}: {e}")
        return True # В случае ошибки API Telegram, пускаем пользователя

# ==========================================
# 🎮 ОСНОВНАЯ ЛОГИКА БОТА
# ==========================================
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()

# --- Обработка команды /start ---
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
    """Приветствие и сброс состояний (защита от застревания в тикете)."""
    current_state = await state.get_state()
    
    # Если пользователь нажал старт во время тикета - уведомляем админов
    if current_state in [SupportStates.waiting_for_question.state, SupportStates.in_ticket.state]:
        data = await state.get_data()
        mod_id = data.get("mod_id")
        target = mod_id if mod_id else MOD_GROUP_ID
        try:
            notification = f"⚠️ Игрок <code>{message.from_user.id}</code> покинул тикет, вернувшись в главное меню (/start)."
            await bot.send_message(chat_id=target, message_thread_id=MOD_THREAD_ID if not mod_id else None, text=notification, parse_mode="HTML")
            # Удаляем кнопку взятия тикета, если он еще не был взят
            if data.get("ticket_msg_id") and not mod_id:
                await bot.edit_reply_markup(chat_id=MOD_GROUP_ID, message_id=data.get("ticket_msg_id"), reply_markup=None)
        except: 
            pass

    await state.clear()
    add_user(message.from_user.id)
    
    first_name = html.escape(message.from_user.first_name)
    welcome_text = (
        f"Привет, {first_name}! 👋\n\n"
        f"Добро пожаловать в поддержку игрового сервера <b>MisaCraft</b>.\n"
        f"Здесь ты можешь узнать статус сервера или обратиться за помощью к администрации."
    )
    await message.answer(welcome_text, reply_markup=main_kb, parse_mode="HTML")

# --- Функция: Статус сервера ---
@router.message(F.text == "🌐 Статус сервера")
async def server_status_handler(message: Message, bot: Bot):
    """Проверка доступности игрового сервера через mcstatus."""
    user_id = message.from_user.id
    current_time = time.time()
    
    # Антиспам проверка (кроме главного админа)
    if user_id != MAIN_ADMIN_ID and user_id in status_cooldowns:
        time_diff = current_time - status_cooldowns[user_id]
        if time_diff < STATUS_COOLDOWN:
            seconds_left = int(STATUS_COOLDOWN - time_diff)
            await message.answer(f"⏳ Не так часто! Подождите еще <b>{seconds_left} сек.</b>", parse_mode="HTML")
            return
    
    # Проверка обязательной подписки
    if not await is_subscribed(user_id, bot):
        sub_text = "🛑 <b>Доступ ограничен!</b>\n\nДля проверки статуса сервера необходимо подписаться на наш новостной канал."
        await message.answer(sub_text, reply_markup=get_subscribe_kb(), parse_mode="HTML")
        return

    status_cooldowns[user_id] = current_time
    wait_msg = await message.answer("🔄 <i>Опрашиваю сервер, подождите...</i>", parse_mode="HTML")
    
    try:
        server = await JavaServer.async_lookup(SERVER_IP)
        query = await server.async_status()
        
        status_report = (
            f"🟢 <b>Сервер MisaCraft онлайн!</b>\n\n"
            f"👥 Игроков: <code>{query.players.online}/{query.players.max}</code>\n"
            f"📍 IP: <code>{SERVER_IP}</code>\n"
            f"⚙️ Версия: <code>{SERVER_VERSION}</code>\n\n"
            f"🔥 <i>Заходи и начинай играть прямо сейчас!</i>"
        )
        await wait_msg.edit_text(status_report, parse_mode="HTML")
        logging.info(f"Пользователь {user_id} проверил статус сервера: ONLINE")
    except Exception as e:
        await wait_msg.edit_text("🔴 <b>Сервер сейчас недоступен.</b>\nВедутся технические работы или сервер временно выключен.", parse_mode="HTML")
        logging.error(f"Ошибка при проверке статуса сервера: {e}")

# --- Функция: FAQ ---
@router.message(F.text == "ℹ️ FAQ")
async def show_faq_handler(message: Message):
    """Показ меню частых вопросов."""
    faq_main_text = "📚 <b>База знаний Misacraft</b>\n\nЗдесь собраны ответы на самые популярные вопросы игроков. Выберите интересующий раздел:"
    await message.answer(faq_main_text, reply_markup=faq_kb, parse_mode="HTML")

@router.callback_query(F.data == "faq_connect")
async def faq_connect_callback(callback: CallbackQuery):
    """Детальная инструкция по входу."""
    instructions = (
        f"🎮 <b>Как начать играть?</b>\n\n"
        f"1. Используйте IP: <code>{SERVER_IP}</code>\n"
        f"2. Версия игры: <code>{SERVER_VERSION}</code>\n"
        f"3. Для игры обязательна привязка Discord. Зайдите в наш канал для получения кода подтверждения."
    )
    await callback.message.answer(instructions, parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "check_sub")
async def check_subscription_callback(callback: CallbackQuery, bot: Bot):
    """Кнопка 'Я подписался'."""
    if await is_subscribed(callback.from_user.id, bot):
        await callback.message.delete()
        await callback.message.answer("✅ <b>Спасибо за подписку!</b> Теперь все функции бота полностью доступны.", reply_markup=main_kb, parse_mode="HTML")
    else:
        await callback.answer("❌ Вы всё еще не подписаны на канал @misacraft1", show_alert=True)

# --- СИСТЕМА ТИКЕТОВ ПОДДЕРЖКИ ---

@router.message(F.text == "🆘 Написать в поддержку")
async def start_support_ticket(message: Message, state: FSMContext, bot: Bot):
    """Начало процесса создания тикета."""
    user_id = message.from_user.id
    
    # 1. Проверка подписки
    if not await is_subscribed(user_id, bot):
        await message.answer("🛑 <b>Ошибка!</b>\nОбращения в поддержку доступны только подписчикам канала.", reply_markup=get_subscribe_kb(), parse_mode="HTML")
        return
    
    # 2. Проверка антиспама (5 минут)
    if user_id != MAIN_ADMIN_ID and user_id in user_cooldowns:
        time_diff = time.time() - user_cooldowns[user_id]
        if time_diff < TICKET_COOLDOWN:
            minutes_left = int((TICKET_COOLDOWN - time_diff) // 60)
            await message.answer(f"⏳ Вы недавно создавали обращение. Пожалуйста, подождите еще <b>{minutes_left} мин.</b>", parse_mode="HTML")
            return

    # 3. Переход в режим ожидания вопроса
    await state.set_state(SupportStates.waiting_for_question)
    cancel_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True)
    await message.answer(
        "📝 <b>Создание обращения</b>\n\nПожалуйста, опишите вашу проблему или задайте вопрос одним сообщением.\n"
        "Вы можете прикрепить скриншот, отправить голосовое сообщение или видео.", 
        reply_markup=cancel_kb, 
        parse_mode="HTML"
    )

@router.message(SupportStates.waiting_for_question)
async def process_initial_question(message: Message, state: FSMContext, bot: Bot):
    """Обработка первого сообщения тикета и отправка модераторам."""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("🔙 <i>Создание обращения отменено.</i>", reply_markup=main_kb, parse_mode="HTML")
        return

    user_id = message.from_user.id
    user_cooldowns[user_id] = time.time() # Активируем КД
    
    await message.answer(
        "✅ <b>Обращение успешно отправлено!</b>\n\n"
        "Администрация получила твой сигнал. Пожалуйста, ожидай ответа модератора в этом чате.\n"
        "<i>Пока модератор не подключился, дополнительные сообщения отправлять нельзя.</i>", 
        reply_markup=in_ticket_kb, 
        parse_mode="HTML"
    )
    await state.set_state(SupportStates.in_ticket)
    
    # Подготовка сообщения для админов
    user_full_name = html.escape(message.from_user.full_name)
    username = f"@{message.from_user.username}" if message.from_user.username else "нет юзернейма"
    
    header_info = (
        f"🚨 <b>НОВЫЙ ТИКЕТ ПОДДЕРЖКИ</b>\n"
        f"👤 Игрок: {user_full_name} ({username})\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"➖➖➖➖➖➖➖➖➖➖"
    )
    
    try:
        # Сначала отправляем текстовую шапку
        await bot.send_message(chat_id=MOD_GROUP_ID, text=header_info, message_thread_id=MOD_THREAD_ID, parse_mode="HTML")
        
        # Затем копируем само сообщение игрока с кнопкой "Взять"
        sent_ticket = await message.copy_to(
            chat_id=MOD_GROUP_ID, 
            message_thread_id=MOD_THREAD_ID, 
            reply_markup=get_take_ticket_kb(user_id)
        )
        
        # Сохраняем ID сообщения, чтобы потом убрать кнопку
        await state.update_data(mod_id=None, ticket_msg_id=sent_ticket.message_id)
        logging.info(f"Тикет от {user_id} успешно доставлен модераторам.")
    except Exception as e:
        logging.error(f"Критическая ошибка при пересылке тикета модераторам: {e}")
        await state.update_data(mod_id=None)

@router.message(SupportStates.in_ticket)
async def handle_messages_inside_ticket(message: Message, state: FSMContext, bot: Bot):
    """Обработка сообщений, когда тикет уже создан."""
    
    # Кнопка закрытия тикета со стороны игрока
    if message.text == "🔒 Закрыть обращение":
        data = await state.get_data()
        mod_id = data.get("mod_id")
        target_chat = mod_id if mod_id else MOD_GROUP_ID
        
        # Если тикет еще не взят, убираем кнопку из общей группы
        if not mod_id and data.get("ticket_msg_id"):
            try:
                await bot.edit_reply_markup(chat_id=MOD_GROUP_ID, message_id=data.get("ticket_msg_id"), reply_markup=None)
            except: pass
            
        await state.clear()
        await message.answer("🔒 <b>Диалог завершен.</b> Если понадобится помощь — пиши снова!", reply_markup=main_kb, parse_mode="HTML")
        
        # Уведомляем админа о закрытии
        try:
            notification = f"🔒 Игрок <code>{message.from_user.id}</code> самостоятельно закрыл обращение."
            await bot.send_message(chat_id=target_chat, message_thread_id=MOD_THREAD_ID if not mod_id else None, text=notification, parse_mode="HTML")
        except: pass
        return

    # Логика пересылки сообщений
    data = await state.get_data()
    mod_assigned_id = data.get("mod_id")
    
    if not mod_assigned_id:
        # Строгий режим: запрет на спам до взятия тикета модератором
        warning = "⏳ <b>Подождите!</b>\nВаш тикет еще находится в очереди. Дождитесь ответа модератора, прежде чем присылать что-то еще."
        await message.answer(warning, parse_mode="HTML")
        return
    
    # Если модератор уже взял тикет, просто пересылаем ему всё подряд
    try:
        await message.copy_to(chat_id=mod_assigned_id)
        await message.answer("📨 <i>Сообщение доставлено модератору.</i>", parse_mode="HTML")
    except Exception as e:
        logging.warning(f"Не удалось доставить сообщение от игрока админу {mod_assigned_id}: {e}")

# --- СИСТЕМА МОДЕРАТОРОВ (АДМИН-ПАНЕЛЬ) ---

@router.callback_query(F.data.startswith("take_ticket_"))
async def mod_take_ticket_handler(callback: CallbackQuery, bot: Bot):
    """Когда модератор нажимает 'Взять обращение'."""
    player_id = int(callback.data.split("_")[2])
    mod_id = callback.from_user.id
    
    # Получаем доступ к FSM игрока через специальный ключ StorageKey
    player_state_key = StorageKey(bot_id=bot.id, chat_id=player_id, user_id=player_id)
    player_fsm = FSMContext(storage=dp.storage, key=player_state_key)
    
    # Проверка: активен ли еще тикет?
    if await player_fsm.get_state() != SupportStates.in_ticket.state:
        await callback.answer("⚠️ Это обращение больше не актуально (закрыто игроком).", show_alert=True)
        try: await callback.message.edit_reply_markup(reply_markup=None)
        except: pass
        return

    # Пробуем написать модератору в ЛС
    try:
        confirm_text = f"✅ <b>Вы взяли тикет игрока</b> <code>{player_id}</code>\nТеперь пишите сообщения сюда, чтобы ответить ему."
        await bot.send_message(chat_id=mod_id, text=confirm_text, reply_markup=get_admin_ticket_kb(player_id), parse_mode="HTML")
    except Exception:
        await callback.answer("❌ Бот не может написать вам в ЛС! Сначала зайдите в бота и нажмите /start", show_alert=True)
        return

    # Обновляем данные игрока: закрепляем за ним модератора
    await player_fsm.update_data(mod_id=mod_id)
    
    # УБИРАЕМ КНОПКУ (Железно!)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except:
        pass
    
    # Обновляем визуально сообщение в группе
    mod_name = html.escape(callback.from_user.first_name)
    assignment_info = f"\n\n✅ <b>Взял в работу:</b> {mod_name}"
    
    try:
        if callback.message.text:
            await callback.message.edit_text(callback.message.text + assignment_info, parse_mode="HTML")
        elif callback.message.caption:
            await callback.message.edit_caption(caption=callback.message.caption + assignment_info, parse_mode="HTML")
        else:
            # Для стикеров/ГС/видео без подписи просто отвечаем текстом
            await callback.message.reply(assignment_info, parse_mode="HTML")
    except:
        try: await callback.message.reply(assignment_info, parse_mode="HTML")
        except: pass
        
    await callback.answer("Вы успешно взяли тикет!")
    logging.info(f"Модератор {mod_id} взял тикет игрока {player_id}")

@router.callback_query(F.data.startswith("reply_to_"))
async def admin_initiate_reply(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Админ нажал 'Ответить' в ЛС."""
    player_id = int(callback.data.split("_")[2])
    
    # Проверяем, не закрыл ли игрок тикет прямо сейчас
    p_key = StorageKey(bot_id=bot.id, chat_id=player_id, user_id=player_id)
    p_fsm = FSMContext(storage=dp.storage, key=p_key)
    
    if await p_fsm.get_state() != SupportStates.in_ticket.state:
        await callback.answer("⚠️ Ошибка: игрок уже закрыл этот диалог.", show_alert=True)
        return

    await state.update_data(reply_to=player_id)
    await state.set_state(AdminStates.waiting_for_reply)
    
    cancel_reply_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отменить отправку", callback_data="cancel_admin_reply")]])
    await callback.message.answer(f"✍️ <b>Введите ответ для</b> <code>{player_id}</code>:", reply_markup=cancel_reply_kb, parse_mode="HTML")
    await callback.answer()

@router.message(AdminStates.waiting_for_reply)
async def process_admin_response(message: Message, state: FSMContext, bot: Bot):
    """Отправка ответа админа игроку."""
    data = await state.get_data()
    player_id = data.get("reply_to")
    
    # Финальная проверка перед отправкой
    p_key = StorageKey(bot_id=bot.id, chat_id=player_id, user_id=player_id)
    p_fsm = FSMContext(storage=dp.storage, key=p_key)
    
    if await p_fsm.get_state() != SupportStates.in_ticket.state:
        await message.answer("❌ <b>Ошибка:</b> игрок закрыл тикет. Ответ не доставлен.")
        await state.clear()
        return
    
    try:
        # Уведомляем игрока, что это ответ поддержки
        await bot.send_message(chat_id=player_id, text="👨‍💻 <b>ОТВЕТ ОТ АДМИНИСТРАЦИИ:</b>", parse_mode="HTML")
        # Копируем само сообщение (любого типа)
        await message.copy_to(chat_id=player_id)
        await message.answer("✅ <b>Ответ успешно доставлен!</b>\n<i>Диалог остается открытым.</i>", parse_mode="HTML")
        logging.info(f"Админ ответил игроку {player_id}")
    except Exception as e:
        await message.answer(f"❌ <b>Ошибка доставки:</b> {e}")
    
    await state.clear()

@router.callback_query(F.data == "cancel_admin_reply")
async def cancel_admin_reply_callback(callback: CallbackQuery, state: FSMContext):
    """Отмена режима ответа у админа."""
    await state.clear()
    await callback.message.edit_text("🔙 <i>Отправка сообщения отменена.</i>", parse_mode="HTML")

@router.callback_query(F.data.startswith("close_ticket_"))
async def admin_close_ticket_handler(callback: CallbackQuery, bot: Bot):
    """Когда админ закрывает тикет игрока."""
    player_id = int(callback.data.split("_")[2])
    
    p_key = StorageKey(bot_id=bot.id, chat_id=player_id, user_id=player_id)
    p_fsm = FSMContext(storage=dp.storage, key=p_key)
    
    await p_fsm.clear() # Сбрасываем состояние игрока
    await callback.message.edit_text(f"🔒 <b>Тикет игрока</b> <code>{player_id}</code> <b>успешно закрыт.</b>", parse_mode="HTML")
    
    try:
        bye_text = "🔒 <b>Поддержка завершила ваш тикет.</b>\nЕсли проблема не решена — создайте новое обращение через меню."
        await bot.send_message(chat_id=player_id, text=bye_text, reply_markup=main_kb, parse_mode="HTML")
    except: 
        pass
    logging.info(f"Админ закрыл тикет игрока {player_id}")

# --- ФУНКЦИЯ: МАССОВАЯ РАССЫЛКА ---

@router.message(Command("broadcast"))
async def cmd_broadcast_start(message: Message, state: FSMContext):
    """Запуск рассылки (только для главного админа)."""
    if message.from_user.id != MAIN_ADMIN_ID:
        return
    
    await message.answer(
        "📣 <b>РЕЖИМ РАССЫЛКИ</b>\n\nОтправьте сообщение (любого типа), которое получат все пользователи бота.\n"
        "Для отмены напишите слово <code>отмена</code>.",
        parse_mode="HTML"
    )
    await state.set_state(AdminStates.waiting_for_broadcast)

@router.message(AdminStates.waiting_for_broadcast)
async def process_mass_broadcast(message: Message, state: FSMContext, bot: Bot):
    """Техническое выполнение рассылки."""
    if message.text and message.text.lower() == 'отмена':
        await state.clear()
        await message.answer("🔙 <i>Рассылка отменена.</i>", parse_mode="HTML")
        return

    user_list = get_all_users()
    if not user_list:
        await message.answer("⚠️ <b>Ошибка:</b> База пользователей пуста!")
        await state.clear()
        return

    await message.answer(f"🚀 <b>Начинаю рассылку на</b> <code>{len(user_list)}</code> <b>человек...</b>", parse_mode="HTML")
    
    success_count = 0
    blocked_count = 0
    
    for uid in user_list:
        try:
            # Используем copy_to для пересылки любого контента
            await message.copy_to(chat_id=uid)
            success_count += 1
            # Маленькая пауза, чтобы не получить бан от Telegram
            await asyncio.sleep(0.05)
        except:
            blocked_count += 1

    report = (
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"📦 Доставлено: <code>{success_count}</code>\n"
        f"🚫 Заблокировали бота: <code>{blocked_count}</code>"
    )
    await message.answer(report, parse_mode="HTML")
    await state.clear()
    logging.info(f"Рассылка выполнена: {success_count} успех, {blocked_count} блок.")

# ==========================================
# 🚀 ЗАПУСК БОТА
# ==========================================
async def main():
    """Точка входа в программу."""
    dp.include_router(router)
    
    # Очищаем старые сообщения, которые накопились пока бот был выключен
    await bot.delete_webhook(drop_pending_updates=True)
    
    print("-----------------------------------------")
    print("🤖 БОТ МИСАКРАФТ УСПЕШНО ЗАПУЩЕН!")
    print(f"📡 IP сервера: {SERVER_IP}")
    print("-----------------------------------------")
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот выключен пользователем.")
