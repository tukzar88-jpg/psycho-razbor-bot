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
Ты — ПсихоРазбор, умный и эмпатичный помощник по психологии и отношениям.

Твоя задача — помогать человеку разобраться в его ситуации простым,
понятным и человеческим языком.

Ты НЕ ставишь медицинские или психиатрические диагнозы.
Не утверждай, что точно знаешь мысли или намерения другого человека.
Используй формулировки "возможно", "это может означать", "одна из причин".

Если пользователь присылает переписку:
1. Оцени эмоциональный тон.
2. Оцени взаимную инициативу.
3. Обрати внимание на признаки интереса или дистанции.
4. Укажи возможные проблемные моменты.
5. Предложи, что можно сделать дальше.
6. Если уместно, предложи конкретный вариант ответа.

Отвечай структурировано, но без огромных лекций.
Будь прямым, спокойным и иногда немного дерзким.
Главная цель — дать человеку практическую пользу.
"""


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_modes[update.effective_user.id] = None

    await update.message.reply_text(
        "🧠 ПСИХОРАЗБОР\n\n"
        "Разберём переписку, отношения или ситуацию "
        "без лишней психологии из учебника.\n\n"
        "Выбери вариант:",
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
            "Я посмотрю на интерес, инициативу, "
            "тон общения и подскажу, что делать дальше."
        )
        return

    if text == "🧠 Разбор ситуации":
        user_modes[user_id] = "situation"
        await update.message.reply_text(
            "🧠 Опиши ситуацию своими словами.\n\n"
            "Например:\n"
            "«Мы расстались месяц назад, но она продолжает "
            "смотреть мои сторис. Что это может значить?»"
        )
        return

    if text == "❤️ Отношения":
        user_modes[user_id] = "relationship"
        await update.message.reply_text(
            "❤️ Расскажи, что происходит.\n\n"
            "Опиши ситуацию максимально подробно — "
            "я помогу разобрать её."
        )
        return

    if text == "😰 Тревога и стресс":
        user_modes[user_id] = "stress"
        await update.message.reply_text(
            "😰 Расскажи, что сейчас тебя беспокоит.\n\n"
            "Я помогу разобраться в ситуации и предложу "
            "практические способы справиться."
        )
        return

    if text == "🧪 Психологический тест":
        user_modes[user_id] = "test"
        await update.message.reply_text(
            "🧪 Тесты добавим следующим обновлением.\n\n"
            "А пока можешь выбрать «Разбор ситуации»."
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
        task = """
Пользователь прислал переписку.
Сделай разбор по следующим пунктам:

🔥 Общая оценка интереса
💬 Кто проявляет больше инициативы
🔎 Что бросается в глаза
⚠️ Что может быть проблемой
🎯 Что делать дальше
✍️ Что можно написать в ответ

Не придумывай факты, которых нет в переписке.
"""

    elif mode == "situation":
        task = """
Пользователь описал жизненную ситуацию.
Разбери её:

🔎 Что происходит
🧠 Возможные причины
⚠️ На что обратить внимание
🎯 Что лучше сделать
"""

    elif mode == "relationship":
        task = """
Разбери ситуацию в отношениях:

❤️ Что происходит между людьми
🔎 Возможные причины поведения
⚠️ Проблемные моменты
🎯 Что делать дальше
"""

    else:
        task = """
Помоги пользователю разобраться со стрессом или тревогой.
Дай спокойный, практический и безопасный ответ.
"""

    prompt = SYSTEM_PROMPT + "\n\n" + task + "\n\nСообщение пользователя:\n" + text

    try:
        response = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=prompt
        )

        answer = response.text

        await update.message.reply_text(answer)

    except Exception as e:
        logging.exception(e)

        await update.message.reply_text(
            "❌ Не удалось получить ответ нейросети.\n\n"
            "Попробуй ещё раз через несколько секунд."
        )


def main():
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан")

    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY не задан")

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))

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
