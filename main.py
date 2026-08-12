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
# CLIENTS
# ============================================================

client = genai.Client(
    api_key=GEMINI_API_KEY
)


supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)


MODEL = "gemini-3.6-flash"


# ============================================================
# МЕНЮ
# ============================================================

keyboard = [
    ["💬 Разбор переписки"],
    ["📸 Анализ скриншота"],
    ["🧠 Разбор ситуации"],
    ["❤️ Отношения", "😰 Тревога и стресс"],
    ["🧪 Психологический тест"],
    ["👤 Мой профиль", "📚 Мои разборы"],
]


# ============================================================
# СОСТОЯНИЯ ПОЛЬЗОВАТЕЛЕЙ
# ============================================================

user_modes = {}

profile_states = {}


# ============================================================
# КЛАВИАТУРА
# ============================================================

def main_keyboard():

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True
    )


# ============================================================
# ОТПРАВКА ДЛИННОГО СООБЩЕНИЯ
# ============================================================

async def send_long_message(
    update: Update,
    text: str
):

    if not text:
        return

    for i in range(
        0,
        len(text),
        4000
    ):

        await update.message.reply_text(
            text[i:i + 4000]
        )


# ============================================================
# ОЧИСТКА MARKDOWN
# ============================================================

def clean_markdown(text):

    if not text:
        return text

    # Жирный
    text = re.sub(
        r"\*\*(.*?)\*\*",
        r"\1",
        text,
        flags=re.DOTALL
    )

    # Курсив
    text = re.sub(
        r"(?<!\*)\*(?!\s)(.*?)(?<!\s)\*(?!\*)",
        r"\1",
        text,
        flags=re.DOTALL
    )

    # Подчёркивание
    text = re.sub(
        r"__(.*?)__",
        r"\1",
        text,
        flags=re.DOTALL
    )

    # Заголовки
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

    # Код
    text = text.replace(
        "```",
        ""
    )

    text = text.replace(
        "`",
        ""
    )

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
# ПОЛУЧЕНИЕ ПРОФИЛЯ
# ============================================================

def get_user_profile(user_id):

    try:

        response = (
            supabase
            .table("users")
            .select("*")
            .eq("telegram_id", user_id)
            .limit(1)
            .execute()
        )

        data = response.data or []

        if not data:
            return None

        return data[0]

    except Exception:

        logging.exception(
            "Ошибка получения профиля"
        )

        return None


# ============================================================
# СОХРАНЕНИЕ ПРОФИЛЯ
# ============================================================

def save_user_profile(
    user_id,
    name,
    age,
    gender
):

    try:

        existing = (
            supabase
            .table("users")
            .select("id")
            .eq("telegram_id", user_id)
            .limit(1)
            .execute()
        )

        data = existing.data or []

        profile_data = {
            "telegram_id": user_id,
            "name": name,
            "age": age,
            "gender": gender,
        }

        if data:

            result = (
                supabase
                .table("users")
                .update(profile_data)
                .eq("telegram_id", user_id)
                .execute()
            )

        else:

            result = (
                supabase
                .table("users")
                .insert(profile_data)
                .execute()
            )

        return bool(result.data)

    except Exception:

        logging.exception(
            "Ошибка сохранения профиля"
        )

        return False


# ============================================================
# ПРОВЕРКА ПРОФИЛЯ
# ============================================================

def profile_exists(user_id):

    profile = get_user_profile(
        user_id
    )

    if not profile:
        return False

    name = profile.get("name")
    age = profile.get("age")
    gender = profile.get("gender")

    return bool(
        name
        and age
        and gender
    )


# ============================================================
# ФОРМИРОВАНИЕ ПРОФИЛЯ ДЛЯ GEMINI
# ============================================================

def profile_context(user_id):

    profile = get_user_profile(
        user_id
    )

    if not profile:
        return ""

    name = profile.get(
        "name",
        ""
    )

    age = profile.get(
        "age",
        ""
    )

    gender = profile.get(
        "gender",
        ""
    )

    return (
        "\n\n"
        "ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ:\n"
        f"Имя: {name}\n"
        f"Возраст: {age}\n"
        f"Пол: {gender}\n\n"
        "Учитывай эти данные при формировании ответа. "
        "Обращайся к пользователю по имени естественно, "
        "но не вставляй имя в каждое сообщение."
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

НЕ используй:

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

Варианты должны быть естественными
для обычной переписки в Telegram.

Не придумывай факты.
"""


# ============================================================
# АНАЛИЗ СКРИНШОТА
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
# СОХРАНЕНИЕ АНАЛИЗА
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
            "user_message": user_message,
            "result": result,
        }

        response = (
            supabase
            .table("analyses")
            .insert(data)
            .execute()
        )

        logging.info(
            "Анализ сохранён: user=%s type=%s",
            user_id,
            analysis_type
        )

        return bool(response.data)

    except Exception:

        logging.exception(
            "Ошибка сохранения анализа"
        )

        return False


# ============================================================
# START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    user_modes[user_id] = None

    profile_states.pop(
        user_id,
        None
    )

    if not profile_exists(user_id):

        await update.message.reply_text(
            "🧠 ПСИХОРАЗБОР\n\n"
            "Давай сначала создадим твой профиль.\n\n"
            "Как тебя зовут?"
        )

        profile_states[user_id] = {
            "step": "name"
        }

        return

    await update.message.reply_text(
        "🧠 ПСИХОРАЗБОР\n\n"
        "С возвращением!\n\n"
        "Выбирай, что хочешь разобрать 👇",
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

    state = profile_states.get(
        user_id
    )

    if not state:
        return False

    text = update.message.text.strip()

    step = state.get(
        "step"
    )


    # ========================================================
    # ИМЯ
    # ========================================================

    if step == "name":

        if len(text) < 2:

            await update.message.reply_text(
                "Напиши имя немного подробнее 🙂"
            )

            return True

        state["name"] = text

        state["step"] = "age"

        await update.message.reply_text(
            "Отлично 👍\n\n"
            "Сколько тебе лет?"
        )

        return True


    # ========================================================
    # ВОЗРАСТ
    # ========================================================

    if step == "age":

        if not text.isdigit():

            await update.message.reply_text(
                "Напиши возраст цифрами.\n\n"
                "Например: 25"
            )

            return True

        age = int(text)

        if age < 13 or age > 100:

            await update.message.reply_text(
                "Укажи реальный возраст от 13 до 100 лет."
            )

            return True

        state["age"] = age

        state["step"] = "gender"

        gender_keyboard = [
            ["👨 Мужчина", "👩 Женщина"],
            ["◀️ Назад"],
        ]

        await update.message.reply_text(
            "И последний вопрос.\n\n"
            "Укажи свой пол:",
            reply_markup=ReplyKeyboardMarkup(
                gender_keyboard,
                resize_keyboard=True
            )
        )

        return True


    # ========================================================
    # ПОЛ
    # ========================================================

    if step == "gender":

        if text == "👨 Мужчина":

            gender = "мужчина"

        elif text == "👩 Женщина":

            gender = "женщина"

        elif text == "◀️ Назад":

            state["step"] = "age"

            await update.message.reply_text(
                "Сколько тебе лет?"
            )

            return True

        else:

            await update.message.reply_text(
                "Выбери вариант кнопкой 👇"
            )

            return True

        state["gender"] = gender

        success = save_user_profile(
            user_id=user_id,
            name=state["name"],
            age=state["age"],
            gender=state["gender"]
        )

        if not success:

            await update.message.reply_text(
                "❌ Не удалось сохранить профиль.\n\n"
                "Попробуй ещё раз."
            )

            return True

        profile_states.pop(
            user_id,
            None
        )

        user_modes[user_id] = None

        await update.message.reply_text(
            "✅ Профиль сохранён!\n\n"
            f"👤 Имя: {state['name']}\n"
            f"🎂 Возраст: {state['age']}\n"
            f"⚧ Пол: {state['gender']}\n\n"
            "Теперь я смогу учитывать эти данные "
            "при анализе твоих ситуаций.",
            reply_markup=main_keyboard()
        )

        return True

    return False


# ============================================================
# МОЙ ПРОФИЛЬ
# ============================================================

async def show_profile(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    profile = get_user_profile(
        user_id
    )

    if not profile:

        await update.message.reply_text(
            "👤 Профиль ещё не создан.\n\n"
            "Давай создадим его."
        )

        profile_states[user_id] = {
            "step": "name"
        }

        return

    name = profile.get(
        "name",
        "—"
    )

    age = profile.get(
        "age",
        "—"
    )

    gender = profile.get(
        "gender",
        "—"
    )

    await update.message.reply_text(
        "👤 МОЙ ПРОФИЛЬ\n\n"
        f"Имя: {name}\n"
        f"Возраст: {age}\n"
        f"Пол: {gender}\n\n"
        "Если хочешь изменить профиль, "
        "нажми кнопку ниже.",
        reply_markup=ReplyKeyboardMarkup(
            [
                ["✏️ Изменить профиль"],
                ["🔙 Главное меню"],
            ],
            resize_keyboard=True
        )
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
            .order(
                "created_at",
                desc=True
            )
            .limit(10)
            .execute()
        )

        analyses = response.data or []

        if not analyses:

            await update.message.reply_text(
                "📚 МОИ РАЗБОРЫ\n\n"
                "У тебя пока нет сохранённых разборов.\n\n"
                "Сделай первый анализ — "
                "и он появится здесь.",
                reply_markup=main_keyboard()
            )

            return

        buttons = []

        for index, item in enumerate(
            analyses,
            start=1
        ):

            analysis_type = item.get(
                "analysis_type",
                "Разбор"
            )

            created_at = item.get(
                "created_at",
                ""
            )

            if "T" in str(created_at):

                date_text = (
                    str(created_at)
                    .split("T")[0]
                )

            else:

                date_text = str(
                    created_at
                )[:10]

            button_text = (
                f"{index}️⃣ "
                f"{analysis_type} — "
                f"{date_text}"
            )

            buttons.append([
                button_text
            ])

        buttons.append([
            "🔙 Главное меню"
        ])

        user_modes[user_id] = {
            "type": "history",
            "analyses": analyses
        }

        await update.message.reply_text(
            "📚 МОИ РАЗБОРЫ\n\n"
            "Последние 10 разборов:\n\n"
            "Выбери нужный разбор 👇",
            reply_markup=ReplyKeyboardMarkup(
                buttons,
                resize_keyboard=True
            )
        )

    except Exception as e:

        logging.exception(
            "Ошибка получения истории"
        )

        await update.message.reply_text(
            "❌ Ошибка при получении разборов:\n\n"
            + str(e)[:2000]
        )


# ============================================================
# ОТКРЫТИЕ СОХРАНЁННОГО РАЗБОРА
# ============================================================

async def open_analysis(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    text = update.message.text.strip()

    history = user_modes.get(
        user_id
    )

    if not isinstance(
        history,
        dict
    ):

        return False

    if history.get("type") != "history":

        return False

    analyses = history.get(
        "analyses",
        []
    )

    selected_index = None

    for index in range(
        1,
        len(analyses) + 1
    ):

        if text.startswith(
            f"{index}️⃣"
        ):

            selected_index = index - 1

            break

    if selected_index is None:

        return False

    try:

        analysis = analyses[
            selected_index
        ]

        analysis_id = analysis.get(
            "id"
        )

        if not analysis_id:

            await update.message.reply_text(
                "❌ Не удалось определить разбор."
            )

            return True

        # ВАЖНАЯ ПРОВЕРКА:
        # открываем только разбор этого пользователя

        response = (
            supabase
            .table("analyses")
            .select("*")
            .eq("id", analysis_id)
            .eq("telegram_id", user_id)
            .limit(1)
            .execute()
        )

        data = response.data or []

        if not data:

            await update.message.reply_text(
                "❌ Разбор не найден.",
                reply_markup=main_keyboard()
            )

            return True

        item = data[0]

        analysis_type = item.get(
            "analysis_type",
            "Разбор"
        )

        user_message = item.get(
            "user_message",
            ""
        )

        result = item.get(
            "result",
            ""
        )

        created_at = item.get(
            "created_at",
            ""
        )

        result = clean_markdown(
            result
        )

        answer = (
            f"📚 {analysis_type}\n\n"
            f"🕐 {created_at}\n\n"
            f"📝 ТВОЁ СООБЩЕНИЕ:\n\n"
            f"{user_message}\n\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"🧠 РЕЗУЛЬТАТ:\n\n"
            f"{result}"
        )

        await send_long_message(
            update,
            answer
        )

        await update.message.reply_text(
            "Что хочешь сделать дальше? 👇",
            reply_markup=main_keyboard()
        )

        return True

    except Exception as e:

        logging.exception(
            "Ошибка открытия анализа"
        )

        await update.message.reply_text(
            "❌ Не удалось открыть разбор:\n\n"
            + str(e)[:2000]
        )

        return True


# ============================================================
# АНАЛИЗ СКРИНШОТА
# ============================================================

async def handle_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    logging.info(
        "Получен скриншот от пользователя %s",
        user_id
    )

    if not profile_exists(user_id):

        await update.message.reply_text(
            "👤 Сначала создай профиль.\n\n"
            "Нажми /start"
        )

        return

    await update.message.reply_text(
        "📸 Получил скриншот.\n\n"
        "🧠 Читаю переписку и анализирую..."
    )

    try:

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
            + profile_context(user_id)
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

        # Сохраняем анализ
        save_analysis(
            user_id=user_id,
            analysis_type="Анализ скриншота",
            user_message="Скриншот переписки",
            result=answer
        )

        await send_long_message(
            update,
            answer
        )

        await update.message.reply_text(
            "📚 Этот разбор сохранён в «Мои разборы».",
            reply_markup=main_keyboard()
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
    # ПРОФИЛЬ
    # ========================================================

    if user_id in profile_states:

        handled = await handle_profile(
            update,
            context
        )

        if handled:
            return


    # ========================================================
    # ОТКРЫТИЕ СОХРАНЁННОГО РАЗБОРА
    # ========================================================

    if await open_analysis(
        update,
        context
    ):

        return


    # ========================================================
    # ГЛАВНОЕ МЕНЮ
    # ========================================================

    if text == "🔙 Главное меню":

        user_modes[user_id] = None

        await update.message.reply_text(
            "🧠 Главное меню\n\n"
            "Выбирай раздел 👇",
            reply_markup=main_keyboard()
        )

        return


    # ========================================================
    # МОЙ ПРОФИЛЬ
    # ========================================================

    if text == "👤 Мой профиль":

        user_modes[user_id] = None

        await show_profile(
            update,
            context
        )

        return


    # ========================================================
    # ИЗМЕНИТЬ ПРОФИЛЬ
    # ========================================================

    if text == "✏️ Изменить профиль":

        user_modes[user_id] = None

        profile_states[user_id] = {
            "step": "name"
        }

        await update.message.reply_text(
            "✏️ Давай изменим твой профиль.\n\n"
            "Как тебя зовут?"
        )

        return


    # ========================================================
    # МОИ РАЗБОРЫ
    # ========================================================

    if text == "📚 Мои разборы":

        await my_analyses(
            update,
            context
        )

        return


    # ========================================================
    # РАЗБОР ПЕРЕПИСКИ
    # ========================================================

    if text == "💬 Разбор переписки":

        if not profile_exists(user_id):

            await update.message.reply_text(
                "👤 Сначала создай профиль.\n\n"
                "Нажми /start"
            )

            return

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

        if not profile_exists(user_id):

            await update.message.reply_text(
                "👤 Сначала создай профиль.\n\n"
                "Нажми /start"
            )

            return

        user_modes[user_id] = "screenshot"

        await update.message.reply_text(
            "📸 Пришли скриншот переписки.\n\n"
            "Я попробую определить:\n\n"
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

        if not profile_exists(user_id):

            await update.message.reply_text(
                "👤 Сначала создай профиль.\n\n"
                "Нажми /start"
            )

            return

        user_modes[user_id] = "situation"

        await update.message.reply_text(
            "🧠 Опиши ситуацию своими словами."
        )

        return


    # ========================================================
    # ОТНОШЕНИЯ
    # ========================================================

    if text == "❤️ Отношения":

        if not profile_exists(user_id):

            await update.message.reply_text(
                "👤 Сначала создай профиль.\n\n"
                "Нажми /start"
            )

            return

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

        if not profile_exists(user_id):

            await update.message.reply_text(
                "👤 Сначала создай профиль.\n\n"
                "Нажми /start"
            )

            return

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
            "полноценные тесты с результатами.",
            reply_markup=main_keyboard()
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
            "Выбери раздел в меню 👇",
            reply_markup=main_keyboard()
        )

        return


    # ========================================================
    # ИСТОРИЯ
    # ========================================================

    if isinstance(
        mode,
        dict
    ):

        if mode.get("type") == "history":

            await update.message.reply_text(
                "📚 Выбери разбор кнопкой выше 👆"
            )

            return


    # ========================================================
    # РЕЖИМ СКРИНШОТА
    # ========================================================

    if mode == "screenshot":

        await update.message.reply_text(
            "📸 Для этого режима отправь именно "
            "скриншот или фотографию переписки."
        )

        return


    # ========================================================
    # НАЧАЛО АНАЛИЗА
    # ========================================================

    await update.message.reply_text(
        "🧠 Анализирую..."
    )


    # ========================================================
    # ВЫБИРАЕМ PROMPT
    # ========================================================

    if mode == "chat":

        task = CHAT_PROMPT

        analysis_type = (
            "Разбор переписки"
        )

    elif mode == "situation":

        task = SITUATION_PROMPT

        analysis_type = (
            "Разбор ситуации"
        )

    elif mode == "relationship":

        task = RELATIONSHIP_PROMPT

        analysis_type = (
            "Отношения"
        )

    else:

        task = STRESS_PROMPT

        analysis_type = (
            "Тревога и стресс"
        )


    # ========================================================
    # ФИНАЛЬНЫЙ PROMPT
    # ========================================================

    prompt = (
        SYSTEM_PROMPT
        + profile_context(user_id)
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


        # ====================================================
        # СОХРАНЯЕМ РАЗБОР
        # ====================================================

        save_analysis(
            user_id=user_id,
            analysis_type=analysis_type,
            user_message=text,
            result=answer
        )


        # ====================================================
        # ОТПРАВЛЯЕМ ОТВЕТ
        # ====================================================

        await send_long_message(
            update,
            answer
        )


        await update.message.reply_text(
            "📚 Разбор сохранён.\n\n"
            "Посмотреть его можно в разделе "
            "«📚 Мои разборы».",
            reply_markup=main_keyboard()
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


    # /start

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )


    # Фото

    app.add_handler(
        MessageHandler(
            filters.PHOTO,
            handle_photo
        )
    )


    # Текст

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            handle_message
        )
    )


    print(
        "🟢 ПСИХОРАЗБОР успешно запущен."
    )

    app.run_polling()


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    main()
