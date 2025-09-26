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

# --- 1. Stabile Konfiguration ---
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    BOT_TOKEN = os.environ["BOT_TOKEN"]
    ZIEL_BENUTZER_ID = int(os.environ["ZIEL_BENUTZER_ID"])
    DATA_CHANNEL_ID = int(os.environ["DATA_CHANNEL_ID"])
    TRIGGER_WOERTER_STR = os.environ.get("TRIGGER_WOERTER", "")
    TRIGGER_WOERTER = [word.strip().lower() for word in TRIGGER_WOERTER_STR.split(',') if word.strip()]
except (KeyError, ValueError) as e:
    logger.critical(f"FATALER FEHLER: Umgebungsvariable fehlt/falsch: {e}. Bot stoppt.")
    exit()

# --- 2. Webserver für Render ---
app = Flask(__name__)
@app.route('/')
def home(): return "Bot is running."
def run_flask(): app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))

# --- 3. Telegram-Nachrichten-Datenbank ---
db_message_id = None
PAGE_SIZE = 5

async def init_database(application: Application):
    global db_message_id
    bot = application.bot
    try:
        chat_info = await bot.get_chat(DATA_CHANNEL_ID)
        if chat_info.pinned_message:
            db_message_id = chat_info.pinned_message.message_id
            # Überprüfe, ob die Struktur der DB korrekt ist
            try:
                data = json.loads(chat_info.pinned_message.text)
                if "messages" not in data or "groups" not in data:
                    raise ValueError("Incomplete DB structure")
            except (json.JSONDecodeError, ValueError):
                logger.warning("DB-Struktur veraltet/korrupt. Setze zurück.")
                await bot.edit_message_text(chat_id=DATA_CHANNEL_ID, message_id=db_message_id, text=json.dumps({"messages": [], "groups": {}}))
            logger.info(f"Datenbank-Nachricht gefunden: {db_message_id}")
        else:
            logger.warning("Keine DB-Nachricht. Erstelle neue.")
            new_db = json.dumps({"messages": [], "groups": {}})
            message = await bot.send_message(chat_id=DATA_CHANNEL_ID, text=new_db)
            await bot.pin_chat_message(chat_id=DATA_CHANNEL_ID, message_id=message.message_id, disable_notification=True)
            db_message_id = message.message_id
    except Exception as e:
        logger.error(f"Fehler bei DB-Initialisierung: {e}")

async def get_data(bot) -> dict:
    if not db_message_id: return {"messages": [], "groups": {}}
    try:
        chat_info = await bot.get_chat(DATA_CHANNEL_ID)
        return json.loads(chat_info.pinned_message.text)
    except Exception: return {"messages": [], "groups": {}}

async def save_data(bot, data: dict):
    if not db_message_id: return
    try:
        data["messages"].sort(key=lambda x: x['timestamp'], reverse=True)
        data["messages"] = data["messages"][:200]
        await bot.edit_message_text(chat_id=DATA_CHANNEL_ID, message_id=db_message_id, text=json.dumps(data, indent=2))
    except BadRequest as e:
        if "message is not modified" not in str(e): logger.error(f"Fehler beim Speichern: {e}")
    except Exception as e: logger.error(f"Allg. Fehler beim Speichern: {e}")

# --- 4. Bot-Handler und Funktionen ---

# /start öffnet jetzt das Menü
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: await update.message.delete()
    except: pass
    
    data = await get_data(context.bot)
    known_groups = data.get("groups", {})
    
    keyboard = [
        [InlineKeyboardButton("Gespeicherte Nachrichten", callback_data='view_all_0')],
        [InlineKeyboardButton("Gutschein-Codes", callback_data='view_codes_0')],
    ]
    if known_groups:
        keyboard.append([InlineKeyboardButton("--- Live-Überwachung ---", callback_data='noop')])
        for group_id, group_name in known_groups.items():
            keyboard.append([InlineKeyboardButton(f"➡️ {group_name}", callback_data=f'monitor_start_{group_id}')])
    
    menu_message = await update.effective_chat.send_text('Hauptmenü:', reply_markup=InlineKeyboardMarkup(keyboard))
    context.user_data['menu_message_id'] = menu_message.message_id

# Handler für alle Nachrichten in Gruppen
async def group_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return

    # A) Live-Monitoring-Logik
    monitoring_chat_id = context.user_data.get('monitoring_chat_id')
    if monitoring_chat_id and str(update.message.chat_id) == monitoring_chat_id:
        try:
            timestamp = update.message.date.strftime('%H:%M:%S')
            info_msg = await context.bot.send_message(ZIEL_BENUTZER_ID, f"_{timestamp}_", parse_mode='Markdown')
            fwd_msg = await context.bot.forward_message(ZIEL_BENUTZER_ID, update.message.chat_id, update.message.message_id)
            if 'forwarded_messages' not in context.user_data: context.user_data['forwarded_messages'] = []
            context.user_data['forwarded_messages'].extend([info_msg.message_id, fwd_msg.message_id])
        except Exception as e: logger.error(f"Fehler im Live-Monitoring: {e}")

    # B) Keyword-Speicher-Logik (läuft immer im Hintergrund)
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
        except Exception as e: logger.error(f"Fehler beim Speichern der Keyword-Nachricht: {e}")

# Bot lernt neue Gruppen
async def new_group_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.bot.id in [m.id for m in update.message.new_chat_members]:
        chat = update.message.chat
        data = await get_data(context.bot)
        if "groups" not in data: data["groups"] = {}
        data["groups"][str(chat.id)] = chat.title
        await save_data(context.bot, data)
        await context.bot.send_message(ZIEL_BENUTZER_ID, f"Ich wurde zur Gruppe '{chat.title}' hinzugefügt.")

# Logik für alle Knopf-Klicks
async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Menü aufräumen
    if 'menu_message_id' in context.user_data:
        try: await context.bot.delete_message(query.effective_chat.id, context.user_data['menu_message_id'])
        except: pass
        del context.user_data['menu_message_id']
    
    action, _, payload = query.data.partition('_')

    if action == "monitor":
        sub_action, _, chat_id = payload.partition('_')
        if sub_action == "start":
            context.user_data['monitoring_chat_id'] = chat_id
            context.user_data['forwarded_messages'] = []
            
            data = await get_data(context.bot)
            group_name = data.get("groups", {}).get(chat_id, "Unbekannt")

            stop_button = InlineKeyboardMarkup([[InlineKeyboardButton("⏹️ Beenden & Aufräumen", callback_data='stop_monitoring_0')]])
            msg = await query.effective_chat.send_text(f"✅ Live-Überwachung für '{group_name}' gestartet.", reply_markup=stop_button)
            context.user_data['control_message_id'] = msg.message_id
        
    elif action == "stop": # monitor_stop oder view_stop
        for key in ['forwarded_messages', 'control_message_id']:
            if key in context.user_data:
                msg_ids = context.user_data[key] if isinstance(context.user_data[key], list) else [context.user_data[key]]
                for msg_id in msg_ids:
                    try: await context.bot.delete_message(query.effective_chat.id, msg_id)
                    except: pass
        context.user_data.clear()
        await query.effective_chat.send_text("Aktion beendet und Chat aufgeräumt. Sende /start für ein neues Menü.")

    elif action == "view":
        sub_action, _, page_str = payload.partition('_')
        page = int(page_str)
        items = (await get_data(context.bot)).get("messages", [])
        
        text, item_source = "", items
        if sub_action == "all": text = "📜 Gespeicherte Nachrichten:\n\n"
        elif sub_action == "codes": 
            text = "🎟️ Gespeicherte Gutschein-Codes:\n\n"
            item_source = [item for item in items if item.get('gutschein_code')]

        paginated_items = item_source[page*PAGE_SIZE : (page+1)*PAGE_SIZE]
        if not paginated_items: text += "Keine Einträge gefunden."

        for i, item in enumerate(paginated_items):
            dt = datetime.fromisoformat(item['timestamp']).strftime('%d.%m %H:%M')
            if sub_action == "all": text += f"*{page*PAGE_SIZE+i+1}.* Aus *{item['chat_title']}* ({dt})\n`{item['message_text'][:100]}...`\n\n"
            else: text += f"*{page*PAGE_SIZE+i+1}.* Code: `{item['gutschein_code']}`\n_Aus {item['chat_title']} ({dt})_\n\n"

        nav_row = []
        if page > 0: nav_row.append(InlineKeyboardButton("◀️", callback_data=f'view_{sub_action}_{page-1}'))
        if (page+1)*PAGE_SIZE < len(item_source): nav_row.append(InlineKeyboardButton("▶️", callback_data=f'view_{sub_action}_{page+1}'))
        
        keyboard = [nav_row] if nav_row else []
        keyboard.append([InlineKeyboardButton("🏠 Schließen & Aufräumen", callback_data='stop_viewing_0')])
        
        msg = await query.effective_chat.send_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        context.user_data['control_message_id'] = msg.message_id

# --- 5. Hauptprogramm ---
def main() -> None:
    Thread(target=run_flask, daemon=True).start()
    logger.info("Flask-Webserver gestartet.")

    application = Application.builder().token(BOT_TOKEN).build()
    application.post_init = init_database

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(button_callback_handler))
    # Ein Handler für alle relevanten Nachrichten in Gruppen
    application.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, group_message_handler))
    application.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.StatusUpdate.NEW_CHAT_MEMBERS, new_group_handler))

    logger.info("Telegram Bot startet Polling...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
