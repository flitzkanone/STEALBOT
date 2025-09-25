import logging
import os
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from threading import Thread # NEU: Importieren von Thread
from flask import Flask     # NEU: Importieren von Flask

# --- Logging und Konfiguration wie gehabt ---
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

if not BOT_TOKEN or not TRIGGER_WOERTER:
    logging.critical("FEHLER: BOT_TOKEN oder TRIGGER_WOERTER fehlt. Der Bot kann nicht starten.")
    exit()


# --- NEU: Der kleine Flask-Webserver ---
app = Flask('')

@app.route('/')
def home():
    # Diese Nachricht sieht niemand, sie ist nur da, damit der Server etwas tut.
    return "Bot is alive and listening."

def run_flask():
    # Render stellt den Port in der PORT-Umgebungsvariable bereit.
    # Wir benutzen '0.0.0.0', damit der Server von außerhalb des Containers erreichbar ist.
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
# --- Ende des neuen Webserver-Teils ---


# --- Deine Bot-Funktionen bleiben unverändert ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat_id = user.id
    await update.message.reply_html(
        f"Hallo {user.mention_html()}!\n\n"
        f"Deine persönliche Chat-ID lautet:\n"
        f"<code>{chat_id}</code>\n\n"
        f"Trage diese ID in Render als `ZIEL_BENUTZER_ID` ein."
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
                logger.info(f"Nachricht aus Gruppe '{chat.title}' an Benutzer {ZIEL_BENUTZER_ID} weitergeleitet.")
                break
            except Exception as e:
                logger.error(f"Fehler beim Weiterleiten an Benutzer {ZIEL_BENUTZER_ID}: {e}")


def main() -> None:
    # NEU: Starte den Flask-Server in einem eigenen Thread
    flask_thread = Thread(target=run_flask)
    flask_thread.start()

    # Dein Bot startet wie gewohnt
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
