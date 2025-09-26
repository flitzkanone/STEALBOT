# bot.py
import logging
import os
import json
import re
from datetime import datetime
from threading import Thread
from flask import Flask

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

# --- Flask Webserver ---
app = Flask('')
@app.route('/')
def home(): return "Bot is alive."
def run_flask(): app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))

# --- Daten-Management via Telegram ---
# Die Datenstruktur ist jetzt ein Dictionary: {"messages": [], "groups": {}}
async def init_database(application: Application):
    global db_message_id
    if not DATA_CHANNEL_ID: return
    try:
        chat_info = await application.bot.get_chat(DATA_CHANNEL_ID)
        if chat_info.pinned_message:
            db_message_id = chat_info.pinned_message.message_id
            logger.info(f"Datenbank-Nachricht gefunden: {db_message_id}")
            # Stelle sicher, dass die DB-Struktur korrekt ist
            data = await get_data(application.bot)
            if "messages" not in data or "groups" not in data:
                logger.warning("DB-Struktur veraltet. Setze zurück.")
                await save_data(application.bot, {"messages": [], "groups": {}})
        else:
            logger.warning("Keine DB-Nachricht gefunden. Erstelle neue.")
            new_db_content = json.dumps({"messages": [], "groups": {}}, indent=2)
            message = await application.bot.send_message(chat_id=DATA_CHANNEL_ID, text=new_db_content)
            await application.bot.pin_chat_message(chat_id=DATA_CHANNEL_ID, message_id=message.message_id, disable_notification=True)
            db_message_id = message.message_id
    except Exception as e:
        logger.error(f"Fehler bei DB-Initialisierung: {e}")

async def get_data(bot) -> dict:
    if not db_message_id: return {"messages": [], "groups": {}}
    try:
        chat_info = await bot.get_chat(DATA_CHANNEL_ID)
        return json.loads(chat_info.pinned_message.text)
    except Exception:
        return {"messages": [], "groups": {}}

async def save_data(bot, data: dict):
    if not db_message_id: return
    try:
        # Sortiere Nachrichten, beschränke auf die neuesten 200
        data["messages"].sort(key=lambda x: x['timestamp'], reverse=True)
        data["messages"] = data["messages"][:200]
        json_string = json.dumps(data, indent=2)
        await bot.edit_message_text(chat_id=DATA_CHANNEL_ID, message_id=db_message_id, text=json_string)
    except BadRequest as e:
        if "message is not modified" not in str(e):
            logger.error(f"Fehler beim Speichern: {e}")

# --- Hauptlogik ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Der neue /start Befehl, der das Menü öffnet und den Chat aufräumt."""
    # Chat aufräumen: Löscht die /start Nachricht
    try:
        await update.message.delete()
    except Exception:
        pass # Ignoriere, wenn das Löschen fehlschlägt

    data = await get_data(context.bot)
    known_groups = data.get("groups", {})
    
    keyboard = [
        [InlineKeyboardButton("Alle gespeicherten Nachrichten", callback_data='view_all_0')],
        [InlineKeyboardButton("Nur Gutschein-Codes", callback_data='view_codes_0')],
    ]
    
    if known_groups:
        keyboard.append([InlineKeyboardButton("--- Live-Überwachung starten ---", callback_data='noop')])
        for group_id, group_name in known_groups.items():
            keyboard.append([InlineKeyboardButton(f"➡️ {group_name}", callback_data=f'monitor_start_{group_id}')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    menu_message = await update.effective_chat.send_text('Hauptmenü:', reply_markup=reply_markup)
    
    # Speichere die ID der Menü-Nachricht, um sie später zu löschen
    context.user_data['menu_message_id'] = menu_message.message_id

async def handle_keyword_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Speichert Nachrichten mit Keywords im Hintergrund."""
    if not (ZIEL_BENUTZER_ID and DATA_CHANNEL_ID): return
    if not update.message or not update.message.text: return
    
    if any(wort in update.message.text.lower() for wort in TRIGGER_WOERTER):
        try:
            data = await get_data(context.bot)
            text = update.message.text
            new_entry = {
                "chat_title": update.message.chat.title or "Unbekannt", 
                "message_text": text, 
                "gutschein_code": re.search(r"Code:\s*(.*?)\s*Von", text, re.I|re.S).group(1).strip() if re.search(r"Code:", text, re.I) else None,
                "timestamp": datetime.utcnow().isoformat()
            }
            data["messages"].insert(0, new_entry)
            await save_data(context.bot, data)
            logger.info(f"Keyword-Nachricht aus '{update.message.chat.title}' gespeichert.")
        except Exception as e:
            logger.error(f"Fehler in handle_keyword_message: {e}")

async def handle_monitoring_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Leitet ALLE Nachrichten weiter, wenn der Live-Modus für diesen Chat aktiv ist."""
    monitoring_chat_id = context.user_data.get('monitoring_chat_id')
    if monitoring_chat_id and str(update.message.chat_id) == monitoring_chat_id:
        try:
            # Füge einen Zeitstempel hinzu
            timestamp = update.message.date.strftime('%H:%M:%S')
            info_msg = await context.bot.send_message(
                chat_id=ZIEL_BENUTZER_ID,
                text=f"_{timestamp}_",
                parse_mode='Markdown'
            )
            
            fwd_msg = await context.bot.forward_message(
                chat_id=ZIEL_BENUTZER_ID,
                from_chat_id=update.message.chat_id,
                message_id=update.message.message_id
            )
            # Speichere die IDs der weitergeleiteten Nachrichten zum späteren Löschen
            if 'forwarded_messages' not in context.user_data:
                context.user_data['forwarded_messages'] = []
            context.user_data['forwarded_messages'].extend([info_msg.message_id, fwd_msg.message_id])
        except Exception as e:
            logger.error(f"Fehler im Live-Monitoring: {e}")

async def handle_group_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lernt neue Gruppen, wenn der Bot hinzugefügt wird."""
    if context.bot.id in [m.id for m in update.message.new_chat_members]:
        chat = update.message.chat
        logger.info(f"Bot wurde zur Gruppe '{chat.title}' ({chat.id}) hinzugefügt.")
        data = await get_data(context.bot)
        data["groups"][str(chat.id)] = chat.title
        await save_data(context.bot, data)
        await context.bot.send_message(ZIEL_BENUTZER_ID, f"Ich wurde zur Gruppe '{chat.title}' hinzugefügt und kann sie jetzt überwachen.")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verarbeitet alle Knopf-Klicks."""
    query = update.callback_query
    await query.answer()

    # Menü-Nachricht löschen, um den Chat sauber zu halten
    menu_message_id = context.user_data.get('menu_message_id')
    if menu_message_id:
        try:
            await context.bot.delete_message(chat_id=query.effective_chat.id, message_id=menu_message_id)
        except Exception: pass

    data_parts = query.data.split('_')
    action = data_parts[0]
    
    if action == "monitor":
        sub_action = data_parts[1]
        if sub_action == "start":
            chat_id_to_monitor = data_parts[2]
            context.user_data['monitoring_chat_id'] = chat_id_to_monitor
            context.user_data['forwarded_messages'] = [] # Reset list for new session
            
            data = await get_data(context.bot)
            group_name = data.get("groups", {}).get(chat_id_to_monitor, "Unbekannt")

            stop_button = InlineKeyboardMarkup([[InlineKeyboardButton("⏹️ Überwachung beenden & aufräumen", callback_data='monitor_stop_0')]])
            control_message = await query.effective_chat.send_text(
                f"✅ Live-Überwachung für '{group_name}' gestartet.\nAlle neuen Nachrichten werden jetzt hier angezeigt.",
                reply_markup=stop_button
            )
            # Speichere die ID der Kontroll-Nachricht, damit wir sie auch löschen können
            context.user_data['control_message_id'] = control_message.message_id

        elif sub_action == "stop":
            # 1. Lösche alle weitergeleiteten Nachrichten
            forwarded_ids = context.user_data.get('forwarded_messages', [])
            for msg_id in forwarded_ids:
                try:
                    await context.bot.delete_message(chat_id=query.effective_chat.id, message_id=msg_id)
                except Exception: pass
            
            # 2. Lösche die "Überwachung beenden"-Nachricht
            control_message_id = context.user_data.get('control_message_id')
            if control_message_id:
                try:
                    await context.bot.delete_message(chat_id=query.effective_chat.id, message_id=control_message_id)
                except Exception: pass

            # 3. Setze den Status zurück
            context.user_data.clear()
            await query.effective_chat.send_text("Überwachung beendet und Chat aufgeräumt. Sende /start für ein neues Menü.")

    elif action == "view": # Logik für "Alle Nachrichten" und "Codes"
        page = int(data_parts[2])
        all_data = (await get_data(context.bot)).get("messages", [])
        
        sub_action = data_parts[1]
        if sub_action == "all":
            items = all_data
            text = "📜 Alle gespeicherten Nachrichten:\n\n"
        else: # "codes"
            items = [item for item in all_data if item.get('gutschein_code')]
            text = "🎟️ Gespeicherte Gutschein-Codes:\n\n"

        start_index = page * PAGE_SIZE
        paginated_items = items[start_index : start_index + PAGE_SIZE]
        if not paginated_items: text += "Keine Einträge gefunden."

        for i, item in enumerate(paginated_items):
            dt = datetime.fromisoformat(item['timestamp']).strftime('%d.%m %H:%M')
            if sub_action == "all":
                text += f"*{start_index+i+1}.* Aus *{item['chat_title']}* ({dt})\n`{item['message_text'][:100]}...`\n\n"
            else:
                text += f"*{start_index+i+1}.* Code: `{item['gutschein_code']}`\n_Aus {item['chat_title']} ({dt})_\n\n"
        
        # Paginierungs-Knöpfe
        keyboard_rows = []
        nav_row = []
        if page > 0: nav_row.append(InlineKeyboardButton("◀️", callback_data=f'view_{sub_action}_{page-1}'))
        if (start_index + PAGE_SIZE) < len(items): nav_row.append(InlineKeyboardButton("▶️", callback_data=f'view_{sub_action}_{page+1}'))
        if nav_row: keyboard_rows.append(nav_row)
        keyboard_rows.append([InlineKeyboardButton("🏠 Menü schließen & aufräumen", callback_data='monitor_stop_0')])
        
        menu_msg = await query.effective_chat.send_text(text, reply_markup=InlineKeyboardMarkup(keyboard_rows), parse_mode='Markdown')
        context.user_data['control_message_id'] = menu_msg.message_id # Diese Nachricht wird beim Schließen auch gelöscht

def main() -> None:
    if not all([BOT_TOKEN, ZIEL_BENUTZER_ID, DATA_CHANNEL_ID]):
        logger.critical("Essentielle Umgebungsvariablen fehlen!")
        return

    # Webserver starten
    Thread(target=run_flask, daemon=True).start()

    application = Application.builder().token(BOT_TOKEN).build()
    application.post_init = init_database

    # Handler registrieren
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Nachrichtenhändler in Gruppen: Wichtig, sie in der gleichen Gruppe zu haben
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_monitoring_message), group=1)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_keyword_message), group=1)
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_group_join), group=2)

    logger.info("Bot startet im erweiterten Modus...")
    application.run_polling(drop_pending_updates=True) # Verwirft alte Nachrichten bei Neustart

if __name__ == "__main__":
    main()
