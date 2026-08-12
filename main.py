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

if not SUPABASE_SECRET_KEY:
    raise RuntimeError(
        "SUPABASE_SECRET_KEY не задан в Railway"
    )


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
]


gender_keyboard = [
    ["👨 Мужской", "👩 Женский"],
    ["Не хочу указывать"],
]


# ============================================================
# ВРЕМЕННЫЕ ДАННЫЕ
# ============================================================

# Текущий режим пользователя
user_modes = {}

# Этап заполнения профиля
user_profile_steps = {}


# ============================================================
# РАБОТА С SUPABASE
# ============================================================

def get_user_profile(user_id):
    """
    Получает профиль пользователя из Supabase.
    """

    try:
        result = (
            supabase
            .table("users")
            .select("telegram_id, name, age, gender")
            .eq("telegram_id", user_id)
            .maybe_single()
            .execute()
        )

        if result.data:
            return result.data

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
    """
    Создаёт или обновляет профиль пользователя.
    """

    try:

        data = {
            "telegram_id": user_id,
            "name": name,
            "age": age,
            "gender": gender
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
            "Профиль пользователя %s сохранён",
            user_id
        )

        return result.data

    except Exception:

        logging.exception(
            "Ошибка сохранения профиля %s",
            user_id
        )

        raise


def profile_complete(profile):
    """
    Проверяет, заполнен ли профиль.
    """

    if not profile:
        return False

    return (
        bool(profile.get("name"))
        and bool(profile.get("age"))
        and bool(profile.get("gender"))
    )


# ============================================================
# ОЧИСТКА MARKDOWN
# ============================================================

def clean_markdown(text):

    if not text:
        return text

    # Жирный текст
    text = re.sub(
        r"\*\*(.*?)\*\*",
        r"\1",
        text
    )

    # Курсив
    text = re.sub(
        r"(?<!\*)\*(?!\s)(.*?)(?<!\s)\*(?!\*)",
        r"\1",
        text
    )

    # Подчёркивание
    text = re.sub(
        r"__(.*?)__",
        r"\1",
        text
    )

    # Markdown-заголовки
    text = re.sub(
        r"(?m)^\s*#{1,6}\s*",
        "",
        text
    )

    # Цитаты
    text = re.sub(
        r"(?m)^\s*>\s?",
        "",
        text
    )

    # Обратные кавычки
    text = text.replace("```", "")
    text = text.replace("`", "")

    # Лишние пробелы
    text = re.sub(
        r"[ \t]+\n",
        "\n",
        text
    )

    # Не больше двух пустых строк
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

    name = profile.get("name", "")
    age = profile.get("age", "")
    gender = profile.get("gender", "")

    return (
        "\n\n"
        "ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ:\n"
        f"Имя: {name}\n"
        f"Возраст: {age}\n"
        f"Пол: {gender}\n\n"
        "Учитывай профиль пользователя при анализе. "
        "Не делай выводы только на основании пола или возраста. "
        "Основывай выводы прежде всего на содержании "
        "переписки и описанной ситуации.\n"
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

Для нумерованных вариантов используй:

1. вариант
2. вариант
3. вариант

Эмодзи использовать можно.

Текст должен выглядеть естественно
в сообщении Telegram.

Главная цель — дать человеку практическую пользу.
"""


# ============================================================
# РАЗБОР ПЕРЕПИСКИ
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


# ============================================================
# РАЗБОР СКРИНШОТА
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

Укажи конкретные сообщения
или особенности переписки,
которые могут говорить об интересе.

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

Не придумывай сообщения,
которых нет на изображении.

Если изображение слишком маленькое,
обрезано или плохо читается,
честно сообщи об этом.
"""


# ============================================================
# РАЗБОР СИТУАЦИИ
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
# ОТНОШЕНИЯ
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
# ТРЕВОГА И СТРЕСС
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
# ГЛАВНОЕ МЕНЮ
# ============================================================

async def show_main_menu(update):

    await update.message.reply_text(
        "🧠 ПСИХОРАЗБОР\n\n"
        "Разберём переписку, скриншот, "
        "отношения или ситуацию.\n\n"
        "Выбирай 👇",

        reply_markup=ReplyKeyboardMarkup(
            keyboard,
            resize_keyboard=True
        )
    )


# ============================================================
# НАЧАЛО ПРОФИЛЯ
# ============================================================

async def start_profile(update):

    user_id = update.effective_user.id

    user_profile_steps[user_id] = "name"

    await update.message.reply_text(
        "👋 Привет!\n\n"
        "Давай сначала немного познакомимся.\n\n"
        "Как тебя зовут?"
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

    # Загружаем профиль из Supabase
    profile = get_user_profile(user_id)

    if not profile_complete(profile):

        await start_profile(update)

        return

    await show_main_menu(update)


# ============================================================
# ИЗМЕНЕНИЕ ПРОФИЛЯ
# ============================================================

async def edit_profile(update):

    user_id = update.effective_user.id

    user_profile_steps[user_id] = "name"

    await update.message.reply_text(
        "⚙️ Давай обновим профиль.\n\n"
        "Как тебя зовут?"
    )


# ============================================================
# ОБРАБОТКА ПРОФИЛЯ
# ============================================================

async def handle_profile_input(
    update: Update,
    text: str
):

    user_id = update.effective_user.id

    step = user_profile_steps.get(user_id)

    if not step:
        return False


    # ========================================================
    # ИМЯ
    # ========================================================

    if step == "name":

        name = text.strip()

        if len(name) < 2:

            await update.message.reply_text(
                "Напиши имя чуть подробнее 🙂"
            )

            return True

        if len(name) > 40:

            await update.message.reply_text(
                "Имя слишком длинное. "
                "Напиши, пожалуйста, короче."
            )

            return True


        # Создаём/обновляем временный профиль
        old_profile = get_user_profile(user_id)

        if old_profile:
            current_age = old_profile.get("age")
            current_gender = old_profile.get("gender")
        else:
            current_age = None
            current_gender = None


        # Пока сохраняем только имя
        # Остальные данные сохраним после заполнения
        if user_id not in user_profile_steps:
            user_profile_steps[user_id] = "name"

        user_profile_steps[user_id] = "age"

        # Сохраняем имя временно в контексте
        update_profile_cache = context_user_cache.get(user_id, {})
        update_profile_cache["name"] = name
        update_profile_cache["age"] = current_age
        update_profile_cache["gender"] = current_gender
        context_user_cache[user_id] = update_profile_cache


        await update.message.reply_text(
            f"Приятно познакомиться, {name}! 👋\n\n"
            "🎂 Сколько тебе лет?"
        )

        return True


    # ========================================================
    # ВОЗРАСТ
    # ========================================================

    if step == "age":

        age_text = text.strip()

        try:
            age = int(age_text)

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


        profile_data = context_user_cache.get(
            user_id,
            {}
        )

        profile_data["age"] = age

        context_user_cache[user_id] = profile_data

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


    # ========================================================
    # ПОЛ
    # ========================================================

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
                    resize_keyboard=True,
                    one_time_keyboard=True
                )
            )

            return True


        profile_data = context_user_cache.get(
            user_id,
            {}
        )

        profile_data["gender"] = gender

        name = profile_data.get(
            "name",
            ""
        )

        age = profile_data.get(
            "age"
        )


        # Сохраняем ВСЁ в Supabase
        try:

            save_user_profile(
                user_id=user_id,
                name=name,
                age=age,
                gender=gender
            )

        except Exception:

            await update.message.reply_text(
                "❌ Не удалось сохранить профиль.\n\n"
                "Попробуй ещё раз через несколько секунд."
            )

            return True


        user_profile_steps.pop(
            user_id,
            None
        )

        context_user_cache.pop(
            user_id,
            None
        )

        user_modes[user_id] = None


        await update.message.reply_text(
            "✅ Профиль сохранён!\n\n"
            "Теперь он будет храниться в базе, "
            "поэтому после перезапуска бота "
            "вводить данные заново не понадобится."
        )


        await show_main_menu(update)

        return True


    return False


# ============================================================
# ВРЕМЕННЫЙ КЭШ ПРОФИЛЯ
# ============================================================

context_user_cache = {}


# ============================================================
# АНАЛИЗ СКРИНШОТА
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


    logging.info(
        "Получен скриншот от пользователя %s",
        user_id
    )


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


        profile_text = get_profile_text(
            profile
        )


        prompt = (
            SYSTEM_PROMPT
            + profile_text
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


        answer = clean_markdown(
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
# ОБРАБОТКА ТЕКСТА
# ============================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    text = update.message.text.strip()


    # ========================================================
    # ПРОВЕРЯЕМ ПРОФИЛЬ
    # ========================================================

    if user_id in user_profile_steps:

        await handle_profile_input(
            update,
            text
        )

        return


    # ========================================================
    # МОЙ ПРОФИЛЬ
    # ========================================================

    if text == "⚙️ Мой профиль":

        await edit_profile(update)

        return


    # ========================================================
    # РАЗБОР ПЕРЕПИСКИ
    # ========================================================

    if text == "💬 Разбор переписки":

        user_modes[user_id] = "chat"

        await update.message.reply_text(
            "💬 Пришли переписку целиком.\n\n"
            "Можно просто скопировать сообщения "
            "и отправить их сюда."
        )

        return


    # ========================================================
    # АНАЛИЗ СКРИНШОТА
    # ========================================================

    if text == "📸 Анализ скриншота":

        user_modes[user_id] = "screenshot"

        await update.message.reply_text(
            "📸 Пришли скриншот переписки.\n\n"
            "Я прочитаю сообщения и попробую определить:\n\n"
            "📊 интерес\n"
            "💬 инициативу\n"
            "🟢 признаки интереса\n"
            "🔴 тревожные моменты\n"
            "🎯 что делать\n"
            "✍️ что написать"
        )

        return


    # ========================================================
    # РАЗБОР СИТУАЦИИ
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
            "😰 Расскажи, что тебя сейчас беспокоит."
        )

        return


    # ========================================================
    # ТЕСТЫ
    # ========================================================

    if text == "🧪 Психологический тест":

        await update.message.reply_text(
            "🧪 Раздел тестов пока готовится.\n\n"
            "Следующим обновлением добавим "
            "полноценные тесты с результатами."
        )

        return


    # ========================================================
    # ПРОВЕРЯЕМ РЕЖИМ
    # ========================================================

    mode = user_modes.get(
        user_id
    )


    if not mode:

        await update.message.reply_text(
            "Выбери раздел в меню 👇"
        )

        return


    # ========================================================
    # ЕСЛИ РЕЖИМ СКРИНШОТА
    # ========================================================

    if mode == "screenshot":

        await update.message.reply_text(
            "📸 Для этого режима отправь именно "
            "скриншот или фотографию переписки."
        )

        return


    # ========================================================
    # ПОЛУЧАЕМ ПРОФИЛЬ
    # ========================================================

    profile = get_user_profile(
        user_id
    )


    # ========================================================
    # СООБЩЕНИЕ
    # ========================================================

    await update.message.reply_text(
        "🧠 Анализирую..."
    )


    # ========================================================
    # ВЫБИРАЕМ ПРОМПТ
    # ========================================================

    if mode == "chat":

        task = CHAT_PROMPT

    elif mode == "situation":

        task = SITUATION_PROMPT

    elif mode == "relationship":

        task = RELATIONSHIP_PROMPT

    else:

        task = STRESS_PROMPT


    # ========================================================
    # ПРОФИЛЬ
    # ========================================================

    profile_text = get_profile_text(
        profile
    )


    # ========================================================
    # ФИНАЛЬНЫЙ PROMPT
    # ========================================================

    prompt = (
        SYSTEM_PROMPT
        + profile_text
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


        answer = clean_markdown(
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
            "Ошибка Gemini"
        )


        await update.message.reply_text(
            "❌ Ошибка Gemini:\n\n"
            + str(e)[:3000]
        )


# ============================================================
# КОМАНДА /PROFILE
# ============================================================

async def profile_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    profile = get_user_profile(
        user_id
    )


    if not profile:

        await start_profile(update)

        return


    name = profile.get(
        "name",
        "не указано"
    )

    age = profile.get(
        "age",
        "не указано"
    )

    gender = profile.get(
        "gender",
        "не указан"
    )


    await update.message.reply_text(
        "⚙️ ТВОЙ ПРОФИЛЬ\n\n"
        f"👤 Имя: {name}\n"
        f"🎂 Возраст: {age}\n"
        f"🚻 Пол: {gender}\n\n"
        "Чтобы изменить данные, нажми "
        "«⚙️ Мой профиль»."
    )


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


    # /start
    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )


    # /profile
    app.add_handler(
        CommandHandler(
            "profile",
            profile_command
        )
    )


    # Фотографии
    app.add_handler(
        MessageHandler(
            filters.PHOTO,
            handle_photo
        )
    )


    # Текст
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


# ============================================================
# START PROGRAM
# ============================================================

if __name__ == "__main__":
    main()
