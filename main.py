import os
import logging
import io

from google import genai
from google.genai import types

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# =========================
# НАСТРОЙКИ
# =========================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN не задан")

if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY не задан")


client = genai.Client(
    api_key=GEMINI_API_KEY
)

MODEL = "gemini-3.6-flash"


# =========================
# МЕНЮ
# =========================

keyboard = [
    ["💬 Разбор переписки"],
    ["📸 Анализ скриншота"],
    ["🧠 Разбор ситуации"],
    ["❤️ Отношения", "😰 Тревога и стресс"],
    ["🧪 Психологический тест"],
]

user_modes = {}


# =========================
# ОСНОВНОЙ ПРОМПТ
# =========================

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
- Отвечай живым человеческим языком.

Главная цель — дать человеку практическую пользу.
"""


# =========================
# РАЗБОР ТЕКСТОВОЙ ПЕРЕПИСКИ
# =========================

CHAT_PROMPT = """
Пользователь прислал переписку.

Сделай разбор:

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


# =========================
# РАЗБОР СКРИНШОТА
# =========================

SCREENSHOT_PROMPT = """
На изображении находится переписка между людьми.

Твоя задача — внимательно изучить изображение
и сделать психологический анализ переписки.

Сначала самостоятельно прочитай сообщения
на изображении.

Если часть текста плохо читается,
не придумывай его.

Используй структуру:

🔥 РАЗБОР СКРИНШОТА

📊 ИНТЕРЕС: X/10

Оцени уровень заинтересованности
по поведению и сообщениям.

💬 ИНИЦИАТИВА

Определи:
- кто чаще пишет первым;
- кто задаёт вопросы;
- кто поддерживает разговор;
- кто пытается продолжить общение;
- кто предлагает встречу или контакт.

🟢 ПРИЗНАКИ ИНТЕРЕСА

Укажи конкретные сообщения или особенности
переписки, которые могут говорить об интересе.

🔴 ЧТО НАСТОРАЖИВАЕТ

Укажи признаки дистанции,
холодности или слабой инициативы.

🧠 ЧТО, СКОРЕЕ ВСЕГО, ПРОИСХОДИТ

Дай наиболее вероятное объяснение.

Помни:
ты не можешь точно знать мысли человека.

🎯 ЧТО ДЕЛАТЬ

Дай конкретные рекомендации.

✍️ ЧТО НАПИСАТЬ

Предложи три варианта:

1. Спокойный
2. Уверенный
3. Дерзкий

ВАЖНО:

Не придумывай сообщения,
которых нет на изображении.

Если скриншот слишком маленький,
обрезан или плохо читается,
честно сообщи об этом.
"""


# =========================
# СИТУАЦИЯ
# =========================

SITUATION_PROMPT = """
Пользователь описал ситуацию.

Разбери:

🔎 ЧТО ПРОИСХОДИТ

🧠 ВОЗМОЖНЫЕ ПРИЧИНЫ

⚠️ ЧТО НАСТОРАЖИВАЕТ

🎯 ЧТО ДЕЛАТЬ

✍️ ЧТО МОЖНО СКАЗАТЬ

Не выдавай предположения за факты.
"""


# =========================
# ОТНОШЕНИЯ
# =========================

RELATIONSHIP_PROMPT = """
Разбери ситуацию в отношениях.

❤️ ЧТО ПРОИСХОДИТ

🔎 ВОЗМОЖНЫЕ ПРИЧИНЫ

⚠️ ПРОБЛЕМНЫЕ МОМЕНТЫ

🧠 ЧТО МОЖЕТ ПРОИСХОДИТЬ

🎯 ЧТО ДЕЛАТЬ ДАЛЬШЕ

✍️ ЧТО МОЖНО НАПИСАТЬ

Не утверждай, что точно знаешь мысли другого человека.
"""


# =========================
# ТРЕВОГА
# =========================

STRESS_PROMPT = """
Помоги пользователю разобраться со стрессом.

😰 ЧТО ПРОИСХОДИТ

🧠 ПОЧЕМУ ТАК МОЖЕТ ПРОИСХОДИТЬ

🎯 ЧТО МОЖНО СДЕЛАТЬ СЕЙЧАС

💡 ЧТО ПОМОЖЕТ ДАЛЬШЕ

Не ставь диагнозов.
"""


# =========================
# START
# =========================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    user_modes[user_id] = None

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


# =========================
# ОБРАБОТКА ФОТО
# =========================

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

        photo = update.message.photo[-1]

        file = await context.bot.get_file(
            photo.file_id
        )

        image_bytes = await file.download_as_bytearray()

        image_part = types.Part.from_bytes(
            data=bytes(image_bytes),
            mime_type="image/jpeg"
        )

        prompt = (
            SYSTEM_PROMPT
            + "\n\n"
            + SCREENSHOT_PROMPT
        )

        response = client.interactions.create(
            model=MODEL,
            input=[
                prompt,
                image_part
            ]
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

        logging.exception(
            "Ошибка анализа изображения"
        )

        await update.message.reply_text(
            "❌ Ошибка при анализе скриншота:\n\n"
            + str(e)[:3000]
        )


# =========================
# ТЕКСТОВЫЕ СООБЩЕНИЯ
# =========================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    text = update.message.text


    # -------------------------
    # ПЕРЕПИСКА
    # -------------------------

    if text == "💬 Разбор переписки":

        user_modes[user_id] = "chat"

        await update.message.reply_text(
            "💬 Пришли переписку целиком.\n\n"
            "Можно просто скопировать сообщения сюда."
        )

        return


    # -------------------------
    # СКРИНШОТ
    # -------------------------

    if text == "📸 Анализ скриншота":

        user_modes[user_id] = "screenshot"

        await update.message.reply_text(
            "📸 Пришли скриншот переписки.\n\n"
            "Я попробую прочитать сообщения "
            "и определить интерес, инициативу "
            "и проблемные моменты."
        )

        return


    # -------------------------
    # СИТУАЦИЯ
    # -------------------------

    if text == "🧠 Разбор ситуации":

        user_modes[user_id] = "situation"

        await update.message.reply_text(
            "🧠 Опиши ситуацию своими словами."
        )

        return


    # -------------------------
    # ОТНОШЕНИЯ
    # -------------------------

    if text == "❤️ Отношения":

        user_modes[user_id] = "relationship"

        await update.message.reply_text(
            "❤️ Расскажи, что происходит "
            "в отношениях."
        )

        return


    # -------------------------
    # ТРЕВОГА
    # -------------------------

    if text == "😰 Тревога и стресс":

        user_modes[user_id] = "stress"

        await update.message.reply_text(
            "😰 Расскажи, что тебя беспокоит."
        )

        return


    # -------------------------
    # ТЕСТ
    # -------------------------

    if text == "🧪 Психологический тест":

        await update.message.reply_text(
            "🧪 Тесты добавим следующим обновлением."
        )

        return


    # -------------------------
    # РЕЖИМ
    # -------------------------

    mode = user_modes.get(user_id)

    if not mode:

        await update.message.reply_text(
            "Выбери раздел в меню 👇"
        )

        return


    # -------------------------
    # ПРОВЕРКА
    # -------------------------

    if mode == "screenshot":

        await update.message.reply_text(
            "📸 Для этого режима отправь именно "
            "фотографию или скриншот."
        )

        return


    await update.message.reply_text(
        "🧠 Анализирую..."
    )


    # -------------------------
    # ПРОМПТ
    # -------------------------

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


    # -------------------------
    # GEMINI
    # -------------------------

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

        logging.exception(
            "Ошибка Gemini"
        )

        await update.message.reply_text(
            "❌ Ошибка Gemini:\n\n"
            + str(e)[:3000]
        )


# =========================
# ЗАПУСК
# =========================

def main():

    print(
        "ПСИХОРАЗБОР запускается..."
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
        "ПСИХОРАЗБОР запущен."
    )

    app.run_polling()


if __name__ == "__main__":
    main()
