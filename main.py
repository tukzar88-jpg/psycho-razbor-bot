import os
import logging
import base64
import re

from google import genai
from supabase import create_client, Client

from telegram import (
    Update,
    ReplyKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ============================================================
# НАСТРОЙКИ
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not TELEGRAM_TOKEN:
    raise RuntimeError(
        "TELEGRAM_BOT_TOKEN не задан в Railway"
    )

if not GEMINI_API_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY не задан в Railway"
    )

if not SUPABASE_URL:
    raise RuntimeError(
        "SUPABASE_URL не задан в Railway"
    )

if not SUPABASE_KEY:
    raise RuntimeError(
        "SUPABASE_KEY не задан в Railway"
    )

# ============================================================
# КЛИЕНТЫ
# ============================================================

gemini = genai.Client(
    api_key=GEMINI_API_KEY
)

supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)

MODEL = "gemini-3.6-flash"

# ============================================================
# СОСТОЯНИЯ
# ============================================================

PROFILE_NAME = 1
PROFILE_AGE = 2
PROFILE_GENDER = 3

user_modes = {}
user_profile_state = {}

# ============================================================
# ГЛАВНОЕ МЕНЮ
# ============================================================

MAIN_KEYBOARD = [
    ["💬 Разбор переписки"],
    ["📸 Анализ скриншота"],
    ["🧠 Разбор ситуации"],
    ["❤️ Отношения", "😰 Тревога и стресс"],
    ["🧪 Психологический тест"],
    ["📚 Мои разборы", "⚙️ Мой профиль"],
]

GENDER_KEYBOARD = [
    ["👨 Мужчина", "👩 Женщина"],
]


def main_keyboard():
    return ReplyKeyboardMarkup(
        MAIN_KEYBOARD,
        resize_keyboard=True
    )


# ============================================================
# ОЧИСТКА MARKDOWN
# ============================================================

def clean_markdown(text):
    if not text:
        return ""

    text = re.sub(
        r"\*\*(.*?)\*\*",
        r"\1",
        text,
        flags=re.DOTALL
    )

    text = re.sub(
        r"(?<!\*)\*(?!\s)(.*?)(?<!\s)\*(?!\*)",
        r"\1",
        text,
        flags=re.DOTALL
    )

    text = re.sub(
        r"__(.*?)__",
        r"\1",
        text,
        flags=re.DOTALL
    )

    text = re.sub(
        r"(?m)^\s*#{1,6}\s*",
        "",
        text
    )

    text = re.sub(
        r"(?m)^\s*>\s?",
        "",
        text
    )

    text = text.replace("```", "")
    text = text.replace("`", "")

    text = re.sub(
        r"[ \t]+\n",
        "\n",
        text
    )

    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text
    )

    return text.strip()


# ============================================================
# ПОЛУЧЕНИЕ ПРОФИЛЯ
# ============================================================

def get_profile(user_id):

    try:

        response = (
            supabase
            .table("users")
            .select("*")
            .eq("telegram_id", user_id)
            .limit(1)
            .execute()
        )

        if response.data:
            return response.data[0]

    except Exception as e:

        logging.exception(
            "Ошибка получения профиля: %s",
            e
        )

    return None


# ============================================================
# СОХРАНЕНИЕ ПРОФИЛЯ
# ============================================================

def save_profile(
    user_id,
    name,
    age,
    gender
):

    try:

        existing = get_profile(user_id)

        data = {
            "telegram_id": user_id,
            "name": name,
            "age": age,
            "gender": gender,
        }

        if existing:

            (
                supabase
                .table("users")
                .update(data)
                .eq("telegram_id", user_id)
                .execute()
            )

        else:

            (
                supabase
                .table("users")
                .insert(data)
                .execute()
            )

        logging.info(
            "Профиль сохранён: %s",
            user_id
        )

        return True

    except Exception as e:

        logging.exception(
            "Ошибка сохранения профиля: %s",
            e
        )

        return False


# ============================================================
# ТЕКСТ ПРОФИЛЯ
# ============================================================

def profile_text(profile):

    if not profile:

        return (
            "⚙️ МОЙ ПРОФИЛЬ\n\n"
            "Профиль пока не заполнен."
        )

    name = profile.get("name") or "Не указано"
    age = profile.get("age") or "Не указан"
    gender = profile.get("gender") or "Не указан"

    if gender == "male":
        gender_text = "Мужчина"

    elif gender == "female":
        gender_text = "Женщина"

    else:
        gender_text = str(gender)

    return (
        "⚙️ МОЙ ПРОФИЛЬ\n\n"
        f"👤 Имя: {name}\n"
        f"🎂 Возраст: {age}\n"
        f"⚧ Пол: {gender_text}\n\n"
        "Эти данные учитываются при анализе."
    )


# ============================================================
# КОНТЕКСТ ПРОФИЛЯ ДЛЯ GEMINI
# ============================================================

def profile_context(profile):

    if not profile:

        return (
            "Профиль пользователя не заполнен."
        )

    name = profile.get("name") or "не указано"
    age = profile.get("age") or "не указан"
    gender = profile.get("gender") or "не указан"

    return (
        "ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ:\n"
        f"Имя: {name}\n"
        f"Возраст: {age}\n"
        f"Пол: {gender}\n\n"
        "Учитывай эти данные при анализе "
        "и формулировке рекомендаций."
    )


# ============================================================
# СОХРАНЕНИЕ АНАЛИЗА
# ============================================================

def save_analysis(
    user_id,
    analysis_type,
    user_text,
    answer
):

    try:

        data = {
            "telegram_id": user_id,
            "analysis_type": analysis_type,
            "user_message": user_text[:10000],
            "result": answer[:30000],
        }

        response = (
            supabase
            .table("analyses")
            .insert(data)
            .execute()
        )

        logging.info(
            "Анализ успешно сохранён: %s",
            response.data
        )

        return True

    except Exception as e:

        logging.exception(
            "ОШИБКА СОХРАНЕНИЯ АНАЛИЗА: %s",
            e
        )

        return False


# ============================================================
# ОТПРАВКА ДЛИННОГО СООБЩЕНИЯ
# ============================================================

async def send_long_message(
    update,
    text
):

    if not text:
        return

    text = clean_markdown(text)

    for i in range(
        0,
        len(text),
        4000
    ):

        await update.message.reply_text(
            text[i:i + 4000]
        )


# ============================================================
# ОСНОВНОЙ ПРОМПТ
# ============================================================

SYSTEM_PROMPT = """
Ты — ПСИХОРАЗБОР.

Ты умный, прямой и эмпатичный AI-помощник
по отношениям, перепискам и жизненным ситуациям.

Твоя задача — помогать человеку понять происходящее
и давать конкретные практические рекомендации.

ВАЖНЫЕ ПРАВИЛА:

• Не ставь медицинских или психиатрических диагнозов.
• Не утверждай, что точно знаешь мысли другого человека.
• Отделяй факты от предположений.
• Не придумывай отсутствующие факты.
• Если информации недостаточно — скажи об этом.
• Не поддерживай опасное или токсичное поведение.
• Не читай пользователю мораль.
• Отвечай простым человеческим языком.

СТРОГОЕ ПРАВИЛО ФОРМАТИРОВАНИЯ:

Никогда не используй Markdown.

Не используй:

**
*
#
>

Не используй жирный текст.
Не используй курсив.
Не используй Markdown-заголовки.

Используй обычный текст.

Для списков используй:

• пункт

Для нумерованных вариантов:

1. вариант
2. вариант
3. вариант

Эмодзи использовать можно.

Текст должен выглядеть естественно
в сообщении Telegram.

Никогда не ставь звёздочки вокруг слов.
"""


# ============================================================
# ПРОМПТ РАЗБОРА ПЕРЕПИСКИ
# ============================================================

CHAT_PROMPT = """
Пользователь прислал переписку.

Сделай разбор:

🔥 РАЗБОР ПЕРЕПИСКИ

📊 ИНТЕРЕС: X/10

Оцени уровень заинтересованности человека
только по признакам, которые реально видны
в переписке.

💬 ИНИЦИАТИВА

Определи:

• кто чаще начинает разговор;
• кто задаёт вопросы;
• кто поддерживает диалог;
• кто предлагает темы;
• кто предлагает встречу;
• кто отвечает односложно.

🟢 ПРИЗНАКИ ИНТЕРЕСА

Укажи конкретные моменты переписки.

🔴 ЧТО НАСТОРАЖИВАЕТ

Укажи конкретные моменты,
которые могут говорить о дистанции
или снижении интереса.

🧠 МОЙ ВЫВОД

Дай честный вывод.

Не говори:
"она точно тебя любит"
или:
"она точно тебя не любит".

Объясни наиболее вероятный вариант.

🎯 ЧТО ДЕЛАТЬ

Дай 2–4 конкретных действия.

✍️ ЧТО НАПИСАТЬ

Предложи три варианта:

1. Спокойный
2. Уверенный
3. Дерзкий

Варианты должны быть естественными
для Telegram.

Не используй Markdown.
"""


# ============================================================
# ПРОМПТ СКРИНШОТА
# ============================================================

SCREENSHOT_PROMPT = """
На изображении находится переписка между людьми.

Внимательно прочитай текст на изображении
и сделай анализ переписки.

Если какие-то сообщения плохо видны,
не придумывай их.

Используй структуру:

🔥 РАЗБОР СКРИНШОТА

📊 ИНТЕРЕС: X/10

💬 ИНИЦИАТИВА

Определи:

• кто чаще пишет первым;
• кто задаёт вопросы;
• кто поддерживает разговор;
• кто пытается продолжить общение;
• кто предлагает встречу;
• кто отвечает односложно.

🟢 ПРИЗНАКИ ИНТЕРЕСА

Укажи конкретные сообщения
или особенности переписки.

🔴 ЧТО НАСТОРАЖИВАЕТ

Укажи признаки дистанции,
холодности или слабой инициативы.

🧠 ЧТО, СКОРЕЕ ВСЕГО, ПРОИСХОДИТ

Дай наиболее вероятное объяснение.

Важно:
ты не можешь точно знать мысли человека.

🎯 ЧТО ДЕЛАТЬ

Дай конкретные рекомендации.

✍️ ЧТО НАПИСАТЬ

Предложи три варианта:

1. Спокойный
2. Уверенный
3. Дерзкий

Если изображение плохо читается,
честно сообщи об этом.

Не используй Markdown.
"""


# ============================================================
# ПРОМПТ СИТУАЦИИ
# ============================================================

SITUATION_PROMPT = """
Пользователь описал ситуацию.

Сделай разбор:

🔎 ЧТО ПРОИСХОДИТ

Кратко объясни ситуацию.

🧠 ВОЗМОЖНЫЕ ПРИЧИНЫ

Дай несколько наиболее вероятных объяснений.

⚠️ ЧТО НАСТОРАЖИВАЕТ

Укажи возможные проблемные моменты.

🎯 ЧТО ДЕЛАТЬ

Дай конкретные действия.

✍️ ЧТО МОЖНО СКАЗАТЬ

Если нужен разговор или сообщение,
предложи конкретный вариант.

Не выдавай предположения за факты.
"""


# ============================================================
# ПРОМПТ ОТНОШЕНИЙ
# ============================================================

RELATIONSHIP_PROMPT = """
Пользователь рассказал о проблеме в отношениях.

Разбери:

❤️ ЧТО ПРОИСХОДИТ

🔎 ВОЗМОЖНЫЕ ПРИЧИНЫ

⚠️ ПРОБЛЕМНЫЕ МОМЕНТЫ

🧠 ЧТО МОЖЕТ ПРОИСХОДИТЬ

🎯 ЧТО ДЕЛАТЬ ДАЛЬШЕ

✍️ ЧТО МОЖНО НАПИСАТЬ

Давай конкретные рекомендации.

Не ставь диагнозы.
Не утверждай, что точно знаешь мысли
другого человека.
"""


# ============================================================
# ПРОМПТ ТРЕВОГИ
# ============================================================

STRESS_PROMPT = """
Пользователь рассказал о тревоге или стрессе.

Ответь спокойно и практично.

Используй:

😰 ЧТО ПРОИСХОДИТ

🧠 ПОЧЕМУ ТАК МОЖЕТ ПРОИСХОДИТЬ

🎯 ЧТО МОЖНО СДЕЛАТЬ ПРЯМО СЕЙЧАС

💡 ЧТО ПОМОЖЕТ В ДОЛГОСРОЧНОЙ ПЕРСПЕКТИВЕ

Не ставь медицинских диагнозов.
"""


# ============================================================
# START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    user_modes[user_id] = None

    profile = get_profile(user_id)

    if not profile:

        user_profile_state[user_id] = {
            "step": PROFILE_NAME,
            "name": None,
            "age": None,
            "gender": None,
        }

        await update.message.reply_text(
            "🧠 ПСИХОРАЗБОР\n\n"
            "Привет! Давай сначала создадим твой профиль.\n\n"
            "Как тебя зовут?"
        )

        return

    await update.message.reply_text(
        "🧠 ПСИХОРАЗБОР\n\n"
        f"С возвращением, {profile.get('name', '')}! 👋\n\n"
        "Выбирай нужный раздел 👇",
        reply_markup=main_keyboard()
    )


# ============================================================
# ПРОФИЛЬ
# ============================================================

async def handle_profile(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id
    text = update.message.text.strip()

    state = user_profile_state.get(user_id)

    if not state:
        return False

    step = state["step"]

    # --------------------------------------------------------
    # ИМЯ
    # --------------------------------------------------------

    if step == PROFILE_NAME:

        if len(text) < 2 or len(text) > 50:

            await update.message.reply_text(
                "Напиши имя от 2 до 50 символов."
            )

            return True

        state["name"] = text
        state["step"] = PROFILE_AGE

        await update.message.reply_text(
            "Отлично 👍\n\n"
            "Сколько тебе лет?"
        )

        return True

    # --------------------------------------------------------
    # ВОЗРАСТ
    # --------------------------------------------------------

    if step == PROFILE_AGE:

        if not text.isdigit():

            await update.message.reply_text(
                "Напиши возраст цифрами, например: 25"
            )

            return True

        age = int(text)

        if age < 13 or age > 100:

            await update.message.reply_text(
                "Укажи возраст от 13 до 100 лет."
            )

            return True

        state["age"] = age
        state["step"] = PROFILE_GENDER

        await update.message.reply_text(
            "Теперь укажи пол 👇",
            reply_markup=ReplyKeyboardMarkup(
                GENDER_KEYBOARD,
                resize_keyboard=True,
                one_time_keyboard=True
            )
        )

        return True

    # --------------------------------------------------------
    # ПОЛ
    # --------------------------------------------------------

    if step == PROFILE_GENDER:

        if text == "👨 Мужчина":

            gender = "male"

        elif text == "👩 Женщина":

            gender = "female"

        else:

            await update.message.reply_text(
                "Выбери один из вариантов 👇",
                reply_markup=ReplyKeyboardMarkup(
                    GENDER_KEYBOARD,
                    resize_keyboard=True,
                    one_time_keyboard=True
                )
            )

            return True

        state["gender"] = gender

        success = save_profile(
            user_id,
            state["name"],
            state["age"],
            gender
        )

        if not success:

            await update.message.reply_text(
                "❌ Не удалось сохранить профиль.\n\n"
                "Проверь настройки Supabase."
            )

            return True

        user_profile_state.pop(
            user_id,
            None
        )

        gender_text = (
            "Мужчина"
            if gender == "male"
            else "Женщина"
        )

        await update.message.reply_text(
            "✅ Профиль сохранён!\n\n"
            f"👤 Имя: {state['name']}\n"
            f"🎂 Возраст: {state['age']}\n"
            f"⚧ Пол: {gender_text}\n\n"
            "Теперь я буду учитывать эти данные "
            "при анализе.",
            reply_markup=main_keyboard()
        )

        return True

    return False


# ============================================================
# МОЙ ПРОФИЛЬ
# ============================================================

async def profile_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    profile = get_profile(user_id)

    await update.message.reply_text(
        profile_text(profile),
        reply_markup=main_keyboard()
    )


# ============================================================
# МОИ РАЗБОРЫ
# ============================================================

async def my_analyses(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    try:

        response = (
            supabase
            .table("analyses")
            .select("*")
            .eq("telegram_id", user_id)
            .order("created_at", desc=True)
            .limit(10)
            .execute()
        )

        analyses = response.data or []

        if not analyses:

            await update.message.reply_text(
                "📚 МОИ РАЗБОРЫ\n\n"
                "У тебя пока нет сохранённых разборов.\n\n"
                "Сделай первый анализ — и он появится здесь.",
                reply_markup=main_keyboard()
            )

            return

        text = (
            "📚 МОИ РАЗБОРЫ\n\n"
            f"Последние разборы: {len(analyses)}\n\n"
        )

        for index, item in enumerate(
            analyses,
            start=1
        ):

            analysis_type = item.get(
                "analysis_type",
                "Разбор"
            )

            user_message = item.get(
                "user_message",
                ""
            )

            created_at = item.get(
                "created_at",
                ""
            )

            if len(user_message) > 150:

                user_message = (
                    user_message[:150]
                    + "..."
                )

            text += (
                f"{index}. {analysis_type}\n"
                f"📝 {user_message}\n"
                f"🕐 {created_at}\n\n"
            )

        await send_long_message(
            update,
            text
        )

    except Exception as e:

        logging.exception(
            "Ошибка получения истории: %s",
            e
        )

        await update.message.reply_text(
            "❌ Ошибка при получении разборов:\n\n"
            + str(e)[:2000]
        )


# ============================================================
# СКРИНШОТ
# ============================================================

async def handle_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    await update.message.reply_text(
        "📸 Получил скриншот.\n\n"
        "🧠 Читаю переписку и анализирую..."
    )

    try:

        profile = get_profile(user_id)

        photo = update.message.photo[-1]

        telegram_file = (
            await context.bot.get_file(
                photo.file_id
            )
        )

        image_bytes = (
            await telegram_file.download_as_bytearray()
        )

        image_b64 = base64.b64encode(
            bytes(image_bytes)
        ).decode("utf-8")

        prompt = (
            SYSTEM_PROMPT
            + "\n\n"
            + profile_context(profile)
            + "\n\n"
            + SCREENSHOT_PROMPT
        )

        response = gemini.interactions.create(
            model=MODEL,
            input=[
                {
                    "type": "text",
                    "text": prompt
                },
                {
                    "type": "image",
                    "data": image_b64,
                    "mime_type": "image/jpeg"
                }
            ]
        )

        answer = response.output_text

        if not answer:

            raise RuntimeError(
                "Gemini вернул пустой ответ"
            )

        answer = clean_markdown(answer)

        saved = save_analysis(
            user_id,
            "Анализ скриншота",
            "Скриншот переписки",
            answer
        )

        if not saved:

            logging.warning(
                "Скриншот проанализирован, "
                "но не сохранён"
            )

        await send_long_message(
            update,
            answer
        )

    except Exception as e:

        logging.exception(
            "Ошибка анализа скриншота: %s",
            e
        )

        await update.message.reply_text(
            "❌ Ошибка при анализе скриншота:\n\n"
            + str(e)[:3000]
        )


# ============================================================
# ТЕКСТОВЫЕ СООБЩЕНИЯ
# ============================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id
    text = update.message.text.strip()

    # --------------------------------------------------------
    # ПРОФИЛЬ
    # --------------------------------------------------------

    if user_id in user_profile_state:

        handled = await handle_profile(
            update,
            context
        )

        if handled:
            return

    # --------------------------------------------------------
    # РАЗБОР ПЕРЕПИСКИ
    # --------------------------------------------------------

    if text == "💬 Разбор переписки":

        user_modes[user_id] = "chat"

        await update.message.reply_text(
            "💬 Пришли переписку целиком.\n\n"
            "Можно просто скопировать сообщения "
            "и отправить их сюда."
        )

        return

    # --------------------------------------------------------
    # СКРИНШОТ
    # --------------------------------------------------------

    if text == "📸 Анализ скриншота":

        user_modes[user_id] = "screenshot"

        await update.message.reply_text(
            "📸 Пришли скриншот переписки."
        )

        return

    # --------------------------------------------------------
    # СИТУАЦИЯ
    # --------------------------------------------------------

    if text == "🧠 Разбор ситуации":

        user_modes[user_id] = "situation"

        await update.message.reply_text(
            "🧠 Опиши ситуацию своими словами."
        )

        return

    # --------------------------------------------------------
    # ОТНОШЕНИЯ
    # --------------------------------------------------------

    if text == "❤️ Отношения":

        user_modes[user_id] = "relationship"

        await update.message.reply_text(
            "❤️ Расскажи, что происходит "
            "в отношениях."
        )

        return

    # --------------------------------------------------------
    # ТРЕВОГА
    # --------------------------------------------------------

    if text == "😰 Тревога и стресс":

        user_modes[user_id] = "stress"

        await update.message.reply_text(
            "😰 Расскажи, что тебя сейчас беспокоит."
        )

        return

    # --------------------------------------------------------
    # ТЕСТ
    # --------------------------------------------------------

    if text == "🧪 Психологический тест":

        await update.message.reply_text(
            "🧪 Раздел тестов пока готовится."
        )

        return

    # --------------------------------------------------------
    # МОИ РАЗБОРЫ
    # --------------------------------------------------------

    if text == "📚 Мои разборы":

        await my_analyses(
            update,
            context
        )

        return

    # --------------------------------------------------------
    # ПРОФИЛЬ
    # --------------------------------------------------------

    if text == "⚙️ Мой профиль":

        await profile_menu(
            update,
            context
        )

        return

    # --------------------------------------------------------
    # ТЕКУЩИЙ РЕЖИМ
    # --------------------------------------------------------

    mode = user_modes.get(user_id)

    if mode == "screenshot":

        await update.message.reply_text(
            "📸 Для этого режима отправь "
            "именно скриншот."
        )

        return

    if not mode:

        await update.message.reply_text(
            "Выбери раздел в меню 👇",
            reply_markup=main_keyboard()
        )

        return

    # --------------------------------------------------------
    # ПРОФИЛЬ
    # --------------------------------------------------------

    profile = get_profile(user_id)

    # --------------------------------------------------------
    # ПРОМПТ
    # --------------------------------------------------------

    if mode == "chat":

        task = CHAT_PROMPT
        analysis_type = "Разбор переписки"

    elif mode == "situation":

        task = SITUATION_PROMPT
        analysis_type = "Разбор ситуации"

    elif mode == "relationship":

        task = RELATIONSHIP_PROMPT
        analysis_type = "Отношения"

    else:

        task = STRESS_PROMPT
        analysis_type = "Тревога и стресс"

    prompt = (
        SYSTEM_PROMPT
        + "\n\n"
        + profile_context(profile)
        + "\n\n"
        + task
        + "\n\n"
        + "СООБЩЕНИЕ ПОЛЬЗОВАТЕЛЯ:\n"
        + text
    )

    await update.message.reply_text(
        "🧠 Анализирую..."
    )

    try:

        response = gemini.interactions.create(
            model=MODEL,
            input=prompt
        )

        answer = response.output_text

        if not answer:

            raise RuntimeError(
                "Gemini вернул пустой ответ"
            )

        answer = clean_markdown(answer)

        # ----------------------------------------------------
        # СОХРАНЯЕМ АНАЛИЗ
        # ----------------------------------------------------

        saved = save_analysis(
            user_id,
            analysis_type,
            text,
            answer
        )

        if saved:

            logging.info(
                "История анализа сохранена."
            )

        else:

            logging.error(
                "Ответ отправлен, "
                "но история не сохранилась."
            )

        await send_long_message(
            update,
            answer
        )

    except Exception as e:

        logging.exception(
            "Ошибка Gemini: %s",
            e
        )

        await update.message.reply_text(
            "❌ Ошибка Gemini:\n\n"
            + str(e)[:3000]
        )


# ============================================================
# КОМАНДЫ
# ============================================================

async def history_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await my_analyses(
        update,
        context
    )


async def profile_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await profile_menu(
        update,
        context
    )


# ============================================================
# ЗАПУСК
# ============================================================

def main():

    print(
        "🧠 ПСИХОРАЗБОР запускается..."
    )

    app = (
        Application
        .builder()
        .token(TELEGRAM_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        CommandHandler(
            "history",
            history_command
        )
    )

    app.add_handler(
        CommandHandler(
            "profile",
            profile_command
        )
    )

    app.add_handler(
        MessageHandler(
            filters.PHOTO,
            handle_photo
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    print(
        "🟢 ПСИХОРАЗБОР успешно запущен."
    )

    app.run_polling()


if __name__ == "__main__":
    main()
