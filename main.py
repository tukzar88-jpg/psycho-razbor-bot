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

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN не задан")

if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY не задан")

client = genai.Client(api_key=GEMINI_API_KEY)

MODEL = "gemini-3.6-flash"

keyboard = [
    ["💬 Разбор переписки"],
    ["🧠 Разбор ситуации"],
    ["❤️ Отношения", "😰 Тревога и стресс"],
    ["🧪 Психологический тест"],
]

user_modes = {}


SYSTEM_PROMPT = """
Ты — ПСИХОРАЗБОР, AI-помощник по отношениям,
перепискам и жизненным ситуациям.

Твоя задача — давать человеку понятный,
честный и практически полезный анализ.

Правила:

- Не ставь медицинские или психиатрические диагнозы.
- Не утверждай, что точно знаешь мысли другого человека.
- Отделяй факты от предположений.
- Не придумывай отсутствующие факты.
- Если информации мало — скажи об этом.
- Не поддерживай опасное или токсичное поведение.
- Отвечай живым человеческим языком.
- Не пиши огромные лекции.
- Давай конкретные действия.

Используй формулировки:
"возможно",
"скорее всего",
"одна из причин",
"по имеющейся информации".

Главная цель — помочь человеку понять ситуацию
и решить, что делать дальше.
"""


CHAT_PROMPT = """
Пользователь прислал переписку.

Сделай разбор в следующем формате:

🔥 РАЗБОР ПЕРЕПИСКИ

📊 ИНТЕРЕС: X/10

Оцени только по реально видимым признакам.

💬 ИНИЦИАТИВА

Кто чаще:
- начинает разговор;
- задаёт вопросы;
- поддерживает диалог;
- предлагает темы;
- предлагает встречу.

🟢 ПРИЗНАКИ ИНТЕРЕСА

Укажи конкретные моменты.

🔴 ЧТО НАСТОРАЖИВАЕТ

Укажи конкретные моменты.

🧠 МОЙ ВЫВОД

Коротко и честно объясни ситуацию.

🎯 ЧТО ДЕЛАТЬ

Дай 2–4 конкретных действия.

✍️ ЧТО НАПИСАТЬ

Дай три варианта:

1. Спокойный
2. Уверенный
3. Дерзкий

Не придумывай факты.
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
Разбери ситуацию в отношениях.

Используй:

❤️ ЧТО ПРОИСХОДИТ

🔎 ВОЗМОЖНЫЕ ПРИЧИНЫ

⚠️ ПРОБЛЕМНЫЕ МОМЕНТЫ

🧠 ЧТО МОЖЕТ ПРОИСХОДИТЬ

🎯 ЧТО ДЕЛАТЬ ДАЛЬШЕ

✍️ ЧТО МОЖНО НАПИСАТЬ
"""


STRESS_PROMPT = """
Помоги пользователю разобраться со стрессом.

Используй:

😰 ЧТО ПРОИСХОДИТ

🧠 ПОЧЕМУ ТАК МОЖЕТ ПРОИСХОДИТЬ

🎯 ЧТО МОЖНО СДЕЛАТЬ СЕЙЧАС

💡 ЧТО ПОМОЖЕТ ДАЛЬШЕ

Не ставь диагнозов.
"""


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_modes[update.effective_user.id] = None

    await update.message.reply_text(
        "🧠 ПСИХОРАЗБОР\n\n"
        "Разберём переписку, отношения "
        "или сложную ситуацию.\n\n"
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
            "Можно просто скопировать сообщения сюда."
        )
        return

    if text == "🧠 Разбор ситуации":
        user_modes[user_id] = "situation"

        await update.message.reply_text(
            "🧠 Опиши ситуацию своими словами."
        )
        return

    if text == "❤️ Отношения":
        user_modes[user_id] = "relationship"

        await update.message.reply_text(
            "❤️ Расскажи, что происходит "
            "в отношениях."
        )
        return

    if text == "😰 Тревога и стресс":
        user_modes[user_id] = "stress"

        await update.message.reply_text(
            "😰 Расскажи, что тебя сейчас беспокоит."
        )
        return

    if text == "🧪 Психологический тест":
        await update.message.reply_text(
            "🧪 Тесты добавим следующим обновлением."
        )
        return

    mode = user_modes.get(user_id)

    if not mode:
        await update.message.reply_text(
            "Выбери раздел в меню 👇"
        )
        return

    await update.message.reply_text(
        "🧠 Анализирую..."
    )

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

        for i in range(0, len(answer), 4000):
            await update.message.reply_text(
                answer[i:i + 4000]
            )

    except Exception as e:
        logging.exception("Gemini error")

        await update.message.reply_text(
            "❌ Ошибка Gemini:\n\n"
            + str(e)[:3000]
        )


def main():
    print("ПСИХОРАЗБОР запускается...")

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

    print("ПСИХОРАЗБОР запущен.")

    app.run_polling()


if __name__ == "__main__":
    main()
