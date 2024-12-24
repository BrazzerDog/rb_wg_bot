import os
import re
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ConversationHandler, CallbackQueryHandler, ContextTypes
)
from database import Database
from keyboards import get_yes_no_keyboard, get_report_period_keyboard
import utils
# import phonenumbers  # Добавьте в requirements.txt: phonenumbers==8.13.32
import sqlite3
from collections import defaultdict
import time
import logging

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

logger = logging.getLogger(__name__)

load_dotenv()

ADMIN_USERS = set()  # Множество для хранения ID админов

(
    BIRTH_DATE, FIRST_NAME, LAST_NAME, PATRONYMIC, PHONE_NUMBER,
    MILITARY_SPEC, DENTAL_SANATION, MEDICAL_CERTIFICATES, 
    FOREIGN_PASSPORT, ACTIVE_CONTRACTS
) = range(10)

db = Database()

RATE_LIMIT = {}  # Словарь для отслеживания времени между сообщениями
SPAM_COUNTER = defaultdict(int)
SPAM_RESET_TIME = 60  # Сброс счетчика спама через 60 секунд
MAX_MESSAGES = 50  # Увеличим максимальное количество сообщений в минуту
MIN_MESSAGE_INTERVAL = 0.5  # Уменьшим минимальный интервал между сообщениями до 0.5 секунды

# Словари для отслеживания попыток
KEY_ATTEMPTS = defaultdict(list)
BLOCKED_USERS = set()
MAX_KEY_ATTEMPTS = 3  # Максимальное количество попыток ввода ключа
BLOCK_TIME = 3600  # Время блокировки в секундах (1 час)

TOTAL_STEPS = 8  # Общее количество шагов
STEPS = {
    BIRTH_DATE: 1,
    FIRST_NAME: 2,
    PHONE_NUMBER: 3,
    MILITARY_SPEC: 4,
    DENTAL_SANATION: 5,
    MEDICAL_CERTIFICATES: 6,
    FOREIGN_PASSPORT: 7,
    ACTIVE_CONTRACTS: 8
}

def generate_progress_bar(current_step):
    filled = "⬢"  # Заполненный символ
    empty = "⬡"   # Пустой символ
    progress = (current_step / TOTAL_STEPS) * 100
    
    bar = ""
    bar += f"\n\n<b>Прогресс заполнения анкеты:</b>\n"
    bar += filled * current_step + empty * (TOTAL_STEPS - current_step)
    bar += f" {current_step}/{TOTAL_STEPS} ({progress:.0f}%)\n\n"
    
    return bar

async def rate_limit_check(user_id):
    current_time = time.time()
    
    # Сброс счетчика если прошла минута
    if user_id in RATE_LIMIT and current_time - RATE_LIMIT[user_id] > SPAM_RESET_TIME:
        SPAM_COUNTER[user_id] = 0
    
    # Проверка минимального интервала между сообщениями
    if user_id in RATE_LIMIT:
        time_diff = current_time - RATE_LIMIT[user_id]
        if time_diff < MIN_MESSAGE_INTERVAL:  # Уменьшенный интервал
            return False
    
    RATE_LIMIT[user_id] = current_time
    SPAM_COUNTER[user_id] += 1
    
    # Если превышен лимит сообщений в минуту
    if SPAM_COUNTER[user_id] > MAX_MESSAGES:
        db.ban_user(user_id)
        BLOCKED_USERS.add(user_id)
        return False
            
    return True

def validate_date(date_str):
    try:
        birth_date = datetime.strptime(date_str, '%d.%m.%Y')
        today = datetime.now()
        age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
        
        if age < 18 or age > 65:
            return False
        return True
    except ValueError:
        return False

def validate_name(name):
    return bool(re.match(r'^[А-ЯЁа-яё\s-]{2,50}$', name))

def validate_phone(phone_str):
    try:
        # Удаляем все пробелы и другие символы из номера
        phone_str = ''.join(filter(str.isdigit, phone_str))
        
        # Проверяем длину номера (от 10 до 15 цифр по международному стандарту)
        if not (10 <= len(phone_str) <= 15):
            return False, None
            
        # Если номер начинается с 8, считаем его российским
        if phone_str.startswith('8'):
            formatted_number = '+7' + phone_str[1:]
        # Если начинается с 7, добавляем +
        elif phone_str.startswith('7'):
            formatted_number = '+' + phone_str
        # Если короткий номер (10 цифр), считаем российским
        elif len(phone_str) == 10:
            formatted_number = '+7' + phone_str
        # Иначе добавляем + для международного формата
        else:
            formatted_number = '+' + phone_str
            
        return True, formatted_number
        
    except Exception:
        return False, None

async def start(update: Update, context):
    user_id = update.effective_user.id
    
    # Сначала проверяем, не является ли сообщение секретным ключом
    if update.message.text == os.getenv('ADMIN_KEY'):
        ADMIN_USERS.add(user_id)  # Добавляем пользователя в множество админов
        await update.message.reply_text(
            "Выберите период для отчета:",
            reply_markup=get_report_period_keyboard()
        )
        return ConversationHandler.END

    if db.is_user_banned(user_id):
        await update.message.reply_text("Доступ запрещен.")
        return ConversationHandler.END
    
    attempts = db.get_user_attempts(user_id)
    if attempts >= 3:
        await update.message.reply_text(
            "Вы уже использовали максимальное количество попыток регистрации (3)."
        )
        return ConversationHandler.END
    
    context.user_data.clear()
    progress = generate_progress_bar(1)
    await update.message.reply_text(
        f"Здравствуйте! Для продолжения регистрации, пожалуйста, "
        f"ответьте на несколько вопросов.\n\n"
        f"У вас осталось {3 - attempts} попыток регистрации."
        f"{progress}"
        f"Укажите вашу дату рождения в формате ДД.ММ.ГГГГ\n"
        f"Например: 01.01.1990",
        parse_mode='HTML'
    )
    return BIRTH_DATE

async def process_birth_date(update: Update, context):
    # Проверяем секретный ключ и здесь тоже
    if update.message.text == os.getenv('ADMIN_KEY'):
        await update.message.reply_text(
            "Выберите период для отчета:",
            reply_markup=get_report_period_keyboard()
        )
        return ConversationHandler.END

    logger.info("Processing birth date: %s", update.message.text)
    if not await rate_limit_check(update.effective_user.id):
        logger.warning("Rate limit exceeded for user %s", update.effective_user.id)
        return
        
    birth_date = update.message.text
    
    if not validate_date(birth_date):
        logger.info("Invalid date format: %s", birth_date)
        await update.message.reply_text(
            "Неверный формат даты или возраст не соответствует требованиям (18-65 лет).\n"
            "Пожалуйста, используйте формат ДД.ММ.ГГГГ\n"
            "Например: 01.01.1990"
        )
        return BIRTH_DATE
    
    logger.info("Valid date received: %s", birth_date)
    context.user_data['birth_date'] = birth_date
    progress = generate_progress_bar(STEPS[FIRST_NAME])
    await update.message.reply_text(
        f"{progress}"
        f"Введите ваши ФИО (Фамилия Имя Отчество).\n"
        f"Пример: Иванов Иван Иванович\n"
        f"Используйте только русские буквы, пробел и дефис.",
        parse_mode='HTML'
    )
    return FIRST_NAME

async def process_first_name(update: Update, context):
    full_name = update.message.text.split()
    
    if len(full_name) != 3:
        await update.message.reply_text(
            "Пожалуйста, введите полные ФИО через пробел.\n"
            "Пример: Иванов Иван Иванович"
        )
        return FIRST_NAME
    
    last_name, first_name, patronymic = full_name
    
    if not all(validate_name(name) for name in [last_name, first_name, patronymic]):
        await update.message.reply_text(
            "Неверный формат ФИО. Используйте только русские буквы, пробел и дефис.\n"
            "Пример: Иванов Иван Иванович"
        )
        return FIRST_NAME
    
    context.user_data['last_name'] = last_name
    context.user_data['first_name'] = first_name
    context.user_data['patronymic'] = patronymic
    
    await update.message.reply_text(
        "Введите ваш номер телефона.\n"
        "Например: +79999999999 или 89999999999"
    )
    return PHONE_NUMBER

async def process_last_name(update: Update, context):
    last_name = update.message.text
    
    if not validate_name(last_name):
        await update.message.reply_text(
            "Неверный формат фамилии. Используйте только русские буквы, пробел и дефис."
        )
        return LAST_NAME
    
    context.user_data['last_name'] = last_name
    await update.message.reply_text(
        "Введите ваше отчество.\n"
        "Используйте только русские буквы, пробел и дефис."
    )
    return PATRONYMIC

async def process_patronymic(update: Update, context):
    patronymic = update.message.text
    
    if not validate_name(patronymic):
        await update.message.reply_text(
            "Неверный формат отчества. Используйте только русские буквы, пробел и дефис."
        )
        return PATRONYMIC
    
    context.user_data['patronymic'] = patronymic
    await update.message.reply_text(
        "Введите ваш номер телефона.\n"
        "Например: +79999999999 или 89999999999"
    )
    return PHONE_NUMBER

async def process_phone_number(update: Update, context):
    phone = update.message.text
    
    is_valid, formatted_number = validate_phone(phone)
    if not is_valid:
        progress = generate_progress_bar(STEPS[PHONE_NUMBER])
        await update.message.reply_text(
            f"{progress}"
            "Неверный формат номера телефона.\n"
            "Примеры правильного формата:\n"
            "+79999999999\n"
            "89999999999\n"
            "9999999999\n"
            "+12345678901 (международный формат)\n\n"
            "Номер должен содержать от 10 до 15 цифр.",
            parse_mode='HTML'
        )
        return PHONE_NUMBER
    
    context.user_data['phone_number'] = formatted_number
    progress = generate_progress_bar(STEPS[MILITARY_SPEC])
    await update.message.reply_text(
        f"{progress}"
        "Укажите номера ВУС и профессии через точку с запятой (;)\n\n"
        "Примеры:\n"
        "837, 166, 461; Плотник, Маляр, Крановщик - если несколько ВУС и профессий\n"
        "837; Плотник - если одна ВУС и профессия\n"
        "нет - если нет ВУС и профессии",
        parse_mode='HTML'
    )
    return MILITARY_SPEC

def validate_military_spec(text):
    # Если указано "нет", это валидное значение
    if text.lower() == 'нет':
        return True, 'нет'
        
    parts = text.split(';')
    if len(parts) != 2:
        return False, None
        
    vus_part, prof_part = parts
    
    # Обрабатываем ВУС
    specs = []
    for spec in vus_part.split(','):
        # Извлекаем только цифры из каждой части
        digits = ''.join(filter(str.isdigit, spec))
        if digits:  # Если остались цифры
            specs.append(digits)
    
    # Проверяем каждый ВУС на соответствие формату (3-4 цифры)
    if not specs or not all(3 <= len(spec) <= 4 for spec in specs):
        return False, None
            
    # Форматируем результат: ВУС + профессии
    formatted_vus = ', '.join(sorted(specs))
    formatted_prof = prof_part.strip()
    
    if not formatted_prof:  # Если профессия не указана
        return False, None
        
    return True, f"{formatted_vus}; {formatted_prof}"

async def process_military_spec(update: Update, context):
    text = update.message.text.strip()
    is_valid, formatted_spec = validate_military_spec(text)
    
    if not is_valid:
        progress = generate_progress_bar(STEPS[MILITARY_SPEC])
        await update.message.reply_text(
            f"{progress}"
            "Неверный формат. Укажите номера ВУС и профессии через точку с запятой (;)\n\n"
            "Примеры:\n"
            "837, 166, 461; Плотник, Маляр, Крановщик - если несколько ВУС и профессий\n"
            "837; Плотник - если одна ВУС и профессия\n"
            "нет - если нет ВУС и профессии",
            parse_mode='HTML'
        )
        return MILITARY_SPEC
    
    context.user_data['military_spec'] = formatted_spec
    progress = generate_progress_bar(STEPS[DENTAL_SANATION])
    await update.message.reply_text(
        f"{progress}"
        f"Есть ли у вас санация полости рта?",
        reply_markup=get_yes_no_keyboard(),
        parse_mode='HTML'
    )
    return DENTAL_SANATION

async def process_dental_sanation(update: Update, context):
    answer = update.message.text
    if answer not in ['Да', 'Нет']:
        progress = generate_progress_bar(STEPS[DENTAL_SANATION])
        await update.message.reply_text(
            f"{progress}"
            "Пожалуйста, выберите 'Да' или 'Нет' на клавиатуре.",
            reply_markup=get_yes_no_keyboard(),
            parse_mode='HTML'
        )
        return DENTAL_SANATION
    
    context.user_data['dental_sanation'] = (answer == 'Да')
    progress = generate_progress_bar(STEPS[MEDICAL_CERTIFICATES])
    await update.message.reply_text(
        f"{progress}"
        "Есть ли у вас справки ВИЧ/Сифилис/Гепатит?",
        reply_markup=get_yes_no_keyboard(),
        parse_mode='HTML'
    )
    return MEDICAL_CERTIFICATES

async def process_medical_certificates(update: Update, context):
    answer = update.message.text
    if answer not in ['Да', 'Нет']:
        progress = generate_progress_bar(STEPS[MEDICAL_CERTIFICATES])
        await update.message.reply_text(
            f"{progress}"
            "Пожалуйста, выберите 'Да' или 'Нет' на клавиатуре.",
            reply_markup=get_yes_no_keyboard(),
            parse_mode='HTML'
        )
        return MEDICAL_CERTIFICATES
    
    context.user_data['medical_certificates'] = (answer == 'Да')
    progress = generate_progress_bar(STEPS[FOREIGN_PASSPORT])
    await update.message.reply_text(
        f"{progress}"
        "Есть ли у вас загранпаспорт?",
        reply_markup=get_yes_no_keyboard(),
        parse_mode='HTML'
    )
    return FOREIGN_PASSPORT

async def process_foreign_passport(update: Update, context):
    answer = update.message.text
    if answer not in ['Да', 'Нет']:
        progress = generate_progress_bar(STEPS[FOREIGN_PASSPORT])
        await update.message.reply_text(
            f"{progress}"
            "Пожалуйста, выберите 'Да' или 'Нет' на клавиатуре.",
            reply_markup=get_yes_no_keyboard(),
            parse_mode='HTML'
        )
        return FOREIGN_PASSPORT
    
    context.user_data['foreign_passport'] = (answer == 'Да')
    progress = generate_progress_bar(STEPS[ACTIVE_CONTRACTS])
    await update.message.reply_text(
        f"{progress}"
        "Есть ли у вас действующие контракты с силовыми ведомствами?",
        reply_markup=get_yes_no_keyboard(),
        parse_mode='HTML'
    )
    return ACTIVE_CONTRACTS

async def process_active_contracts(update: Update, context):
    answer = update.message.text
    if answer not in ['Да', 'Нет']:
        progress = generate_progress_bar(STEPS[ACTIVE_CONTRACTS])
        await update.message.reply_text(
            f"{progress}"
            "Пожалуйста, выберите 'Да' или 'Нет' на клавиатуре.",
            reply_markup=get_yes_no_keyboard(),
            parse_mode='HTML'
        )
        return ACTIVE_CONTRACTS
    
    context.user_data['active_contracts'] = (answer == 'Да')
    
    try:
        db.add_user(update.effective_user.id, context.user_data)
        await update.message.reply_text(
            "Спасибо! Ваши данные успешно сохранены.\n"
            "Если вам нужно заполнить анкету повторно, используйте команду /start",
            reply_markup=ReplyKeyboardRemove()
        )
    except sqlite3.IntegrityError:
        await update.message.reply_text(
            "Вы уже регистрировались ранее.\n"
            "Если нужно обновить данные, обратитесь к администратору.",
            reply_markup=ReplyKeyboardRemove()
        )
    except Exception as e:
        await update.message.reply_text(
            "Произошла ошибка при сохранении данных. Пожалуйста, попробуйте позже.",
            reply_markup=ReplyKeyboardRemove()
        )
        print(f"Error saving user data: {str(e)}")  # Логируем ошибку
    
    return ConversationHandler.END

async def cancel(update: Update, context):
    user = update.message.from_user
    context.user_data.clear()  # Очищаем данные пользователя
    
    await update.message.reply_text(
        f"Регистрация отменена. Все введённые данные удалены.\n"
        f"Чтобы начать регистрацию заново, используйте команду /start",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

async def process_message(update: Update, context):
    user_id = update.effective_user.id
    current_time = time.time()
    
    # Проверяем, не заблокирован ли пользователь
    if user_id in BLOCKED_USERS:
        return
    
    # Очищаем старые попытки (старше часа)
    KEY_ATTEMPTS[user_id] = [t for t in KEY_ATTEMPTS[user_id] if current_time - t < BLOCK_TIME]
    
    # Если слишком много попыток - блокируем
    if len(KEY_ATTEMPTS[user_id]) >= MAX_KEY_ATTEMPTS:
        BLOCKED_USERS.add(user_id)
        db.ban_user(user_id)  # Баним пользователя в БД
        await update.message.reply_text("Доступ заблокирован из-за превышения лимита попыток.")
        return
    
    # Проверяем ключ
    if update.message.text == os.getenv('ADMIN_KEY'):
        ADMIN_USERS.add(user_id)  # Добавляем пользователя в множество админов
        await update.message.reply_text(
            "Выберите период для отчета:",
            reply_markup=get_report_period_keyboard()
        )
        return
    
    # Если ключ неверный - записываем попытку
    if len(update.message.text) > 20:  # Если похоже на попытку ввода ключа
        KEY_ATTEMPTS[user_id].append(current_time)

async def process_report_callback(update: Update, context):
    query = update.callback_query
    await query.answer()
    
    # Если есть кнопки - значит ключ был введен правильно
    # Просто генерируем и отправляем отчет
    period = query.data.split('_')[1]
    try:
        filename = utils.generate_excel_report(db, period)
        await query.message.reply_document(
            document=open(filename, 'rb'),
            filename=filename
        )
        os.remove(filename)  # Удаляем файл после отправки
    except Exception as e:
        await query.message.reply_text(f"Ошибка при создании отчета: {str(e)}")

def cleanup_temp_data():
    current_time = time.time()
    # Очистка старых попыток ввода ключа
    for user_id in list(KEY_ATTEMPTS.keys()):
        KEY_ATTEMPTS[user_id] = [t for t in KEY_ATTEMPTS[user_id] if current_time - t < BLOCK_TIME]
        if not KEY_ATTEMPTS[user_id]:
            del KEY_ATTEMPTS[user_id]
    
    # Очистка счетчиков спама
    for user_id in list(SPAM_COUNTER.keys()):
        if current_time - RATE_LIMIT.get(user_id, 0) > SPAM_RESET_TIME:
            del SPAM_COUNTER[user_id]
            
    # Очистка старых отчетов
    utils.cleanup_old_reports()

def main():
    application = Application.builder().token(os.getenv('BOT_TOKEN')).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            BIRTH_DATE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, 
                    process_birth_date
                )
            ],
            FIRST_NAME: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, 
                    process_first_name
                )
            ],
            PHONE_NUMBER: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, 
                    process_phone_number
                )
            ],
            MILITARY_SPEC: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, 
                    process_military_spec
                )
            ],
            DENTAL_SANATION: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, 
                    process_dental_sanation
                )
            ],
            MEDICAL_CERTIFICATES: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, 
                    process_medical_certificates
                )
            ],
            FOREIGN_PASSPORT: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, 
                    process_foreign_passport
                )
            ],
            ACTIVE_CONTRACTS: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, 
                    process_active_contracts
                )
            ],
        },
        fallbacks=[],
        allow_reentry=True
    )

    # Добавляем обработчики
    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_message))
    application.add_handler(CallbackQueryHandler(process_report_callback, pattern='^report_'))

    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main() 