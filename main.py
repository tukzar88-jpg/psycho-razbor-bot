import os
import logging
import base64
import re

from google import genai

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

if not TELEGRAM_TOKEN:
    raise RuntimeError(
        "TELEGRAM_BOT_TOKEN не задан в Railway"
    )

if not GEMINI_API_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY не задан в Railway"
    )


client = genai.Client(
    api_key=GEMINI_API_KEY
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
    ["⚙️ Мой профиль"],
]


gender_keyboard = [
    ["👨 Мужской", "👩 Женский"],
    ["Не хочу указывать"],
]


# ============================================================
# ДАННЫЕ ПОЛЬЗОВАТЕЛЕЙ
# ============================================================

# Профиль пользователя:
# {
#     user_id: {
#         "name": "...",
#         "age": "...",
#         "gender": "..."
#     }
# }

user_profiles = {}


# Текущий режим пользователя
user_modes = {}


# Этап заполнения профиля
user_profile_steps = {}


# ============================================================
# ОЧИСТКА MARKDOWN
# ============================================================

def clean_markdown(text):
    """
    Убирает Markdown-разметку Gemini,
    чтобы Telegram показывал обычный красивый текст.
    """

    if not text:
        return text

    # Жирный текст
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)

    # Курсив
    text = re.sub(
        r"(?<!\*)\*(?!\s)(.*?)(?<!\s)\*(?!\*)",
        r"\1",
        text
    )

    # Подчёркивание
    text = re.sub(r"__(.*?)__", r"\1", text)

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

    # Обратные кавычки
    text = text.replace("```", "")
    text = text.replace("`", "")

    # Убираем лишние пробелы перед переносами
    text = re.sub(
        r"[ \t]+\n",
        "\n",
        text
    )

    # Максимум две пустые строки
    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text
    )

    return text.strip()


# ============================================================
# ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ
# ============================================================

def get_profile_text(user_id):
    """
    Возвращает профиль пользователя
    для передачи Gemini.
    """

    profile = user_profiles.get(user_id)

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
        "Учитывай этот профиль при анализе ситуации. "
        "Не делай выводы только на основании пола или возраста. "
        "Основывай анализ прежде всего на фактах и содержании "
        "переписки.\n"
    )


def profile_complete(user_id):
    """
    Проверяет, заполнен ли профиль.
    """

    profile = user_profiles.get(user_id)

    if not profile:
        return False

    return (
        bool(profile.get("name"))
        and bool(profile.get("age"))
        and bool(profile.get("gender"))
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
# РАЗБОР ТЕКСТОВОЙ ПЕРЕПИСКИ
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
# ПОКАЗ ГЛАВНОГО МЕНЮ
# ============================================================

async def show_main_menu(update):
    """
    Показывает основное меню.
    """

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
# НАЧАЛО ЗАПОЛНЕНИЯ ПРОФИЛЯ
# ============================================================

async def start_profile(update):
    """
    Запускает анкету пользователя.
    """

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

    if not profile_complete(user_id):

        await start_profile(update)

        return

    await show_main_menu(update)


# ============================================================
# МОЙ ПРОФИЛЬ
# ============================================================

async def edit_profile(update):
    """
    Запускает повторное заполнение профиля.
    """

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

        if user_id not in user_profiles:

            user_profiles[user_id] = {}

        user_profiles[user_id]["name"] = name

        user_profile_steps[user_id] = "age"

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

        user_profiles[user_id]["age"] = age

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

        user_profiles[user_id]["gender"] = gender

        user_profile_steps.pop(user_id, None)

        user_modes[user_id] = None

        await update.message.reply_text(
            "✅ Профиль заполнен!\n\n"
            "Теперь я смогу учитывать твой возраст, "
            "имя и пол при анализе переписок и ситуаций."
        )

        await show_main_menu(update)

        return True

    return False


# ============================================================
# АНАЛИЗ СКРИНШОТА
# ============================================================

async def handle_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    # Если профиль не заполнен
    if not profile_complete(user_id):

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

        image_bytes = await telegram_file.download_as_bytearray()

        image_b64 = base64.b64encode(
            bytes(image_bytes)
        ).decode("utf-8")


        # Профиль пользователя
        profile_text = get_profile_text(user_id)


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


        # Убираем Markdown
        answer = clean_markdown(answer)


        # Telegram ограничивает длину сообщения
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
    # СНАЧАЛА ПРОВЕРЯЕМ АНКЕТУ
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

    mode = user_modes.get(user_id)

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

    profile_text = get_profile_text(user_id)


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


        # Убираем Markdown
        answer = clean_markdown(answer)


        # Отправляем частями
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
# ОБРАБОТКА КОМАНДЫ /PROFILE
# ============================================================

async def profile_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    profile = user_profiles.get(user_id)

    if not profile:

        await start_profile(update)

        return


    name = profile.get("name", "не указано")
    age = profile.get("age", "не указано")
    gender = profile.get("gender", "не указан")


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
# ЗАПУСК ПРОГРАММЫ
# ============================================================

if __name__ == "__main__":

    main()
