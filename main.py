import os
import logging
from google import genai
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(level=logging.INFO)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY)

keyboard = [
    ["💬 Разбор переписки"],
    ["🧠 Разбор ситуации"],
    ["❤️ Отношения", "😰 Тревога и стресс"],
    ["🧪 Психологический тест"],
]

user_modes = {}


SYSTEM_PROMPT = """
Ты — ПСИХОРАЗБОР, умный и прямой AI-помощник по отношениям,
перепискам и жизненным ситуациям.

Твоя задача — давать человеку максимально полезный и понятный
разбор, а не общие психологические лекции.

ВАЖНЫЕ ПРАВИЛА:
- Не ставь медицинских или психиатрических диагнозов.
- Не утверждай, что точно знаешь мысли другого человека.
- Отделяй факты от предположений.
- Если информации недостаточно — прямо скажи об этом.
- Не обвиняй человека без оснований.
- Не поддерживай токсичное или опасное поведение.

СТИЛЬ:
- Пиши живым человеческим языком.
- Будь прямым.
- Не повторяй одно и то же.
- Не делай огромные лекции.
- Используй эмодзи умеренно.
- Главная цель — практическая польза.
"""


CHAT_ANALYSIS = """
Пользователь прислал переписку.

Проанализируй её и ответь строго в следующем формате:

🔥 РАЗБОР ПЕРЕПИСКИ

📊 ИНТЕРЕС: X/10

Оцени только по признакам, которые реально видны в переписке.

💬 ИНИЦИАТИВА

Кто чаще начинает разговор?
Кто задаёт вопросы?
Кто поддерживает диалог?

🟢 ЧТО ГОВОРИТ В ПОЛЬЗУ ИНТЕРЕСА

3–5 конкретных наблюдений.

🔴 ЧТО НАСТОРАЖИВАЕТ

3–5 конкретных наблюдений.

🧠 МОЙ ВЫВОД

Коротко объясни, что наиболее вероятно происходит.

🎯 ЧТО ДЕЛАТЬ

Дай 2–4 конкретных действия.

✍️ ЧТО НАПИСАТЬ

Предложи 3 варианта ответа:

1. Спокойный
2. Уверенный
3. Дерзкий

Не придумывай факты, которых нет в переписке.
Если переписка слишком короткая — скажи об этом.
"""


SITUATION_ANALYSIS = """
Пользователь описал ситуацию.

Сделай разбор:

🔎 ЧТО ПРОИСХОДИТ

🧠 ВОЗМОЖНЫЕ ПРИЧИНЫ

⚠️ ЧТО НАСТОРАЖИВАЕТ

🎯 ЧТО ДЕЛАТЬ

✍️ ЕСЛИ НУЖНО НАПИСАТЬ

Предложи конкретный вариант сообщения.

Не выдавай предположение за факт.
"""


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_modes[update.effective_user.id] = None

    await update.message.reply_text(
        "🧠 ПСИХОРАЗБОР\n\n"
        "Разберём переписку, отношения или ситуацию.\n\n"
        "Выбирай 👇",
        reply_markup=ReplyKeyboardMarkup(
            keyboard,
            resize_keyboard=True
        )
    )


async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user_id = update.effective_user.id
    text = update.message.text

    if text == "💬 Разбор переписки":
        user_modes[user_id] = "chat"

        await update.message.reply_text(
            "💬 Пришли переписку целиком.\n\n"
            "Можно просто скопировать сообщения сюда.\n\n"
            "Чем больше контекста — тем точнее разбор."
        )
        return

    if text == "🧠 Разбор ситуации":
        user_modes[user_id] = "situation"

        await update.message.reply_text(
            "🧠 Опиши ситуацию своими словами.\n\n"
            "Например:\n"
            "«Девушка раньше сама постоянно писала, "
            "а последние три дня отвечает очень коротко. "
            "Что это может значить?»"
        )
        return

    if text == "❤️ Отношения":
        user_modes[user_id] = "relationship"

        await update.message.reply_text(
            "❤️ Расскажи, что происходит в отношениях.\n\n"
            "Опиши ситуацию подробно."
        )
        return

    if text == "😰 Тревога и стресс":
        user_modes[user_id] = "stress"

        await update.message.reply_text(
            "😰 Расскажи, что тебя сейчас беспокоит.\n\n"
            "Я постараюсь помочь разобраться "
            "и предложить практические шаги."
        )
        return

    if text == "🧪 Психологический тест":
        await update.message.reply_text(
            "🧪 Раздел тестов пока готовится.\n\n"
            "Скоро здесь появятся полноценные тесты "
            "с персональным разбором."
        )
        return

    mode = user_modes.get(user_id)

    if not mode:
        await update.message.reply_text(
            "Выбери раздел в меню 👇"
        )
        return

    await update.message.reply_text("🧠 Анализирую...")

    if mode == "chat":
        prompt = SYSTEM_PROMPT + "\n\n" + CHAT_ANALYSIS

    elif mode == "situation":
        prompt = SYSTEM_PROMPT + "\n\n" + SITUATION_ANALYSIS

    elif mode == "relationship":
        prompt = SYSTEM_PROMPT + """
Разбери отношения между людьми.
Обрати внимание на взаимность, доверие,
границы, инициативу и возможные проблемы.
Дай конкретные рекомендации.
"""

    elif mode == "stress":
        prompt = SYSTEM_PROMPT + """
Помоги человеку разобраться со стрессом или тревогой.
Дай несколько простых практических шагов.
Не ставь диагнозы.
"""

    else:
        prompt = SYSTEM_PROMPT

    prompt += "\n\nСООБЩЕНИЕ ПОЛЬЗОВАТЕЛЯ:\n" + text

    try:
        response = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=prompt
        )

        answer = response.text

        await update.message.reply_text(answer)

    except Exception:
        logging.exception("Gemini error")

        await update.message.reply_text(
            "❌ Не удалось получить анализ.\n\n"
            "Попробуй ещё раз через несколько секунд."
        )


def main():
    if not TELEGRAM_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN не задан"
        )

    if not GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY не задан"
        )

    app = Application.builder().token(
        TELEGRAM_TOKEN
    ).build()

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    print("ПСИХОРАЗБОР запущен")

    app.run_polling()


if __name__ == "__main__":
    main()
