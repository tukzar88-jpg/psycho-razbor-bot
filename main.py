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
# СОСТОЯНИЯ
# ============================================================

user_modes = {}
profile_states = {}
test_states = {}

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

    text = text.replace(
        "```",
        ""
    )

    text = text.replace(
        "`",
        ""
    )

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
# КОНТЕКСТ ПРОФИЛЯ
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

Сделай короткий, но точный разбор всей динамики общения.

🔥 РАЗБОР ПЕРЕПИСКИ

📊 ИНТЕРЕС: X/10

Оцени заинтересованность только по реальным
признакам из переписки.

Учитывай:

• кто чаще начинает разговор;
• кто поддерживает диалог;
• кто задаёт вопросы;
• кто проявляет инициативу;
• кто предлагает встречу;
• насколько эмоциональны ответы;
• есть ли флирт;
• есть ли взаимность;
• меняется ли уровень интереса со временем.

Не оценивай интерес по одному сообщению.

🟢 ПРИЗНАКИ ИНТЕРЕСА

Назови 2–4 конкретных признака из переписки.

🔴 ЧТО НАСТОРАЖИВАЕТ

Назови 2–4 конкретных момента,
которые могут говорить о дистанции,
снижении интереса или отсутствии взаимности.

🟡 НЕОДНОЗНАЧНЫЕ МОМЕНТЫ

Укажи моменты, которые можно трактовать
по-разному.

🧠 МОЙ ВЫВОД

Коротко объясни, что, скорее всего,
происходит между людьми.

Не говори:
"она точно тебя любит"
или:
"она точно тебя не любит".

🎯 ЧТО ДЕЛАТЬ

Дай 3 конкретных действия.

🚫 ЧЕГО НЕ ДЕЛАТЬ

Дай 2–3 конкретных предупреждения.

✍️ ЧТО НАПИСАТЬ

Предложи три коротких варианта:

1. Спокойный
2. Уверенный
3. Дерзкий

Сообщения должны соответствовать
реальной ситуации и не выглядеть искусственно.

Не придумывай факты.
Не растягивай ответ.
"""

# ============================================================
# АНАЛИЗ СКРИНШОТА
# ============================================================

SCREENSHOT_PROMPT = """
На изображении находится переписка между людьми.

Внимательно прочитай текст на изображении.

Если какие-то сообщения плохо видны,
не придумывай их.

Сделай короткий и конкретный анализ.

🔥 РАЗБОР СКРИНШОТА

📊 ИНТЕРЕС: X/10

Оцени интерес по всей видимой переписке.

💬 ИНИЦИАТИВА

Определи:

• кто чаще пишет первым;
• кто задаёт вопросы;
• кто поддерживает разговор;
• кто пытается продолжить общение;
• кто предлагает встречу;
• кто отвечает односложно.

🟢 ПРИЗНАКИ ИНТЕРЕСА

2–4 конкретных момента.

🔴 ЧТО НАСТОРАЖИВАЕТ

2–4 конкретных момента.

🟡 НЕОДНОЗНАЧНЫЕ МОМЕНТЫ

Что нельзя уверенно интерпретировать
только по этой переписке.

🧠 ЧТО, СКОРЕЕ ВСЕГО, ПРОИСХОДИТ

Дай наиболее вероятное объяснение.

🎯 ЧТО ДЕЛАТЬ

3 конкретных действия.

✍️ ЧТО НАПИСАТЬ

Предложи:

1. Спокойный вариант
2. Уверенный вариант
3. Дерзкий вариант

Не придумывай сообщения,
которых нет на изображении.

Если изображение слишком маленькое,
обрезано или плохо читается,
честно сообщи об этом.

Не растягивай ответ.
"""

# ============================================================
# РАЗБОР СИТУАЦИИ
# ============================================================

SITUATION_PROMPT = """
Пользователь описал личную ситуацию.

Сделай короткий, умный и конкретный разбор.

Не ставь диагнозов.
Не выдавай предположения за факты.
Не придумывай информацию, которой нет в сообщении.

Используй структуру:

🔎 ЧТО ПРОИСХОДИТ

1–3 предложения о сути ситуации.

🧠 ПОЧЕМУ ТАК МОЖЕТ БЫТЬ

Назови 2–3 наиболее вероятные причины.
Отделяй факты от предположений.

⚠️ НА ЧТО ОБРАТИТЬ ВНИМАНИЕ

2–4 конкретных момента из ситуации.

🎯 ЧТО ДЕЛАТЬ

Дай 3 конкретных действия прямо сейчас.

🚫 ЧЕГО НЕ ДЕЛАТЬ

1–3 действия, которые могут ухудшить ситуацию.

✍️ ЧТО СКАЗАТЬ

Если нужен разговор или сообщение —
дай один лучший вариант текста.

⭐ МОЙ ВЫВОД

2–3 предложения с максимально честным выводом.

ВАЖНО:

• Не занимай автоматически сторону пользователя.
• Если пользователь неправ — спокойно скажи об этом.
• Если другой человек неправ — тоже скажи.
• Не используй сложный психологический жаргон.
• Не повторяй слова пользователя большими абзацами.
• Не растягивай ответ.
• Каждый раздел должен быть коротким.
• Общий ответ желательно держать в пределах 500–700 слов.
• Если ситуацию можно объяснить проще — объясняй проще.
• Главное — практическая польза.
"""

# ============================================================
# ОТНОШЕНИЯ
# ============================================================

RELATIONSHIP_PROMPT = """
Пользователь рассказал о проблеме в отношениях.

Сделай короткий и конкретный разбор.

❤️ ЧТО ПРОИСХОДИТ

Кратко объясни суть проблемы.

🔎 ВОЗМОЖНЫЕ ПРИЧИНЫ

Назови 2–3 наиболее вероятных объяснения.

⚠️ ПРОБЛЕМНЫЕ МОМЕНТЫ

Укажи конкретные признаки,
на которые стоит обратить внимание.

🧠 ЧТО МОЖЕТ ПРОИСХОДИТЬ

Объясни возможную психологическую динамику,
но не ставь диагнозов.

🎯 ЧТО ДЕЛАТЬ

Дай 3 конкретных действия.

✍️ ЧТО МОЖНО НАПИСАТЬ

Если нужен разговор — предложи
один лучший вариант сообщения.

⭐ ВЫВОД

Коротко скажи, что ты думаешь
о ситуации.

Не утверждай, что точно знаешь мысли
другого человека.
Не растягивай ответ.
"""

# ============================================================
# ТРЕВОГА И СТРЕСС
# ============================================================

STRESS_PROMPT = """
Пользователь рассказал о тревоге или стрессе.

Ответь спокойно, коротко и практично.

😰 ЧТО ПРОИСХОДИТ

Кратко объясни возможную суть состояния.

🧠 ПОЧЕМУ ТАК МОЖЕТ БЫТЬ

Назови несколько возможных причин.

🎯 ЧТО СДЕЛАТЬ СЕЙЧАС

Дай 3 конкретных действия,
которые можно попробовать прямо сейчас.

💡 ЧТО ПОМОЖЕТ ДАЛЬШЕ

Дай 2–3 практических рекомендации.

Не ставь медицинских диагнозов.
Если ситуация выглядит серьёзной —
рекомендуй обратиться к специалисту.

Не растягивай ответ.
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
# ТЕСТ — СТИЛЬ ПРИВЯЗАННОСТИ
# ============================================================

ATTACHMENT_QUESTIONS = [

    "Если человек долго не отвечает мне, "
    "я начинаю переживать, что он потерял интерес.",

    "Мне легко доверять человеку, "
    "с которым я строю отношения.",

    "Когда отношения становятся слишком близкими, "
    "мне иногда хочется отдалиться.",

    "Мне часто нужно подтверждение того, "
    "что я важен человеку.",

    "Я спокойно могу говорить партнёру "
    "о своих чувствах и потребностях.",

    "Я боюсь, что близкий человек "
    "может внезапно уйти от меня.",

    "Мне комфортно проводить время "
    "отдельно от партнёра.",

    "Когда человек проявляет ко мне "
    "слишком много внимания, мне иногда становится некомфортно.",

    "После конфликта мне важно "
    "как можно быстрее восстановить близость.",

    "Я обычно спокойно отношусь "
    "к небольшим изменениям в поведении партнёра."
]

ATTACHMENT_OPTIONS = [
    ["1️⃣ Совсем не про меня"],
    ["2️⃣ Скорее не про меня"],
    ["3️⃣ Иногда про меня"],
    ["4️⃣ Скорее про меня"],
    ["5️⃣ Очень про меня"]
]

# ============================================================
# РЕЗУЛЬТАТ ТЕСТА
# ============================================================
def attachment_result(answers):

    anxious = (
        answers[0]
        + answers[3]
        + answers[5]
        + answers[8]
    )

    avoidant = (
        answers[2]
        + answers[7]
    )

    secure = (
        answers[1]
        + answers[4]
        + answers[6]
        + answers[9]
    )

    # Переводим результаты в проценты
    anxious_percent = round(
        ((anxious - 4) / 16) * 100
    )

    avoidant_percent = round(
        ((avoidant - 2) / 8) * 100
    )

    secure_percent = round(
        ((secure - 4) / 16) * 100
    )

    # Ограничиваем значения
    anxious_percent = max(
        0,
        min(100, anxious_percent)
    )

    avoidant_percent = max(
        0,
        min(100, avoidant_percent)
    )

    secure_percent = max(
        0,
        min(100, secure_percent)
    )

    # Определяем основной стиль
    scores = {
        "Тревожный": anxious_percent,
        "Избегающий": avoidant_percent,
        "Надёжный": secure_percent
    }

    result_type = max(
        scores,
        key=scores.get
    )

    # Описание
    if result_type == "Тревожный":

        description = (
            "Ты можешь быть особенно чувствителен "
            "к изменениям в поведении близкого человека. "
            "Если человек отвечает реже или становится "
            "холоднее, это может вызывать тревогу и желание "
            "получить подтверждение его чувств."
        )

        advice = (
            "Старайся оценивать отношения по общей "
            "динамике, а не по отдельным сообщениям. "
            "Полезно прямо говорить о своих потребностях, "
            "вместо того чтобы постоянно искать подтверждение."
        )

    elif result_type == "Избегающий":

        description = (
            "Тебе может быть особенно важно сохранять "
            "личное пространство и независимость. "
            "Когда близости становится слишком много, "
            "может появляться желание дистанцироваться."
        )

        advice = (
            "Если хочется отдалиться, попробуй сначала "
            "объяснить человеку, что тебе нужно немного "
            "личного пространства, вместо того чтобы "
            "просто исчезать или закрываться."
        )

    else:

        description = (
            "Ты в целом способен сочетать близость "
            "и личные границы. Изменения в поведении "
            "партнёра не обязательно сразу воспринимаешь "
            "как угрозу отношениям."
        )

        advice = (
            "Продолжай открыто говорить о своих чувствах "
            "и потребностях и при этом уважать личное "
            "пространство другого человека."
        )

    result = (
        "🧪 ТЕСТ НА СТИЛЬ ПРИВЯЗАННОСТИ\n\n"
        f"❤️ ОСНОВНОЙ СТИЛЬ: {result_type}\n\n"
        f"😰 Тревожный: {anxious_percent}%\n"
        f"🚪 Избегающий: {avoidant_percent}%\n"
        f"💚 Надёжный: {secure_percent}%\n\n"
        f"🧠 ЧТО ЭТО ЗНАЧИТ\n\n"
        f"{description}\n\n"
        f"🎯 ЧТО ВАЖНО\n\n"
        f"{advice}\n\n"
        "Важно: этот тест не является медицинской "
        "или психологической диагностикой. Он показывает "
        "общую тенденцию по твоим ответам."
    )

    return (
        result_type,
        description,
        advice,
        result
    )
# ============================================================
# НАЧАЛО ТЕСТА
# ============================================================

async def start_attachment_test(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    if not profile_exists(user_id):

        await update.message.reply_text(
            "👤 Сначала создай профиль.\n\n"
            "Нажми /start"
        )

        return

    user_modes[user_id] = None

    test_states[user_id] = {
        "type": "attachment",
        "question": 0,
        "answers": []
    }

    await send_attachment_question(
        update,
        user_id
    )

# ============================================================
# ВОПРОС ТЕСТА
# ============================================================

async def send_attachment_question(
    update: Update,
    user_id
):

    state = test_states.get(
        user_id
    )

    if not state:
        return

    question_number = state["question"]

    if question_number >= len(
        ATTACHMENT_QUESTIONS
    ):
        return

    question = ATTACHMENT_QUESTIONS[
        question_number
    ]

    keyboard = ReplyKeyboardMarkup(
        ATTACHMENT_OPTIONS,
        resize_keyboard=True
    )

    await update.message.reply_text(
        "🧪 Тест на стиль привязанности\n\n"
        f"Вопрос {question_number + 1} из "
        f"{len(ATTACHMENT_QUESTIONS)}\n\n"
        f"{question}\n\n"
        "Выбери вариант, который лучше всего "
        "описывает тебя:",
        reply_markup=keyboard
    )

# ============================================================
# ОБРАБОТКА ТЕСТА
# ============================================================

async def handle_attachment_test(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    state = test_states.get(
        user_id
    )

    if not state:
        return False

    text = update.message.text.strip()

    values = {
        "1️⃣ Совсем не про меня": 1,
        "2️⃣ Скорее не про меня": 2,
        "3️⃣ Иногда про меня": 3,
        "4️⃣ Скорее про меня": 4,
        "5️⃣ Очень про меня": 5
    }

    if text not in values:

        await update.message.reply_text(
            "Выбери один из вариантов кнопкой 👇"
        )

        return True

    state["answers"].append(
        values[text]
    )

    state["question"] += 1

    if state["question"] < len(
        ATTACHMENT_QUESTIONS
    ):

        await send_attachment_question(
            update,
            user_id
        )

        return True

    answers = state["answers"]

    (
    result_type,
    description,
    advice,
    result
) = attachment_result(
    answers
)

    saved = save_analysis(
        user_id=user_id,
        analysis_type="Тест — стиль привязанности",
        user_message="Тест из 10 вопросов",
        result=result
    )

    test_states.pop(
        user_id,
        None
    )

    user_modes[user_id] = None

    await update.message.reply_text(
        result,
        reply_markup=main_keyboard()
    )

    if saved:

        await update.message.reply_text(
            "📚 Результат сохранён "
            "в «Мои разборы».",
            reply_markup=main_keyboard()
        )

    return True

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

    test_states.pop(
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
            "📚 Этот разбор сохранён "
            "в «Мои разборы».",
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
    # ТЕСТ
    # ========================================================

    if user_id in test_states:

        handled = await handle_attachment_test(
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

        test_states.pop(
            user_id,
            None
        )

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

        test_states.pop(
            user_id,
            None
        )

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

        test_states.pop(
            user_id,
            None
        )

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

        test_states.pop(
            user_id,
            None
        )

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

        test_states.pop(
            user_id,
            None
        )

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

        test_states.pop(
            user_id,
            None
        )

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

        test_states.pop(
            user_id,
            None
        )

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

        test_states.pop(
            user_id,
            None
        )

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

        test_states.pop(
            user_id,
            None
        )

        user_modes[user_id] = "stress"

        await update.message.reply_text(
            "😰 Расскажи, что тебя сейчас беспокоит."
        )

        return

    # ========================================================
    # ПСИХОЛОГИЧЕСКИЙ ТЕСТ
    # ========================================================

    if text == "🧪 Психологический тест":

        if not profile_exists(user_id):

            await update.message.reply_text(
                "👤 Сначала создай профиль.\n\n"
                "Нажми /start"
            )

            return

        user_modes[user_id] = None

        test_states.pop(
            user_id,
            None
        )

        test_keyboard = [
            ["❤️ Стиль привязанности"],
            ["🔙 Главное меню"]
        ]

        await update.message.reply_text(
            "🧪 ПСИХОЛОГИЧЕСКИЕ ТЕСТЫ\n\n"
            "Выбери тест 👇",
            reply_markup=ReplyKeyboardMarkup(
                test_keyboard,
                resize_keyboard=True
            )
        )

        return

    # ========================================================
    # СТИЛЬ ПРИВЯЗАННОСТИ
    # ========================================================

    if text == "❤️ Стиль привязанности":

        await start_attachment_test(
            update,
            context
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
        # СОХРАНЯЕМ
        # ====================================================

        saved = save_analysis(
            user_id=user_id,
            analysis_type=analysis_type,
            user_message=text,
            result=answer
        )

        # ====================================================
        # ОТПРАВЛЯЕМ
        # ====================================================

        await send_long_message(
            update,
            answer
        )

        if saved:

            await update.message.reply_text(
                "📚 Разбор сохранён.\n\n"
                "Посмотреть его можно в разделе "
                "«📚 Мои разборы».",
                reply_markup=main_keyboard()
            )

        else:

            await update.message.reply_text(
                "Разбор готов, но сохранить его "
                "в историю не удалось.",
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
