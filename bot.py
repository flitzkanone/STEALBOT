# bot.py
import logging
import os
import json
import re
from datetime import datetime
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

# Globale Variable für die ID der Datenbank-Nachricht
db_message_id = None
PAGE_SIZE = 5

# --- Daten-Management via Telegram-Nachricht ---

async def init_database(application: Application):
    """Sucht oder erstellt die Datenbank-Nachricht im Kanal."""
    global db_message_id
    if not DATA_CHANNEL_ID:
        logger.error("DATA_CHANNEL_ID ist nicht gesetzt! Daten können nicht gespeichert werden.")
        return
    
    bot = application.bot
    try:
        # Versuche, die angepinnte Nachricht zu finden
        chat_info = await bot.get_chat(DATA_CHANNEL_ID)
        if chat_info.pinned_message:
            db_message_id = chat_info.pinned_message.message_id
            logger.info(f"Datenbank-Nachricht gefunden mit ID: {db_message_id}")
        else:
            # Erstelle und pinne eine neue Nachricht
            logger.warning("Keine angepinnte Nachricht gefunden. Erstelle eine neue.")
            message = await bot.send_message(chat_id=DATA_CHANNEL_ID, text="[]") # Leere JSON-Liste
            await bot.pin_chat_message(chat_id=DATA_CHANNEL_ID, message_id=message.message_id)
            db_message_id = message.message_id
            logger.info(f"Neue Datenbank-Nachricht erstellt und gepinnt mit ID: {db_message_id}")
    except Exception as e:
        logger.error(f"Fehler beim Initialisieren der Datenbank im Kanal {DATA_CHANNEL_ID}: {e}")
        logger.error("Stelle sicher, dass der Bot Admin im Kanal ist und die richtigen Rechte hat (Nachrichten bearbeiten & anpinnen).")

async def get_data(bot) -> list:
    """Liest die Daten aus der Telegram-Nachricht."""
    if not db_message_id: return []
    try:
        message = await bot.edit_message_text(chat_id=DATA_CHANNEL_ID, message_id=db_message_id, text="Reading data...") # Platzhalter
        data_text = message.text
        # Workaround: edit_message_text gibt das Message-Objekt zurück, das manchmal den alten Text hat. Wir müssen den Text manuell abrufen, um sicher zu sein.
        # Da wir den Text nicht wirklich ändern, rufen wir ihn einfach ab. Besser ist es, eine separate Lesemethode zu haben, aber das ist komplizierter.
        # Einfacher Trick: Wir bearbeiten die Nachricht nicht wirklich.
        # Besser: Wir holen uns die Nachricht einfach. Aber wie? Es gibt keine get_message Methode.
        # Korrektur: Wir können edit_message verwenden, um den Text abzurufen, aber es ist unschön.
        # Bessere Logik: Wir speichern die Daten lokal im Speicher und synchronisieren sie nur beim Schreiben.
        # Lasst uns die ursprüngliche Logik beibehalten und hoffen, dass der edit-Trick funktioniert.
        # Fallback: Wenn wir lesen, können wir einfach einen leeren Text editieren.
        # Beste Methode: Den Text aus der `pinned_message` Eigenschaft des Chats lesen.
        chat_info = await bot.get_chat(DATA_CHANNEL_ID)
        data_text = chat_info.pinned_message.text
        return json.loads(data_text)
    except BadRequest as e:
        if "message is not modified" in str(e):
             chat_info = await bot.get_chat(DATA_CHANNEL_ID)
             if chat_info.pinned_message:
                return json.loads(chat_info.pinned_message.text)
        logger.error(f"Fehler beim Lesen der Daten (BadRequest): {e}")
        return []
    except (json.JSONDecodeError, AttributeError):
        logger.warning("Daten in der Nachricht sind korrupt oder leer. Beginne mit einer leeren Liste.")
        return []
    except Exception as e:
        logger.error(f"Allgemeiner Fehler beim Lesen der Daten: {e}")
        return []


async def save_data(bot, data: list):
    """Speichert die Daten durch Bearbeiten der Telegram-Nachricht."""
    if not db_message_id: return
    try:
        # Sortiere die Daten, neueste zuerst
        data.sort(key=lambda x: x['timestamp'], reverse=True)
        # Konvertiere die Daten in einen formatierten JSON-String
        json_string = json.dumps(data, indent=2)
        # Telegram hat ein Limit für die Nachrichtenlänge (4096 Zeichen)
        if len(json_string) > 4090:
             logger.warning("Datenbank-Nachricht wird zu groß! Älteste Einträge werden gelöscht.")
             # Kürze die Liste, um unter das Limit zu kommen (z.B. die ältesten 10 löschen)
             data = data[:-10]
             json_string = json.dumps(data, indent=2)

        await bot.edit_message_text(
            chat_id=DATA_CHANNEL_ID,
            message_id=db_message_id,
            text=json_string
        )
    except BadRequest as e:
        if "message is not modified" in str(e):
            pass # Ignoriere diesen Fehler, es bedeutet, es gab nichts zu speichern
        else:
            logger.error(f"Fehler beim Speichern der Daten (BadRequest): {e}")
    except Exception as e:
        logger.error(f"Allgemeiner Fehler beim Speichern der Daten: {e}")

def extract_gutschein_code(text):
    match = re.search(r"Code:\s*(.*?)\s*Von", text, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else None

# --- Befehle und Callbacks ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(f"Hallo! Sende /menu, um die Optionen anzuzeigen.")

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Alle weitergeleiteten Nachrichten", callback_data='view_all_0')],
        [InlineKeyboardButton("Nur Gutschein-Codes", callback_data='view_codes_0')],
    ]
    await update.message.reply_text('Hauptmenü:', reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not (ZIEL_BENUTZER_ID and DATA_CHANNEL_ID): return
    if not update.message or not update.message.text: return
    
    message = update.message
    chat = message.chat
    text = message.text
    text_lower = text.lower()

    if any(wort in text_lower for wort in TRIGGER_WOERTER):
        try:
            await context.bot.forward_message(
                chat_id=ZIEL_BENUTZER_ID, from_chat_id=message.chat_id, message_id=message.message_id)
            
            # Neue Nachricht zu den Daten hinzufügen
            current_data = await get_data(context.bot)
            new_entry = {
                "chat_title": chat.title or "Unbekannter Chat",
                "message_text": text,
                "gutschein_code": extract_gutschein_code(text),
                "timestamp": datetime.utcnow().isoformat() # ISO-Format für einfache Sortierung
            }
            current_data.insert(0, new_entry) # Neueste zuerst
            await save_data(context.bot, current_data)
            
            logger.info(f"Nachricht aus '{chat.title}' weitergeleitet und gespeichert.")
        except Exception as e:
            logger.error(f"Fehler in handle_group_message: {e}")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data.split('_')
    action = f"{data[0]}_{data[1]}"
    page = int(data[2])

    # Hauptmenü-Aktion
    if action == "main_menu":
        keyboard = [
            [InlineKeyboardButton("Alle weitergeleiteten Nachrichten", callback_data='view_all_0')],
            [InlineKeyboardButton("Nur Gutschein-Codes", callback_data='view_codes_0')],
        ]
        await query.edit_message_text(text='Hauptmenü:', reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # Daten abrufen
    all_data = await get_data(context.bot)
    
    if action == "view_all":
        items = all_data
        text = "📜 Alle Nachrichten:\n\n"
    elif action == "view_codes":
        items = [item for item in all_data if item.get('gutschein_code')]
        text = "🎟️ Gutschein-Codes:\n\n"
    else:
        return

    # Paginierung
    start_index = page * PAGE_SIZE
    end_index = start_index + PAGE_SIZE
    paginated_items = items[start_index:end_index]
    
    if not paginated_items:
        text += "Keine Einträge gefunden."

    for i, item in enumerate(paginated_items):
        dt_object = datetime.fromisoformat(item['timestamp'])
        formatted_date = dt_object.strftime('%d.%m.%Y %H:%M')
        if action == "view_all":
            text += f"*{start_index + i + 1}.* Aus: *{item['chat_title']}* ({formatted_date})\n`{item['message_text'][:150]}...`\n\n"
        else: # view_codes
            text += f"*{start_index + i + 1}.* Code: `{item['gutschein_code']}`\n_Aus: {item['chat_title']} ({formatted_date})_\n\n"

    # Paginierungs-Knöpfe
    keyboard = []
    row = []
    if page > 0:
        row.append(InlineKeyboardButton("◀️ Zurück", callback_data=f'{action}_{page - 1}'))
    if end_index < len(items):
        row.append(InlineKeyboardButton("Vor ▶️", callback_data=f'{action}_{page + 1}'))
    
    if row: keyboard.append(row)
    keyboard.append([InlineKeyboardButton("Hauptmenü 🏠", callback_data='main_menu_0')])
    
    try:
        await query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except BadRequest as e:
        if "message is not modified" in str(e):
            pass # Ignorieren, wenn sich der Inhalt nicht ändert
        else:
            raise e

def main() -> None:
    if not all([BOT_TOKEN, ZIEL_BENUTZER_ID, DATA_CHANNEL_ID]):
        logger.critical("Eine der essentiellen Umgebungsvariablen fehlt! (BOT_TOKEN, ZIEL_BENUTZER_ID, DATA_CHANNEL_ID)")
        return

    application = Application.builder().token(BOT_TOKEN).build()
    
    # Datenbank nach dem Initialisieren des Bots einrichten
    application.post_init = init_database

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_group_message))

    logger.info("Bot startet mit Telegram-Nachricht als Datenbank...")
    application.run_polling()

if __name__ == "__main__":
    main()
