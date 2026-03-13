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

# Информация о сервере
SERVER_IP = "play.misacraft.online"
SERVER_VERSION = "1.21.10"
DONATE_LINK = "https://site.misacraft.online/"
RULES_LINK = "https://site.misacraft.online/"
DISCORD_LINK = "https://discord.gg/69Jf7R4JFF"
USERS_FILE = "users.txt"

# Настройки антиспама
TICKET_COOLDOWN = 300  # Задержка между тикетами в секундах (300 = 5 минут)
user_cooldowns = {}    # Словарь для хранения времени последнего тикета

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
        [KeyboardButton(text="ℹ️ Частые вопросы (FAQ)")],
        [KeyboardButton(text="🆘 Написать в поддержку")],
        [KeyboardButton(text="🌐 Статус сервера")]
    ],
    resize_keyboard=True,
    input_field_placeholder="Выберите действие..."
)

in_ticket_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="ℹ️ Частые вопросы (FAQ)")],
        [KeyboardButton(text="🔒 Закрыть обращение")],
        [KeyboardButton(text="🌐 Статус сервера")]
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
async def cmd_start(message: Message, state: FSMContext):
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

@router.message(F.text == "ℹ️ Частые вопросы (FAQ)")
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

@router.message(F.text == "🌐 Статус сервера")
async def server_status(message: Message):
    wait_msg = await message.answer("🔄 <i>Опрашиваю сервер...</i>", parse_mode="HTML")
    try:
        server = await JavaServer.async_lookup(SERVER_IP)
        status = await server.async_status()
        text = (
            f"🟢 <b>Misacraft работает стабильно!</b>\n\n"
            f"👥 Игроков онлайн: <code>{status.players.online}/{status.players.max}</code>\n"
            f"IP: <code>{SERVER_IP}</code>\n"
            f"🔥 <i>Залетай, ждем тебя!</i>"
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
async def ask_support(message: Message, state: FSMContext):
    user_id = message.from_user.id
    current_time = time.time()
    
    # Проверка антиспама: если игрок уже есть в базе задержек
    if user_id in user_cooldowns:
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
        target_id = mod_id if mod_id else MOD_GROUP_ID
        thread_id = None if mod_id else MOD_THREAD_ID

        await state.clear()
        await message.answer("✅ <b>Обращение закрыто.</b>\n\nЕсли появятся новые вопросы - смело пиши снова!", reply_markup=main_kb, parse_mode="HTML")
        try:
            await bot.send_message(chat_id=target_id, message_thread_id=thread_id, text=f"🔒 Игрок <code>{message.from_user.id}</code> самостоятельно закрыл свое обращение.", parse_mode="HTML")
        except:
            pass
    else:
        await message.answer("У вас нет активных обращений.", reply_markup=main_kb)

@router.message(SupportStates.waiting_for_question, F.text | F.photo)
async def process_support_question(message: Message, state: FSMContext):
    user_id = message.from_user.id
    username = f"@{message.from_user.username}" if message.from_user.username else "Без юзернейма"
    
    # Фиксируем время создания тикета (активируем задержку для игрока)
    user_cooldowns[user_id] = time.time()
    
    await message.answer(
        "✅ <b>Обращение успешно создано!</b>\n\n"
        "Администрация уже получила твое сообщение. Обычно мы отвечаем в течение дня.\n"
        "Ты можешь присылать сюда дополнительные детали или скриншоты, пока диалог открыт.",
        reply_markup=in_ticket_kb,
        parse_mode="HTML"
    )
    await state.set_state(SupportStates.in_ticket)
    await state.update_data(mod_id=None)
    
    text_content = message.text or message.caption or "<Только фото>"
    safe_name = html.escape(message.from_user.full_name)
    safe_text = html.escape(text_content)
    
    admin_text = (
        f"🚨 <b>Новый тикет поддержки</b>\n\n"
        f"👤 <b>Пользователь:</b> {safe_name} ({username})\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"{safe_text}"
    )
    try:
        if message.photo:
            await bot.send_photo(chat_id=MOD_GROUP_ID, message_thread_id=MOD_THREAD_ID, photo=message.photo[-1].file_id, caption=admin_text, reply_markup=get_take_ticket_kb(user_id), parse_mode="HTML")
        else:
            await bot.send_message(chat_id=MOD_GROUP_ID, message_thread_id=MOD_THREAD_ID, text=admin_text, reply_markup=get_take_ticket_kb(user_id), parse_mode="HTML")
    except Exception as e:
        logging.error(f"Ошибка отправки в группу модераторов: {e}")

@router.message(SupportStates.in_ticket, F.text | F.photo)
async def process_additional_ticket_message(message: Message, state: FSMContext):
    user_id = message.from_user.id
    text_content = message.text or message.caption or "<Только фото>"
    safe_text = html.escape(text_content)
    
    admin_text = (
        f"💬 <b>Новое сообщение в тикет от</b> <code>{user_id}</code>:\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"{safe_text}"
    )
    
    player_data = await state.get_data()
    mod_id = player_data.get("mod_id")
    
    target_id = mod_id if mod_id else MOD_GROUP_ID
    thread_id = None if mod_id else MOD_THREAD_ID
    kb = get_admin_ticket_kb(user_id) if mod_id else get_take_ticket_kb(user_id)
    
    try:
        if message.photo:
            await bot.send_photo(chat_id=target_id, message_thread_id=thread_id, photo=message.photo[-1].file_id, caption=admin_text, reply_markup=kb, parse_mode="HTML")
        else:
            await bot.send_message(chat_id=target_id, message_thread_id=thread_id, text=admin_text, reply_markup=kb, parse_mode="HTML")
        await message.answer("📨 <i>Сообщение добавлено к обращению.</i>", parse_mode="HTML")
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
async def admin_start_reply(callback: CallbackQuery, state: FSMContext):
    player_id = int(callback.data.split("_")[2])
    await state.update_data(reply_to_user=player_id)
    await state.set_state(AdminStates.waiting_for_reply)
    
    await callback.message.answer(
        f"✍️ Напиши ответ для пользователя <code>{player_id}</code>.\n"
        f"<i>(Можно прикрепить фото. Для отмены напиши 'отмена')</i>", 
        parse_mode="HTML"
    )
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

@router.message(AdminStates.waiting_for_reply, F.text | F.photo)
async def process_admin_reply(message: Message, state: FSMContext):
    if message.text and message.text.lower() == 'отмена':
        await state.clear()
        await message.answer("🔙 <i>Отправка ответа отменена.</i>", parse_mode="HTML")
        return

    data = await state.get_data()
    player_id = data.get("reply_to_user")
    
    text_content = message.text or message.caption or ""
    safe_text = html.escape(text_content)
    
    reply_text = (
        f"👨‍💻 <b>Ответ от администрации:</b>\n\n"
        f"{safe_text}"
    )
    
    try:
        if message.photo:
            await bot.send_photo(chat_id=player_id, photo=message.photo[-1].file_id, caption=reply_text, parse_mode="HTML")
        else:
            await bot.send_message(chat_id=player_id, text=reply_text, parse_mode="HTML")
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
        "Отправь текст (или фото с текстом), который получат <b>все</b> пользователи бота.\n"
        "<i>(Для отмены напиши <code>отмена</code>)</i>",
        parse_mode="HTML"
    )
    await state.set_state(AdminStates.waiting_for_broadcast)

@router.message(AdminStates.waiting_for_broadcast, F.text | F.photo)
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
    
    text_content = message.text or message.caption or ""
    safe_text = html.escape(text_content)
    
    for user_id in users:
        try:
            if message.photo:
                await bot.send_photo(chat_id=user_id, photo=message.photo[-1].file_id, caption=safe_text, parse_mode="HTML")
            else:
                await bot.send_message(chat_id=user_id, text=safe_text, parse_mode="HTML")
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
