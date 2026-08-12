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
    raise RuntimeError("TELEGRAM_BOT_TOKEN не задан в Railway")

if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY не задан в Railway")

if not SUPABASE_URL:
    raise RuntimeError("SUPABASE_URL не задан в Railway")

if not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_KEY не задан в Railway")


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
# ДЛИННЫЕ СООБЩЕНИЯ
# ============================================================

async def send_long_message(
    update: Update,
    text: str
):
    if not text:
        return

    for i in range(0, len(text), 4000):
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
# ПРОФИЛЬ
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
        logging.exception("Ошибка получения профиля")
        return None


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

        profile_data = {
            "telegram_id": user_id,
            "name": name,
            "age": age,
            "gender": gender,
        }

        if existing.data:
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
        logging.exception("Ошибка сохранения профиля")
        return False


def profile_exists(user_id):
    profile = get_user_profile(user_id)

    if not profile:
        return False

    return bool(
        profile.get("name")
        and profile.get("age")
        and profile.get("gender")
    )


def profile_context(user_id):
    profile = get_user_profile(user_id)

    if not profile:
        return ""

    return (
        "\n\n"
        "ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ:\n"
        f"Имя: {profile.get('name', '')}\n"
        f"Возраст: {profile.get('age', '')}\n"
        f"Пол: {profile.get('gender', '')}\n\n"
        "Учитывай эти данные естественно."
    )


# ============================================================
# ОСНОВНОЙ PROMPT
# ============================================================

SYSTEM_PROMPT = """
Ты — ПСИХОРАЗБОР.

Ты умный, прямой и эмпатичный AI-помощник
по отношениям, перепискам и жизненным ситуациям.

Правила:

- Не ставь медицинских или психиатрических диагнозов.
- Не утверждай, что точно знаешь мысли другого человека.
- Отделяй факты от предположений.
- Не придумывай отсутствующие факты.
- Если информации недостаточно — скажи об этом.
- Не занимай автоматически сторону пользователя.
- Пиши простым человеческим языком.

Никогда не используй Markdown.

Для списков используй:
• пункт

Для нумерованных вариантов:
1. вариант
2. вариант
3. вариант

Эмодзи использовать можно.
"""


# ============================================================
# РАЗБОР ПЕРЕПИСКИ
# ============================================================

CHAT_PROMPT = """
Пользователь прислал переписку.

Сделай короткий, но точный разбор.

🔥 РАЗБОР ПЕРЕПИСКИ

📊 ИНТЕРЕС: X/10

Оцени заинтересованность по всей переписке.

Учитывай:
• инициативу;
• встречные вопросы;
• подробность ответов;
• желание продолжать разговор;
• флирт;
• предложение встречи;
• взаимность;
• изменение динамики.

🟢 ПРИЗНАКИ ИНТЕРЕСА

2–4 конкретных признака.

🔴 ЧТО НАСТОРАЖИВАЕТ

2–4 конкретных момента.

🟡 НЕОДНОЗНАЧНЫЕ МОМЕНТЫ

Что можно трактовать по-разному.

🧠 МОЙ ВЫВОД

Коротко объясни наиболее вероятную ситуацию.

🎯 ЧТО ДЕЛАТЬ

3 конкретных действия.

🚫 ЧЕГО НЕ ДЕЛАТЬ

2–3 предупреждения.

✍️ ЧТО НАПИСАТЬ

1. Спокойный вариант
2. Уверенный вариант
3. Дерзкий вариант

Не придумывай факты.
"""


# ============================================================
# СКРИНШОТ
# ============================================================

SCREENSHOT_PROMPT = """
На изображении находится переписка.

Внимательно прочитай текст.
Если часть текста плохо видна — не придумывай её.

🔥 РАЗБОР СКРИНШОТА

📊 ИНТЕРЕС: X/10

💬 ИНИЦИАТИВА

Кто пишет первым, задаёт вопросы,
поддерживает разговор и предлагает встречу.

🟢 ПРИЗНАКИ ИНТЕРЕСА

2–4 конкретных момента.

🔴 ЧТО НАСТОРАЖИВАЕТ

2–4 конкретных момента.

🟡 НЕОДНОЗНАЧНЫЕ МОМЕНТЫ

Что нельзя уверенно определить.

🧠 ЧТО, СКОРЕЕ ВСЕГО, ПРОИСХОДИТ

Наиболее вероятное объяснение.

🎯 ЧТО ДЕЛАТЬ

3 конкретных действия.

✍️ ЧТО НАПИСАТЬ

1. Спокойный вариант
2. Уверенный вариант
3. Дерзкий вариант

Не придумывай сообщения,
которых нет на изображении.
"""


# ============================================================
# СИТУАЦИЯ
# ============================================================

SITUATION_PROMPT = """
Пользователь описал личную ситуацию.

Сделай короткий разбор.

🔎 ЧТО ПРОИСХОДИТ

1–3 предложения.

🧠 ПОЧЕМУ ТАК МОЖЕТ БЫТЬ

2–3 наиболее вероятные причины.

⚠️ НА ЧТО ОБРАТИТЬ ВНИМАНИЕ

2–4 конкретных момента.

🎯 ЧТО ДЕЛАТЬ

3 конкретных действия.

🚫 ЧЕГО НЕ ДЕЛАТЬ

1–3 действия.

✍️ ЧТО СКАЗАТЬ

Один лучший вариант сообщения.

⭐ МОЙ ВЫВОД

2–3 предложения.

Не ставь диагнозов.
Не выдавай предположения за факты.
"""


# ============================================================
# ОТНОШЕНИЯ
# ============================================================

RELATIONSHIP_PROMPT = """
Пользователь рассказал о проблеме в отношениях.

❤️ ЧТО ПРОИСХОДИТ

Кратко объясни ситуацию.

🔎 ВОЗМОЖНЫЕ ПРИЧИНЫ

2–3 наиболее вероятных объяснения.

⚠️ ПРОБЛЕМНЫЕ МОМЕНТЫ

Конкретные признаки.

🧠 ПСИХОЛОГИЧЕСКАЯ ДИНАМИКА

Коротко.

🎯 ЧТО ДЕЛАТЬ

3 конкретных действия.

✍️ ЧТО МОЖНО НАПИСАТЬ

Один лучший вариант.

⭐ ВЫВОД

Коротко и честно.
"""


# ============================================================
# ТРЕВОГА
# ============================================================

STRESS_PROMPT = """
Пользователь рассказал о тревоге или стрессе.

😰 ЧТО ПРОИСХОДИТ

Кратко.

🧠 ПОЧЕМУ ТАК МОЖЕТ БЫТЬ

Несколько возможных причин.

🎯 ЧТО СДЕЛАТЬ СЕЙЧАС

3 конкретных действия.

💡 ЧТО ПОМОЖЕТ ДАЛЬШЕ

2–3 рекомендации.

Не ставь медицинских диагнозов.
"""


# ============================================================
# СОХРАНЕНИЕ
# ============================================================

def save_analysis(
    user_id,
    analysis_type,
    user_message,
    result
):
    try:
        response = (
            supabase
            .table("analyses")
            .insert({
                "telegram_id": user_id,
                "analysis_type": analysis_type,
                "user_message": user_message,
                "result": result,
            })
            .execute()
        )

        return bool(response.data)

    except Exception:
        logging.exception("Ошибка сохранения анализа")
        return False


# ============================================================
# ТЕСТ НА ПРИВЯЗАННОСТЬ
# ============================================================

ATTACHMENT_QUESTIONS = [

    (
        "anxiety",
        "Ты написал близкому человеку, а ответа нет несколько часов.\n\n"
        "1. Спокойно занимаюсь своими делами.\n"
        "2. Замечаю это, но почти не переживаю.\n"
        "3. Иногда думаю, почему он не отвечает.\n"
        "4. Начинаю переживать и искать причину.\n"
        "5. Мне трудно перестать об этом думать."
    ),

    (
        "avoidance",
        "Человек, который тебе нравится, хочет проводить с тобой "
        "намного больше времени.\n\n"
        "1. Мне приятно и комфортно.\n"
        "2. В основном приятно.\n"
        "3. Зависит от ситуации.\n"
        "4. Иногда начинаю чувствовать давление.\n"
        "5. Мне хочется увеличить дистанцию."
    ),

    (
        "anxiety",
        "Партнёр стал немного холоднее обычного.\n\n"
        "1. Спокойно жду и смотрю на общую ситуацию.\n"
        "2. Немного замечаю изменение.\n"
        "3. Иногда думаю, что причина во мне.\n"
        "4. Сильно анализирую его поведение.\n"
        "5. Мне нужно быстро понять, изменились ли его чувства."
    ),

    (
        "avoidance",
        "Во время конфликта тебе обычно проще:\n\n"
        "1. Спокойно обсудить проблему.\n"
        "2. Немного успокоиться и потом обсудить.\n"
        "3. Зависит от ситуации.\n"
        "4. Некоторое время избегать разговора.\n"
        "5. Закрыться и решать всё самостоятельно."
    ),

    (
        "anxiety",
        "Партнёр проводит вечер отдельно с друзьями.\n\n"
        "1. Нормально, у каждого своя жизнь.\n"
        "2. Почти не обращаю внимания.\n"
        "3. Иногда хочется знать, как проходит вечер.\n"
        "4. Мне становится немного тревожно.\n"
        "5. Я начинаю думать, почему ему хочется быть не со мной."
    ),

    (
        "avoidance",
        "Когда тебе эмоционально тяжело, ты скорее:\n\n"
        "1. Спокойно обращусь за поддержкой.\n"
        "2. Могу попросить о помощи, если нужно.\n"
        "3. Сначала попробую разобраться сам.\n"
        "4. Предпочту никого не посвящать.\n"
        "5. Мне очень трудно позволить другому человеку "
        "увидеть мою уязвимость."
    ),

    (
        "anxiety",
        "После ссоры партнёр говорит: «Давай завтра спокойно поговорим».\n\n"
        "1. Хорошо, спокойно подожду.\n"
        "2. Немного переживу, но справлюсь.\n"
        "3. Мне будет сложно не возвращаться к разговору мыслями.\n"
        "4. Хочу быстрее получить подтверждение, что всё нормально.\n"
        "5. До разговора мне будет очень трудно успокоиться."
    ),

    (
        "avoidance",
        "Партнёр хочет поговорить о ваших чувствах.\n\n"
        "1. Мне нормально говорить об этом.\n"
        "2. Скорее нормально.\n"
        "3. Иногда это сложно.\n"
        "4. Я предпочитаю не углубляться.\n"
        "5. Мне хочется уйти от такого разговора."
    ),

    (
        "anxiety",
        "Человек сказал, что ему нужно немного пространства.\n\n"
        "1. Спокойно принимаю это.\n"
        "2. Немного удивляюсь, но принимаю.\n"
        "3. Начинаю думать, что это значит.\n"
        "4. Боюсь, что человек отдаляется.\n"
        "5. Сразу появляется страх потерять отношения."
    ),

    (
        "avoidance",
        "Представь, что отношения становятся серьёзными.\n\n"
        "1. Это вызывает спокойствие.\n"
        "2. В основном мне комфортно.\n"
        "3. Иногда чувствую смешанные эмоции.\n"
        "4. Мне важно сохранить большую дистанцию.\n"
        "5. Серьёзная близость начинает меня напрягать."
    ),

    (
        "anxiety",
        "Партнёр несколько дней занят и отвечает заметно реже.\n\n"
        "1. Понимаю, что у человека могут быть дела.\n"
        "2. Почти не переживаю.\n"
        "3. Иногда проверяю, всё ли нормально.\n"
        "4. Начинаю сомневаться в его отношении ко мне.\n"
        "5. Мне трудно переключиться на свои дела."
    ),

    (
        "avoidance",
        "Если отношения требуют от тебя больше эмоциональной открытости:\n\n"
        "1. Мне нормально становиться открытее.\n"
        "2. Я постепенно привыкаю.\n"
        "3. Иногда мне нужно время.\n"
        "4. Мне хочется оставить часть чувств при себе.\n"
        "5. Мне проще держать эмоциональную дистанцию."
    ),
]


ATTACHMENT_OPTIONS = [
    ["1️⃣"],
    ["2️⃣"],
    ["3️⃣"],
    ["4️⃣"],
    ["5️⃣"],
]


# ============================================================
# РАСЧЁТ ТЕСТА
# ============================================================

def attachment_result(answers):

    anxiety_scores = []
    avoidance_scores = []

    for index, answer in enumerate(answers):

        category = ATTACHMENT_QUESTIONS[
            index
        ][0]

        if category == "anxiety":
            anxiety_scores.append(answer)

        elif category == "avoidance":
            avoidance_scores.append(answer)

    anxiety_mean = (
        sum(anxiety_scores)
        / len(anxiety_scores)
    )

    avoidance_mean = (
        sum(avoidance_scores)
        / len(avoidance_scores)
    )

    anxiety_percent = round(
        ((anxiety_mean - 1) / 4) * 100
    )

    avoidance_percent = round(
        ((avoidance_mean - 1) / 4) * 100
    )

    anxiety_percent = max(
        0,
        min(100, anxiety_percent)
    )

    avoidance_percent = max(
        0,
        min(100, avoidance_percent)
    )

    security_index = round(
        100
        - (
            anxiety_percent
            + avoidance_percent
        ) / 2
    )

    security_index = max(
        0,
        min(100, security_index)
    )

    # ========================================================
    # ПРОФИЛЬ
    # ========================================================

    if (
        anxiety_mean < 3
        and avoidance_mean < 3
    ):

        profile = "Преимущественно надёжный"

        description = (
            "По твоим ответам близость и отношения "
            "скорее не вызывают сильной тревоги "
            "или постоянного желания держать дистанцию."
        )

        recommendation = (
            "Сохраняй открытое общение, личные границы "
            "и привычку прямо говорить о своих потребностях."
        )

    elif (
        anxiety_mean >= 3
        and avoidance_mean < 3
    ):

        profile = "Преимущественно тревожный"

        description = (
            "Неопределённость в отношениях может "
            "переживаться тобой достаточно сильно. "
            "Изменение тона, задержка ответа или дистанция "
            "могут быстро запускать сомнения."
        )

        recommendation = (
            "Старайся проверять свои предположения фактами "
            "и смотреть на общую динамику отношений, "
            "а не на отдельные сигналы."
        )

    elif (
        anxiety_mean < 3
        and avoidance_mean >= 3
    ):

        profile = "Преимущественно избегающий"

        description = (
            "Для тебя особенно важно сохранять автономность. "
            "Когда отношения становятся очень близкими, "
            "может появляться потребность увеличить дистанцию."
        )

        recommendation = (
            "Учись объяснять потребность в пространстве "
            "словами, а не исчезновением или закрытостью."
        )

    else:

        profile = "Тревожно-избегающий"

        description = (
            "По ответам одновременно заметны тревожность "
            "и стремление защищать себя дистанцией. "
            "Близость может одновременно притягивать "
            "и вызывать напряжение."
        )

        recommendation = (
            "Не принимай решения об отношениях на эмоциях. "
            "Сначала разберись, чего ты хочешь, затем "
            "открыто скажи об этом человеку."
        )

    result = (
        "🧪 ТЕСТ НА СТИЛЬ ПРИВЯЗАННОСТИ\n\n"

        f"❤️ ТВОЙ ПРОФИЛЬ:\n"
        f"{profile}\n\n"

        "📊 РЕЗУЛЬТАТЫ:\n\n"

        f"😰 Тревожность — {anxiety_percent}%\n"
        f"🧊 Избегание близости — {avoidance_percent}%\n"
        f"🟢 Условный индекс безопасности — {security_index}%\n\n"

        "🧠 ЧТО ЭТО ЗНАЧИТ:\n\n"
        f"{description}\n\n"

        "🎯 ЧТО МОЖНО УЧЕСТЬ:\n\n"
        f"{recommendation}\n\n"

        "⚠️ ВАЖНО:\n\n"
        "Это адаптированный ситуационный тест "
        "для саморефлексии, а не диагностический инструмент. "
        "Проценты являются наглядным переводом ответов "
        "в шкалу 0–100 и не являются клиническими нормами."
    )

    return result


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
    ][1]

    keyboard_markup = ReplyKeyboardMarkup(
        ATTACHMENT_OPTIONS,
        resize_keyboard=True
    )

    await update.message.reply_text(
        "🧪 ТЕСТ НА СТИЛЬ ПРИВЯЗАННОСТИ\n\n"
        f"Вопрос {question_number + 1} из "
        f"{len(ATTACHMENT_QUESTIONS)}\n\n"
        f"{question}\n\n"
        "Выбери вариант кнопкой:",
        reply_markup=keyboard_markup
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
        "1️⃣": 1,
        "2️⃣": 2,
        "3️⃣": 3,
        "4️⃣": 4,
        "5️⃣": 5,
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

    try:

        result = attachment_result(
            state["answers"]
        )

    except Exception:

        logging.exception(
            "Ошибка расчёта теста"
        )

        test_states.pop(
            user_id,
            None
        )

        user_modes[user_id] = None

        await update.message.reply_text(
            "❌ Не удалось рассчитать результат. "
            "Попробуй пройти тест ещё раз.",
            reply_markup=main_keyboard()
        )

        return True

    saved = save_analysis(
        user_id=user_id,
        analysis_type="Тест — стиль привязанности",
        user_message="Адаптированный ситуационный тест",
        result=result
    )

    test_states.pop(
        user_id,
        None
    )

    user_modes[user_id] = None

    await send_long_message(
        update,
        result
    )

    if saved:

        await update.message.reply_text(
            "📚 Результат сохранён "
            "в «Мои разборы».",
            reply_markup=main_keyboard()
        )

    else:

        await update.message.reply_text(
            "Результат готов, но сохранить "
            "его в историю не удалось.",
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

    await update.message.reply_text(
        "👤 МОЙ ПРОФИЛЬ\n\n"
        f"Имя: {profile.get('name', '—')}\n"
        f"Возраст: {profile.get('age', '—')}\n"
        f"Пол: {profile.get('gender', '—')}\n\n"
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

            created_at = str(
                item.get(
                    "created_at",
                    ""
                )
            )

            if "T" in created_at:

                date_text = (
                    created_at
                    .split("T")[0]
                )

            else:

                date_text = created_at[:10]

            buttons.append([
                f"{index}️⃣ "
                f"{analysis_type} — "
                f"{date_text}"
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
# ОТКРЫТИЕ РАЗБОРА
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

        result = clean_markdown(
            item.get(
                "result",
                ""
            )
        )

        answer = (
            f"📚 {item.get('analysis_type', 'Разбор')}\n\n"
            f"🕐 {item.get('created_at', '')}\n\n"
            f"📝 ТВОЁ СООБЩЕНИЕ:\n\n"
            f"{item.get('user_message', '')}\n\n"
            "━━━━━━━━━━━━━━\n\n"
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
# СКРИНШОТ
# ============================================================

async def handle_photo(
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

    # Профиль
    if user_id in profile_states:

        handled = await handle_profile(
            update,
            context
        )

        if handled:
            return

    # Тест
    if user_id in test_states:

        handled = await handle_attachment_test(
            update,
            context
        )

        if handled:
            return

    # История
    if await open_analysis(
        update,
        context
    ):
        return

    # Главное меню
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

    # Мой профиль
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

    # Изменить профиль
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

    # Мои разборы
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

    # Разбор переписки
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

    # Анализ скриншота
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
            "📸 Пришли скриншот переписки."
        )

        return

    # Разбор ситуации
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

    # Отношения
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

    # Тревога
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

    # Психологический тест
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

        await update.message.reply_text(
            "🧪 ПСИХОЛОГИЧЕСКИЕ ТЕСТЫ\n\n"
            "Выбери тест 👇",
            reply_markup=ReplyKeyboardMarkup(
                [
                    ["❤️ Стиль привязанности"],
                    ["🔙 Главное меню"]
                ],
                resize_keyboard=True
            )
        )

        return

    # Стиль привязанности
    if text == "❤️ Стиль привязанности":

        await start_attachment_test(
            update,
            context
        )

        return

    # Проверяем режим
    mode = user_modes.get(
        user_id
    )

    if not mode:

        await update.message.reply_text(
            "Выбери раздел в меню 👇",
            reply_markup=main_keyboard()
        )

        return

    # История
    if isinstance(
        mode,
        dict
    ):

        if mode.get("type") == "history":

            await update.message.reply_text(
                "📚 Выбери разбор кнопкой выше 👆"
            )

            return

    # Режим скриншота
    if mode == "screenshot":

        await update.message.reply_text(
            "📸 Для этого режима отправь скриншот."
        )

        return

    # Начало анализа
    await update.message.reply_text(
        "🧠 Анализирую..."
    )

    # Выбираем prompt
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
        + profile_context(user_id)
        + "\n\n"
        + task
        + "\n\n"
        + "СООБЩЕНИЕ ПОЛЬЗОВАТЕЛЯ:\n"
        + text
    )

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

        saved = save_analysis(
            user_id=user_id,
            analysis_type=analysis_type,
            user_message=text,
            result=answer
        )

        await send_long_message(
            update,
            answer
        )

        if saved:

            await update.message.reply_text(
                "📚 Разбор сохранён.\n\n"
                "Посмотреть его можно в "
                "«📚 Мои разборы».",
                reply_markup=main_keyboard()
            )

        else:

            await update.message.reply_text(
                "Разбор готов, но сохранить "
                "его в историю не удалось.",
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

    app.add_handler(
        CommandHandler(
            "start",
            start
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
            filters.TEXT
            & ~filters.COMMAND,
            handle_message
        )
    )

    print(
        "🟢 ПСИХОРАЗБОР успешно запущен."
    )

    app.run_polling()


if __name__ == "__main__":
    main()
