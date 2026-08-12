import os
import logging
import base64
import re

from google import genai
from supabase import create_client, Client

from telegram import Update, ReplyKeyboardMarkup
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
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY")


if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN не задан в Railway")

if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY не задан в Railway")

if not SUPABASE_URL:
    raise RuntimeError("SUPABASE_URL не задан в Railway")

if not SUPABASE_SECRET_KEY:
    raise RuntimeError("SUPABASE_SECRET_KEY не задан в Railway")


# ============================================================
# GEMINI
# ============================================================

client = genai.Client(
    api_key=GEMINI_API_KEY
)

MODEL = "gemini-3.6-flash"


# ============================================================
# SUPABASE
# ============================================================

supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_SECRET_KEY
)


# ============================================================
# МЕНЮ
# ============================================================

keyboard = [
    ["💬 Разбор переписки"],
    ["📸 Анализ скриншота"],
    ["🧠 Разбор ситуации"],
    ["❤️ Отношения", "😰 Тревога и стресс"],
    ["🧪 Психологический тест"],
    ["⚙️ Мой профиль"],
    ["📚 Мои разборы"],
]

profile_keyboard = [
    ["✏️ Изменить профиль"],
    ["⬅️ Главное меню"],
]

history_keyboard = [
    ["⬅️ Главное меню"],
]

gender_keyboard = [
    ["👨 Мужской", "👩 Женский"],
    ["Не хочу указывать"],
]


# ============================================================
# ВРЕМЕННЫЕ ДАННЫЕ
# ============================================================

user_modes = {}
user_profile_steps = {}
profile_cache = {}


# ============================================================
# SUPABASE — ПРОФИЛЬ
# ============================================================

def get_user_profile(user_id):

    try:

        result = (
            supabase
            .table("users")
            .select(
                "telegram_id, name, age, gender"
            )
            .eq(
                "telegram_id",
                user_id
            )
            .limit(1)
            .execute()
        )

        if result.data:
            return result.data[0]

        return None

    except Exception:

        logging.exception(
            "Ошибка получения профиля %s",
            user_id
        )

        return None


def save_user_profile(
    user_id,
    name,
    age,
    gender
):

    data = {
        "telegram_id": user_id,
        "name": name,
        "age": age,
        "gender": gender,
    }

    result = (
        supabase
        .table("users")
        .upsert(
            data,
            on_conflict="telegram_id"
        )
        .execute()
    )

    logging.info(
        "Профиль %s сохранён",
        user_id
    )

    return result.data


def profile_complete(profile):

    if not profile:
        return False

    return (
        profile.get("name") is not None
        and str(profile.get("name")).strip() != ""
        and profile.get("age") is not None
        and profile.get("gender") is not None
    )


# ============================================================
# СОХРАНЕНИЕ РАЗБОРА
# ============================================================

def save_analysis(
    user_id,
    analysis_type,
    user_message,
    result
):

    try:

        data = {
            "telegram_id": user_id,
            "analysis_type": analysis_type,
            "user_message": user_message[:10000],
            "result": result[:30000],
        }

        supabase \
            .table("analyses") \
            .insert(data) \
            .execute()

        logging.info(
            "Разбор сохранён: user=%s type=%s",
            user_id,
            analysis_type
        )

    except Exception:

        logging.exception(
            "Ошибка сохранения разбора"
        )


# ============================================================
# ПОЛУЧЕНИЕ ИСТОРИИ
# ============================================================

def get_analysis_history(user_id):

    try:

        result = (
            supabase
            .table("analyses")
            .select(
                "id, analysis_type, result, created_at"
            )
            .eq(
                "telegram_id",
                user_id
            )
            .order(
                "created_at",
                desc=True
            )
            .limit(10)
            .execute()
        )

        return result.data or []

    except Exception:

        logging.exception(
            "Ошибка получения истории"
        )

        return []


# ============================================================
# ОЧИСТКА MARKDOWN
# ============================================================

def clean_markdown(text):

    if not text:
        return text

    text = re.sub(
        r"\*\*(.*?)\*\*",
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
        r"(?<!\*)\*(?!\s)(.*?)(?<!\s)\*(?!\*)",
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
# ПРОФИЛЬ ДЛЯ GEMINI
# ============================================================

def get_profile_text(profile):

    if not profile:
        return ""

    return (
        "\n\n"
        "ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ:\n"
        f"Имя: {profile.get('name', '')}\n"
        f"Возраст: {profile.get('age', '')}\n"
        f"Пол: {profile.get('gender', '')}\n\n"
        "Учитывай профиль при анализе. "
        "Не делай необоснованных выводов только "
        "на основании возраста или пола.\n"
    )


# ============================================================
# SYSTEM PROMPT
# ============================================================

SYSTEM_PROMPT = """
Ты — ПСИХОРАЗБОР.

Ты умный, прямой и эмпатичный AI-помощник
по отношениям, перепискам и жизненным ситуациям.

Твоя задача — помогать человеку понять происходящее
и давать конкретные практические рекомендации.

ВАЖНЫЕ ПРАВИЛА:

- Не ставь медицинских или психиатрических диагнозов.
- Не утверждай, что точно знаешь мысли другого человека.
- Отделяй факты от предположений.
- Не придумывай отсутствующие факты.
- Если информации недостаточно — скажи об этом.
- Не поддерживай опасное или токсичное поведение.
- Не читай пользователю мораль.
- Отвечай простым человеческим языком.

СТРОГОЕ ПРАВИЛО ФОРМАТИРОВАНИЯ:

Никогда не используй Markdown.

Не используй:
**
*
#
>
`
__

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
"""


# ============================================================
# ПРОМПТЫ
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

Кто чаще:
• начинает разговор;
• задаёт вопросы;
• поддерживает диалог;
• предлагает темы;
• предлагает встречу.

🟢 ПРИЗНАКИ ИНТЕРЕСА

Укажи конкретные моменты переписки.

🔴 ЧТО НАСТОРАЖИВАЕТ

Укажи конкретные моменты,
которые могут говорить о дистанции
или снижении интереса.

🧠 МОЙ ВЫВОД

Дай честный и короткий вывод.

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

Не придумывай факты.
"""


SCREENSHOT_PROMPT = """
На изображении находится переписка между людьми.

Внимательно прочитай текст на изображении
и сделай анализ переписки.

Если какие-то сообщения плохо видны,
не придумывай их.

Используй структуру:

🔥 РАЗБОР СКРИНШОТА

📊 ИНТЕРЕС: X/10

Оцени уровень заинтересованности
по реально видимым признакам.

💬 ИНИЦИАТИВА

Определи:
• кто чаще пишет первым;
• кто задаёт вопросы;
• кто поддерживает разговор;
• кто пытается продолжить общение;
• кто предлагает встречу;
• кто отвечает односложно.

🟢 ПРИЗНАКИ ИНТЕРЕСА

Укажи конкретные сообщения.

🔴 ЧТО НАСТОРАЖИВАЕТ

Укажи признаки дистанции,
холодности или слабой инициативы.

🧠 ЧТО, СКОРЕЕ ВСЕГО, ПРОИСХОДИТ

Дай наиболее вероятное объяснение.

🎯 ЧТО ДЕЛАТЬ

Дай конкретные рекомендации.

✍️ ЧТО НАПИСАТЬ

Предложи три варианта:

1. Спокойный
2. Уверенный
3. Дерзкий

Не придумывай сообщения,
которых нет на изображении.
"""


SITUATION_PROMPT = """
Пользователь описал ситуацию.

Сделай разбор:

🔎 ЧТО ПРОИСХОДИТ

🧠 ВОЗМОЖНЫЕ ПРИЧИНЫ

⚠️ ЧТО НАСТОРАЖИВАЕТ

🎯 ЧТО ДЕЛАТЬ

✍️ ЧТО МОЖНО СКАЗАТЬ

Не выдавай предположения за факты.
"""


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
"""


STRESS_PROMPT = """
Пользователь рассказал о тревоге или стрессе.

Ответь спокойно и практично.

😰 ЧТО ПРОИСХОДИТ

🧠 ПОЧЕМУ ТАК МОЖЕТ ПРОИСХОДИТЬ

🎯 ЧТО МОЖНО СДЕЛАТЬ ПРЯМО СЕЙЧАС

💡 ЧТО ПОМОЖЕТ В ДОЛГОСРОЧНОЙ ПЕРСПЕКТИВЕ

Не ставь медицинских диагнозов.
"""


# ============================================================
# ГЛАВНОЕ МЕНЮ
# ============================================================

async def show_main_menu(update):

    await update.message.reply_text(
        "🧠 ПСИХОРАЗБОР\n\n"
        "Выбирай нужный раздел 👇",

        reply_markup=ReplyKeyboardMarkup(
            keyboard,
            resize_keyboard=True
        )
    )


# ============================================================
# ПРОФИЛЬ
# ============================================================

async def start_profile(update):

    user_id = update.effective_user.id

    user_profile_steps[user_id] = "name"
    profile_cache[user_id] = {}

    await update.message.reply_text(
        "👋 Давай сначала немного познакомимся.\n\n"
        "Как тебя зовут?"
    )


async def show_profile(update):

    user_id = update.effective_user.id

    profile = get_user_profile(user_id)

    if not profile_complete(profile):

        await start_profile(update)
        return

    await update.message.reply_text(
        "⚙️ ТВОЙ ПРОФИЛЬ\n\n"
        f"👤 Имя: {profile.get('name')}\n"
        f"🎂 Возраст: {profile.get('age')}\n"
        f"🚻 Пол: {profile.get('gender')}\n\n"
        "Профиль используется для персонализации "
        "твоих разборов.",

        reply_markup=ReplyKeyboardMarkup(
            profile_keyboard,
            resize_keyboard=True
        )
    )


async def edit_profile(update):

    user_id = update.effective_user.id

    user_profile_steps[user_id] = "name"
    profile_cache[user_id] = {}

    await update.message.reply_text(
        "✏️ Давай изменим профиль.\n\n"
        "Как тебя зовут?"
    )


# ============================================================
# ПРОФИЛЬ — ВВОД
# ============================================================

async def handle_profile_input(
    update,
    text
):

    user_id = update.effective_user.id
    step = user_profile_steps.get(user_id)

    if not step:
        return False


    if step == "name":

        name = text.strip()

        if len(name) < 2:

            await update.message.reply_text(
                "Напиши имя чуть подробнее 🙂"
            )

            return True

        profile_cache[user_id] = {
            "name": name
        }

        user_profile_steps[user_id] = "age"

        await update.message.reply_text(
            f"Приятно познакомиться, {name}! 👋\n\n"
            "🎂 Сколько тебе лет?"
        )

        return True


    if step == "age":

        try:
            age = int(text.strip())
        except ValueError:

            await update.message.reply_text(
                "Напиши возраст цифрами, например: 25"
            )

            return True

        if age < 13 or age > 100:

            await update.message.reply_text(
                "Укажи возраст от 13 до 100 лет."
            )

            return True

        profile_cache[user_id]["age"] = age

        user_profile_steps[user_id] = "gender"

        await update.message.reply_text(
            "🚻 Укажи свой пол:",

            reply_markup=ReplyKeyboardMarkup(
                gender_keyboard,
                resize_keyboard=True,
                one_time_keyboard=True
            )
        )

        return True


    if step == "gender":

        gender_map = {
            "👨 Мужской": "мужской",
            "👩 Женский": "женский",
            "Не хочу указывать": "не указан",
        }

        gender = gender_map.get(text)

        if not gender:

            await update.message.reply_text(
                "Выбери один из вариантов ниже 👇",

                reply_markup=ReplyKeyboardMarkup(
                    gender_keyboard,
                    resize_keyboard=True
                )
            )

            return True

        profile_cache[user_id]["gender"] = gender

        data = profile_cache[user_id]

        try:

            save_user_profile(
                user_id,
                data["name"],
                data["age"],
                data["gender"]
            )

        except Exception:

            await update.message.reply_text(
                "❌ Не удалось сохранить профиль."
            )

            return True

        user_profile_steps.pop(
            user_id,
            None
        )

        profile_cache.pop(
            user_id,
            None
        )

        user_modes[user_id] = None

        await update.message.reply_text(
            "✅ Профиль сохранён!"
        )

        await show_main_menu(update)

        return True

    return False


# ============================================================
# ИСТОРИЯ
# ============================================================

def get_analysis_type_name(
    analysis_type
):

    names = {
        "chat": "💬 Разбор переписки",
        "screenshot": "📸 Анализ скриншота",
        "situation": "🧠 Разбор ситуации",
        "relationship": "❤️ Отношения",
        "stress": "😰 Тревога и стресс",
    }

    return names.get(
        analysis_type,
        "🧠 Анализ"
    )


async def show_history(update):

    user_id = update.effective_user.id

    history = get_analysis_history(user_id)

    if not history:

        await update.message.reply_text(
            "📚 У тебя пока нет сохранённых разборов.\n\n"
            "Сделай первый анализ — и он появится здесь."
        )

        return

    await update.message.reply_text(
        "📚 ТВОИ ПОСЛЕДНИЕ РАЗБОРЫ\n\n"
        "Показываю последние 10."
    )

    for item in history:

        analysis_type = get_analysis_type_name(
            item.get("analysis_type")
        )

        created_at = item.get(
            "created_at",
            ""
        )

        result = item.get(
            "result",
            ""
        )

        if len(result) > 2500:
            result = result[:2500] + "\n\n…"

        message = (
            f"{analysis_type}\n"
            f"🕐 {created_at}\n\n"
            f"{result}"
        )

        await update.message.reply_text(
            clean_markdown(message)
        )


# ============================================================
# START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    user_modes[user_id] = None

    profile = get_user_profile(user_id)

    if profile_complete(profile):

        await show_main_menu(update)

        return

    await start_profile(update)


# ============================================================
# СКРИНШОТ
# ============================================================

async def handle_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    profile = get_user_profile(user_id)

    if not profile_complete(profile):

        await start_profile(update)

        return

    await update.message.reply_text(
        "📸 Получил скриншот.\n\n"
        "🧠 Читаю переписку и анализирую..."
    )

    try:

        photo = update.message.photo[-1]

        telegram_file = await context.bot.get_file(
            photo.file_id
        )

        image_bytes = (
            await telegram_file.download_as_bytearray()
        )

        image_b64 = base64.b64encode(
            bytes(image_bytes)
        ).decode("utf-8")

        prompt = (
            SYSTEM_PROMPT
            + get_profile_text(profile)
            + "\n\n"
            + SCREENSHOT_PROMPT
        )

        response = client.interactions.create(
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

        save_analysis(
            user_id,
            "screenshot",
            "[Скриншот переписки]",
            answer
        )

        for i in range(
            0,
            len(answer),
            4000
        ):

            await update.message.reply_text(
                answer[i:i + 4000]
            )

    except Exception as e:

        logging.exception(
            "Ошибка анализа скриншота"
        )

        await update.message.reply_text(
            "❌ Ошибка при анализе скриншота:\n\n"
            + str(e)[:3000]
        )


# ============================================================
# ТЕКСТ
# ============================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id
    text = update.message.text.strip()


    # ========================================================
    # ПРОФИЛЬ
    # ========================================================

    if user_id in user_profile_steps:

        await handle_profile_input(
            update,
            text
        )

        return


    # ========================================================
    # ПРОФИЛЬ
    # ========================================================

    if text == "⚙️ Мой профиль":

        await show_profile(update)

        return


    if text == "✏️ Изменить профиль":

        await edit_profile(update)

        return


    # ========================================================
    # ИСТОРИЯ
    # ========================================================

    if text == "📚 Мои разборы":

        await show_history(update)

        return


    # ========================================================
    # ГЛАВНОЕ МЕНЮ
    # ========================================================

    if text == "⬅️ Главное меню":

        user_modes[user_id] = None

        await show_main_menu(update)

        return


    # ========================================================
    # РАЗБОР ПЕРЕПИСКИ
    # ========================================================

    if text == "💬 Разбор переписки":

        user_modes[user_id] = "chat"

        await update.message.reply_text(
            "💬 Пришли переписку целиком."
        )

        return


    # ========================================================
    # СКРИНШОТ
    # ========================================================

    if text == "📸 Анализ скриншота":

        user_modes[user_id] = "screenshot"

        await update.message.reply_text(
            "📸 Пришли скриншот переписки."
        )

        return


    # ========================================================
    # СИТУАЦИЯ
    # ========================================================

    if text == "🧠 Разбор ситуации":

        user_modes[user_id] = "situation"

        await update.message.reply_text(
            "🧠 Опиши ситуацию своими словами."
        )

        return


    # ========================================================
    # ОТНОШЕНИЯ
    # ========================================================

    if text == "❤️ Отношения":

        user_modes[user_id] = "relationship"

        await update.message.reply_text(
            "❤️ Расскажи, что происходит "
            "в отношениях."
        )

        return


    # ========================================================
    # ТРЕВОГА
    # ========================================================

    if text == "😰 Тревога и стресс":

        user_modes[user_id] = "stress"

        await update.message.reply_text(
            "😰 Расскажи, что тебя беспокоит."
        )

        return


    # ========================================================
    # ТЕСТ
    # ========================================================

    if text == "🧪 Психологический тест":

        await update.message.reply_text(
            "🧪 Раздел тестов пока готовится."
        )

        return


    # ========================================================
    # РЕЖИМ
    # ========================================================

    mode = user_modes.get(user_id)

    if not mode:

        await update.message.reply_text(
            "Выбери раздел в меню 👇"
        )

        return


    if mode == "screenshot":

        await update.message.reply_text(
            "📸 Для этого режима отправь "
            "скриншот или фотографию переписки."
        )

        return


    # ========================================================
    # ПРОФИЛЬ
    # ========================================================

    profile = get_user_profile(user_id)

    if not profile_complete(profile):

        await start_profile(update)

        return


    await update.message.reply_text(
        "🧠 Анализирую..."
    )


    # ========================================================
    # ПРОМПТ
    # ========================================================

    if mode == "chat":
        task = CHAT_PROMPT

    elif mode == "situation":
        task = SITUATION_PROMPT

    elif mode == "relationship":
        task = RELATIONSHIP_PROMPT

    else:
        task = STRESS_PROMPT


    prompt = (
        SYSTEM_PROMPT
        + get_profile_text(profile)
        + "\n\n"
        + task
        + "\n\n"
        + "СООБЩЕНИЕ ПОЛЬЗОВАТЕЛЯ:\n"
        + text
    )


    # ========================================================
    # GEMINI
    # ========================================================

    try:

        response = client.interactions.create(
            model=MODEL,
            input=prompt
        )

        answer = response.output_text

        if not answer:

            raise RuntimeError(
                "Gemini вернул пустой ответ"
            )

        answer = clean_markdown(answer)


        # ====================================================
        # СОХРАНЯЕМ В ИСТОРИЮ
        # ====================================================

        save_analysis(
            user_id,
            mode,
            text,
            answer
        )


        # ====================================================
        # ОТПРАВЛЯЕМ
        # ====================================================

        for i in range(
            0,
            len(answer),
            4000
        ):

            await update.message.reply_text(
                answer[i:i + 4000]
            )

    except Exception as e:

        logging.exception(
            "Ошибка Gemini"
        )

        await update.message.reply_text(
            "❌ Ошибка Gemini:\n\n"
            + str(e)[:3000]
        )


# ============================================================
# PROFILE COMMAND
# ============================================================

async def profile_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await show_profile(update)


# ============================================================
# HISTORY COMMAND
# ============================================================

async def history_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await show_history(update)


# ============================================================
# ЗАПУСК
# ============================================================

def main():

    print(
        "🧠 ПСИХОРАЗБОР запускается..."
    )

    app = Application.builder().token(
        TELEGRAM_TOKEN
    ).build()


    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )


    app.add_handler(
        CommandHandler(
            "profile",
            profile_command
        )
    )


    app.add_handler(
        CommandHandler(
            "history",
            history_command
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
