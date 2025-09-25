import logging
import os
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from threading import Thread # Nötig für den parallelen Webserver
from flask import Flask     # Der Webserver selbst

# --- Logging und Konfiguration ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
TRIGGER_WOERTER_STR = os.environ.get("TRIGGER_WOERTER", "")
TRIGGER_WOERTER = [word.strip().lower() for word in TRIGGER_WOERTER_STR.split(',') if word.strip()]
ZIEL_BENUTZER_ID = None
try:
    ZIEL_BENUTZER_ID = int(os.environ.get("ZIEL_BENUTZER_ID"))
except (ValueError, TypeError):
    logging.warning("ZIEL_BENUTZER_ID ist nicht oder falsch gesetzt. Keyword-Weiterleitung ist deaktiviert.")

if not BOT_TOKEN:
    logging.critical("FEHLER: BOT_TOKEN fehlt. Der Bot kann nicht starten.")
    exit()


# --- Der kleine Flask-Webserver, um Render zufrieden zu stellen ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive."

def run_flask():
    # Render gibt den Port in der 'PORT' Umgebungsvariable vor.
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)


# --- Bot-Funktionen (unverändert) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat_id = user.id
    await update.message.reply_html(
        f"Hallo {user.mention_html()}! Deine Chat-ID ist: <code>{chat_id}</code>"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not ZIEL_BENUTZER_ID: return
    if not update.message or not update.message.text: return
    
    message = update.message
    chat = message.chat
    text_lower = message.text.lower()

    for wort in TRIGGER_WOERTER:
        if wort in text_lower:
            try:
                info_text = f"🔑 Schlüsselwort '{wort}' gefunden!\n\n👥 **Aus Gruppe:** {chat.title or 'Unbekannt'}"
                await context.bot.send_message(chat_id=ZIEL_BENUTZER_ID, text=info_text, parse_mode='Markdown')
                await context.bot.forward_message(chat_id=ZIEL_BENUTZER_ID, from_chat_id=message.chat_id, message_id=message.message_id)
                logger.info(f"Nachricht aus '{chat.title}' an {ZIEL_BENUTZER_ID} weitergeleitet.")
                break
            except Exception as e:
                logger.error(f"Fehler beim Weiterleiten: {e}")


def main() -> None:
    # Starte den Webserver in einem separaten, parallelen Prozess
    flask_thread = Thread(target=run_flask)
    flask_thread.start()

    # Starte den Telegram Bot
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log_message = f"Bot startet... Überwacht auf {len(TRIGGER_WOERTER)} Keywords."
    if ZIEL_BENUTZER_ID:
        log_message += f" Leitet an Benutzer-ID {ZIEL_BENUTZER_ID} weiter."
    else:
        log_message += " Weiterleitung ist DEAKTIVIERT."
    logger.info(log_message)
    
    application.run_polling()

if __name__ == "__main__":
    main()
