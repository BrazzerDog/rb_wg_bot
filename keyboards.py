from telegram import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton

def get_yes_no_keyboard():
    keyboard = [
        ['Да', 'Нет']
    ]
    return ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

def get_report_period_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("За день", callback_data="report_day"),
            InlineKeyboardButton("За неделю", callback_data="report_week")
        ],
        [
            InlineKeyboardButton("За месяц", callback_data="report_month"),
            InlineKeyboardButton("За год", callback_data="report_year")
        ]
    ]
    return InlineKeyboardMarkup(keyboard) 