import logging
import os
from threading import Thread
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- 1. Grundlegende Konfiguration ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- 2. Umgebungsvariablen sicher einlesen ---
try:
    BOT_TOKEN = os.environ["BOT_TOKEN"]
    ZIEL_BENUTZER_ID = int(os.environ["ZIEL_BENUTZER_ID"])
    # Trigger-Wörter einlesen und in eine saubere Liste umwandeln
    TRIGGER_WOERTER_STR = os.environ.get("TRIGGER_WOERTER", "")
    TRIGGER_WOERTER = [word.strip().lower() for word in TRIGGER_WOERTER_STR.split(',') if word.strip()]
except (KeyError, ValueError) as e:
    logger.critical(f"FATALER FEHLER: Eine wichtige Umgebungsvariable fehlt oder ist falsch: {e}. Bot wird beendet.")
    exit()

if not TRIGGER_WOERTER:
    logger.warning("WARNUNG: Keine TRIGGER_WOERTER definiert. Der Bot wird keine Nachrichten weiterleiten.")


# --- 3. Webserver für Render ---
# Dieser Teil dient nur dazu, Render einen offenen Port zu zeigen, damit es keine Timeouts gibt.
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running."

def run_flask():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)


# --- 4. Bot-Funktionen ---

# Ein einfacher /start Befehl, um zu testen, ob der Bot reagiert.
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    await update.message.reply_html(
        f"Hallo! Ich bin online und bereit.\n"
        f"Ich sende alle Nachrichten mit den definierten Schlüsselwörtern an den konfigurierten Benutzer.\n\n"
        f"Deine Chat-ID ist: <code>{user_id}</code> (falls du sie für die Konfiguration brauchst)."
    )

# Die Hauptfunktion: Reagiert auf Nachrichten in Gruppen.
async def forward_on_keyword(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Ignoriere Nachrichten ohne Text
    if not update.message or not update.message.text:
        return

    message = update.message
    text_lower = message.text.lower()

    # Überprüfe, ob eines der Trigger-Wörter vorkommt
    for wort in TRIGGER_WOERTER:
        if wort in text_lower:
            try:
                # Baue eine kleine Info-Nachricht, die vor der weitergeleiteten Nachricht gesendet wird.
                info_text = f"🔑 Schlüsselwort '{wort}' in der Gruppe '{message.chat.title}' gefunden:"
                
                # Sende zuerst die Info
                await context.bot.send_message(chat_id=ZIEL_BENUTZER_ID, text=info_text)
                
                # Leite dann die Originalnachricht weiter
                await context.bot.forward_message(
                    chat_id=ZIEL_BENUTZER_ID,
                    from_chat_id=message.chat_id,
                    message_id=message.message_id
                )
                
                logger.info(f"Nachricht aus '{message.chat.title}' wegen Keyword '{wort}' weitergeleitet.")
                
                # Wichtig: Beende die Schleife nach dem ersten Treffer, um Doppel-Weiterleitungen zu vermeiden.
                break

            except Exception as e:
                logger.error(f"Fehler beim Weiterleiten: {e}")
                # Sende eine Fehlermeldung an den Admin, um das Problem zu melden
                await context.bot.send_message(
                    chat_id=ZIEL_BENUTZER_ID,
                    text=f"🚨 Fehler beim Weiterleiten einer Nachricht aus der Gruppe '{message.chat.title}':\n`{e}`",
                    parse_mode='Markdown'
                )


# --- 5. Hauptprogramm-Struktur ---
def main() -> None:
    """Startet den Webserver und den Bot."""

    # Starte den Flask-Webserver in einem separaten Thread.
    # 'daemon=True' sorgt dafür, dass der Thread beendet wird, wenn das Hauptprogramm endet.
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info("Flask-Webserver gestartet.")

    # Erstelle die Telegram Bot Application.
    application = Application.builder().token(BOT_TOKEN).build()

    # Füge die Handler hinzu.
    application.add_handler(CommandHandler("start", start))
    # Dieser Handler reagiert auf alle Textnachrichten, die keine Befehle sind.
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, forward_on_keyword))

    logger.info("Telegram Bot startet Polling...")
    # 'drop_pending_updates=True' ist wichtig: Es verwirft alte Nachrichten, die ankamen, während der Bot offline war.
    # Das verhindert, dass der Bot nach einem Neustart mit dem "Conflict"-Fehler abstürzt.
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
