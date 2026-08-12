import os
import logging
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

keyboard = [
    ["💬 Разбор переписки"],
    ["🧠 Разбор ситуации"],
    ["❤️ Отношения", "😰 Тревога и стресс"],
    ["🧪 Психологический тест"],
]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🧠 ПСИХОРАЗБОР\n\n"
        "Я помогу разобраться в отношениях, переписках "
        "и сложных жизненных ситуациях.\n\n"
        "Выбери, что хочешь разобрать:"
    )

    await update.message.reply_text(
        text,
        reply_markup=ReplyKeyboardMarkup(
            keyboard,
            resize_keyboard=True,
        ),
    )


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "💬 Разбор переписки":
        await update.message.reply_text(
            "💬 Пришли сюда переписку целиком.\n\n"
            "Я разберу её по:\n"
            "• заинтересованности\n"
            "• инициативе\n"
            "• эмоциональному тону\n"
            "• возможным проблемам\n"
            "• тому, что лучше написать дальше."
        )
        return

    if text == "🧠 Разбор ситуации":
        await update.message.reply_text(
            "🧠 Опиши ситуацию своими словами.\n\n"
            "Например:\n"
            "«Мы расстались месяц назад, но она продолжает "
            "смотреть мои сторис. Что это может значить?»"
        )
        return

    if text == "❤️ Отношения":
        await update.message.reply_text(
            "❤️ Расскажи, что происходит в отношениях.\n\n"
            "Чем подробнее опишешь ситуацию, тем полезнее "
            "будет разбор."
        )
        return

    if text == "😰 Тревога и стресс":
        await update.message.reply_text(
            "😰 Опиши, что тебя сейчас беспокоит.\n\n"
            "Я помогу разобрать ситуацию и предложу "
            "несколько практических способов справиться."
        )
        return

    if text == "🧪 Психологический тест":
        await update.message.reply_text(
            "🧪 Раздел тестов скоро будет доступен.\n\n"
            "Мы добавим персональные психологические тесты "
            "с подробным разбором результатов."
        )
        return

    await update.message.reply_text(
        "Получил сообщение.\n\n"
        "Сейчас подключаем нейросеть — после этого я смогу "
        "анализировать твои ситуации и переписки."
    )


def main():
    if not TOKEN:
        raise RuntimeError(
            "Не задана переменная TELEGRAM_BOT_TOKEN"
        )

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            message_handler,
        )
    )

    print("ПСИХОРАЗБОР запущен")

    app.run_polling()


if __name__ == "__main__":
    main()
