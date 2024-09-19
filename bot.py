import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackContext, MessageHandler, CallbackQueryHandler, filters, ConversationHandler
import os
import pickle
import datetime
import dateparser
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from dotenv import load_dotenv

# Настройки для логирования
logging.basicConfig(level=logging.DEBUG)

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
SCOPES = ['https://www.googleapis.com/auth/calendar']
ADD_TASK_NAME, ADD_TASK_TIME, DELETE_TASK_CONFIRM = range(3)
user_tasks = {}

def authenticate_google_calendar():
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    return build('calendar', 'v3', credentials=creds)

async def start(update: Update, context: CallbackContext) -> None:
    keyboard = [
        [InlineKeyboardButton("Добавить задачу", callback_data='add')],
        [InlineKeyboardButton("Удалить задачу", callback_data='delete')],
        [InlineKeyboardButton("Список задач", callback_data='list')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Привет! Выбери действие:", reply_markup=reply_markup)

async def button_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()
    logging.debug(f"Received callback data: {query.data}")

    if query.data == 'add':
        await query.edit_message_text(text="Введите название задачи:", reply_markup=main_menu())
        return ADD_TASK_NAME
    elif query.data == 'delete':
        await show_task_list_for_deletion(query, context)
        return DELETE_TASK_CONFIRM
    elif query.data == 'list':
        await list_tasks(query, context)
        return ConversationHandler.END
    elif query.data == 'menu':
        await show_main_menu(query, context)
        return ConversationHandler.END
    else:
        await query.edit_message_text("Неизвестное действие", reply_markup=main_menu())

async def add_task_name(update: Update, context: CallbackContext) -> None:
    context.user_data['task_name'] = update.message.text
    await update.message.reply_text("Введите время для задачи (например: 'завтра в 15:00' или '2023-09-18 14:30'):", reply_markup=main_menu())
    return ADD_TASK_TIME

async def add_task_time(update: Update, context: CallbackContext) -> None:
    task_name = context.user_data.get('task_name')
    task_time_str = update.message.text
    task_time = dateparser.parse(task_time_str)

    if not task_time:
        await update.message.reply_text("Не удалось распознать дату/время. Попробуй ещё раз (например: 'завтра в 15:00' или '2023-09-18 14:30').", reply_markup=main_menu())
        return ADD_TASK_TIME

    user_id = update.message.from_user.id
    if user_id not in user_tasks:
        user_tasks[user_id] = []

    user_tasks[user_id].append({'task': task_name, 'time': task_time})
    await update.message.reply_text(f"Задача '{task_name}' добавлена на {task_time.strftime('%Y-%m-%d %H:%M')}!", reply_markup=main_menu())
    add_task_to_google_calendar(task_name, task_time)
    await show_main_menu(update.callback_query, context)
    return ConversationHandler.END

async def show_task_list_for_deletion(query: Update.callback_query, context: CallbackContext) -> None:
    user_id = query.from_user.id
    if user_id not in user_tasks or not user_tasks[user_id]:
        await query.edit_message_text("У тебя нет задач.", reply_markup=main_menu())
        return

    keyboard = [[InlineKeyboardButton(f"{i+1}. {t['task']}", callback_data=str(i))] for i, t in enumerate(user_tasks[user_id])]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("Выбери задачу для удаления:", reply_markup=reply_markup)
    return DELETE_TASK_CONFIRM

async def delete_task(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    task_index = int(query.data)

    if task_index < 0 or task_index >= len(user_tasks[user_id]):
        await query.edit_message_text("Неверный номер задачи.", reply_markup=main_menu())
        return

    removed_task = user_tasks[user_id].pop(task_index)
    await query.edit_message_text(f"Задача '{removed_task['task']}' удалена!", reply_markup=main_menu())
    await show_main_menu(query, context)
    return ConversationHandler.END

def add_task_to_google_calendar(task, task_time):
    service = authenticate_google_calendar()
    event = {
        'summary': task,
        'start': {
            'dateTime': task_time.isoformat(),
            'timeZone': 'UTC',
        },
        'end': {
            'dateTime': (task_time + datetime.timedelta(hours=1)).isoformat(),
            'timeZone': 'UTC',
        },
    }
    event = service.events().insert(calendarId='primary', body=event).execute()
    print(f"Задача добавлена в Google Calendar: {event.get('htmlLink')}")

async def list_tasks(query: Update.callback_query, context: CallbackContext) -> None:
    user_id = query.from_user.id
    if user_id not in user_tasks or not user_tasks[user_id]:
        await query.edit_message_text("У тебя нет задач.", reply_markup=main_menu())
        return

    tasks_text = '\n'.join(f"{i+1}. {t['task']} - {t['time'].strftime('%Y-%m-%d %H:%M')}" for i, t in enumerate(user_tasks[user_id]))
    await query.edit_message_text(f"Твои задачи:\n{tasks_text}", reply_markup=main_menu())

async def show_main_menu(query: Update.callback_query, context: CallbackContext) -> None:
    keyboard = [
        [InlineKeyboardButton("Добавить задачу", callback_data='add')],
        [InlineKeyboardButton("Удалить задачу", callback_data='delete')],
        [InlineKeyboardButton("Список задач", callback_data='list')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("Выбери действие:", reply_markup=reply_markup)

def main_menu():
    keyboard = [
        [InlineKeyboardButton("Главное меню", callback_data='menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def main() -> None:
    application = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern='^(add|delete|list|menu)$')],
        states={
            ADD_TASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_task_name)],
            ADD_TASK_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_task_time)],
            DELETE_TASK_CONFIRM: [CallbackQueryHandler(delete_task)]
        },
        fallbacks=[CallbackQueryHandler(button_handler, pattern='^(menu)$')],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.run_polling()

if __name__ == "__main__":
    main()
