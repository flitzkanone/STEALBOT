# bot.py
import logging
import os
import json
import re
from datetime import datetime
from threading import Thread # Nötig für den Webserver
from flask import Flask     # Der Webserver

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.error import BadRequest

# --- Konfiguration ---
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
TRIGGER_WOERTER_STR = os.environ.get("TRIGGER_WOERTER", "")
TRIGGER_WOERTER = [word.strip().lower() for word in TRIGGER_WOERTER_STR.split(',') if word.strip()]
try:
    ZIEL_BENUTZER_ID = int(os.environ.get("ZIEL_BENUTZER_ID"))
    DATA_CHANNEL_ID = int(os.environ.get("DATA_CHANNEL_ID"))
except (ValueError, TypeError):
    ZIEL_BENUTZER_ID = None
    DATA_CHANNEL_ID = None

db_message_id = None
PAGE_SIZE = 5

# --- Flask Webserver für Render ---
app = Flask('')
@app.route('/')
def home():
    return "Bot is alive and the web server is running."

def run_flask():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

# --- Daten-Management via Telegram ---
async def init_database(application: Application):
    global db_message_id
    if not DATA_CHANNEL_ID: return
    bot = application.bot
    try:
        chat_info = await bot.get_chat(DATA_CHANNEL_ID)
        if chat_info.pinned_message:
            db_message_id = chat_info.pinned_message.message_id
            logger.info(f"Datenbank-Nachricht gefunden mit ID: {db_message_id}")
        else:
            logger.warning("Keine angepinnte Nachricht gefunden. Erstelle eine neue.")
            message = await bot.send_message(chat_id=DATA_CHANNEL_ID, text="[]")
            await bot.pin_chat_message(chat_id=DATA_CHANNEL_ID, message_id=message.message_id, disable_notification=True)
            db_message_id = message.message_id
            logger.info(f"Neue Datenbank-Nachricht erstellt und gepinnt mit ID: {db_message_id}")
    except Exception as e:
        logger.error(f"Fehler bei DB-Initialisierung: {e}. Ist der Bot Admin im Kanal {DATA_CHANNEL_ID}?")

async def get_data(bot) -> list:
    if not db_message_id: return []
    try:
        chat_info = await bot.get_chat(DATA_CHANNEL_ID)
        data_text = chat_info.pinned_message.text
        return json.loads(data_text)
    except (json.JSONDecodeError, AttributeError):
        return []
    except Exception as e:
        logger.error(f"Fehler beim Lesen der Daten: {e}")
        return []

async def save_data(bot, data: list):
    if not db_message_id: return
    try:
        data.sort(key=lambda x: x['timestamp'], reverse=True)
        # Limitiere auf die neuesten 200 Einträge, um das Nachrichtenlimit nicht zu sprengen
        data = data[:200]
        json_string = json.dumps(data, indent=2)

        await bot.edit_message_text(chat_id=DATA_CHANNEL_ID, message_id=db_message_id, text=json_string)
    except BadRequest as e:
        if "message is not modified" not in str(e):
            logger.error(f"Fehler beim Speichern der Daten: {e}")
    except Exception as e:
        logger.error(f"Allg. Fehler beim Speichern der Daten: {e}")

def extract_gutschein_code(text):
    match = re.search(r"Code:\s*(.*?)\s*Von", text, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else None

# --- Befehle und Callbacks ---
# (Dieser Teil bleibt gleich wie zuvor, hier zur Vollständigkeit)
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(f"Hallo! Sende /menu, um die Optionen anzuzeigen.")

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("Alle Nachrichten", callback_data='view_all_0')], [InlineKeyboardButton("Nur Gutschein-Codes", callback_data='view_codes_0')]]
    await update.message.reply_text('Hauptmenü:', reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not (ZIEL_BENUTZER_ID and DATA_CHANNEL_ID): return
    if not update.message or not update.message.text: return
    
    message = update.message
    if any(wort in message.text.lower() for wort in TRIGGER_WOERTER):
        try:
            await context.bot.forward_message(chat_id=ZIEL_BENUTZER_ID, from_chat_id=message.chat_id, message_id=message.message_id)
            
            current_data = await get_data(context.bot)
            new_entry = {"chat_title": message.chat.title or "Unbekannt", "message_text": message.text, "gutschein_code": extract_gutschein_code(message.text), "timestamp": datetime.utcnow().isoformat()}
            current_data.insert(0, new_entry)
            await save_data(context.bot, current_data)
            
            logger.info(f"Nachricht aus '{message.chat.title}' weitergeleitet und gespeichert.")
        except Exception as e:
            logger.error(f"Fehler in handle_group_message: {e}")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data_parts = query.data.split('_')
    action = f"{data_parts[0]}_{data_parts[1]}"
    page = int(data_parts[2])

    if action == "main_menu":
        keyboard = [[InlineKeyboardButton("Alle Nachrichten", callback_data='view_all_0')], [InlineKeyboardButton("Nur Gutschein-Codes", callback_data='view_codes_0')]]
        await query.edit_message_text(text='Hauptmenü:', reply_markup=InlineKeyboardMarkup(keyboard))
        return

    all_data = await get_data(context.bot)
    
    if action == "view_all":
        items = all_data
        text = "📜 Alle Nachrichten:\n\n"
    elif action == "view_codes":
        items = [item for item in all_data if item.get('gutschein_code')]
        text = "🎟️ Gutschein-Codes:\n\n"
    else: return

    start_index = page * PAGE_SIZE
    end_index = start_index + PAGE_SIZE
    paginated_items = items[start_index:end_index]
    
    if not paginated_items: text += "Keine Einträge gefunden."

    for i, item in enumerate(paginated_items):
        dt_object = datetime.fromisoformat(item['timestamp'])
        formatted_date = dt_object.strftime('%d.%m.%Y %H:%M')
        if action == "view_all":
            text += f"*{start_index + i + 1}.* Aus: *{item['chat_title']}* ({formatted_date})\n`{item['message_text'][:150]}...`\n\n"
        else:
            text += f"*{start_index + i + 1}.* Code: `{item['gutschein_code']}`\n_Aus: {item['chat_title']} ({formatted_date})_\n\n"

    keyboard = []
    row = []
    if page > 0: row.append(InlineKeyboardButton("◀️ Zurück", callback_data=f'{action}_{page - 1}'))
    if end_index < len(items): row.append(InlineKeyboardButton("Vor ▶️", callback_data=f'{action}_{page + 1}'))
    
    if row: keyboard.append(row)
    keyboard.append([InlineKeyboardButton("Hauptmenü 🏠", callback_data='main_menu_0')])
    
    try:
        await query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except BadRequest as e:
        if "message is not modified" not in str(e): raise e

def main() -> None:
    if not all([BOT_TOKEN, ZIEL_BENUTZER_ID, DATA_CHANNEL_ID]):
        logger.critical("Essentielle Umgebungsvariablen fehlen!")
        return

    # Starte den Webserver in einem eigenen Thread
    flask_thread = Thread(target=run_flask)
    flask_thread.start()

    application = Application.builder().token(BOT_TOKEN).build()
    
    application.post_init = init_database

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_group_message))

    logger.info("Bot startet mit Telegram-DB und Webserver...")
    application.run_polling()

if __name__ == "__main__":
    main()
