import logging
import os
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- KONFIGURATION WIRD AUS UMGEBUNGSVARIABLEN GELESEN ---

BOT_TOKEN = os.environ.get("BOT_TOKEN")
TRIGGER_WOERTER_STR = os.environ.get("TRIGGER_WOERTER", "")
TRIGGER_WOERTER = [word.strip().lower() for word in TRIGGER_WOERTER_STR.split(',') if word.strip()]

# NEU: Einzelne Ziel-Benutzer-ID einlesen
ZIEL_BENUTZER_ID = None
try:
    ZIEL_BENUTZER_ID = int(os.environ.get("ZIEL_BENUTZER_ID"))
except (ValueError, TypeError):
    logging.warning("ZIEL_BENUTZER_ID ist nicht oder falsch gesetzt. Keyword-Weiterleitung ist deaktiviert.")

# Überprüfung, ob die Basis-Variablen gesetzt sind
if not BOT_TOKEN or not TRIGGER_WOERTER:
    logging.critical("FEHLER: BOT_TOKEN oder TRIGGER_WOERTER fehlt. Der Bot kann nicht starten.")
    exit()

# Logging einrichten
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


# NEU: /start-Befehl, um die Chat-ID herauszufinden
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat_id = user.id
    await update.message.reply_html(
        f"Hallo {user.mention_html()}!\n\n"
        f"Ich bin der Keyword-Bot. Deine persönliche Chat-ID lautet:\n"
        f"<code>{chat_id}</code>\n\n"
        f"Bitte gib diese ID im Render-Dashboard bei der Variable `ZIEL_BENUTZER_ID` an."
    )

# Diese Funktion verarbeitet Nachrichten aus den Gruppen
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Funktion wird nur ausgeführt, wenn eine Ziel-ID konfiguriert ist
    if not ZIEL_BENUTZER_ID:
        return

    if not update.message or not update.message.text:
        return

    message = update.message
    chat = message.chat
    text_lower = message.text.lower()

    for wort in TRIGGER_WOERTER:
        if wort in text_lower:
            try:
                # Info-Text erstellen, damit Anna weiß, woher die Nachricht kommt
                info_text = (
                    f"🔑 Schlüsselwort '{wort}' gefunden!\n\n"
                    f"👥 **Aus Gruppe:** {chat.title or 'Unbekannt'}"
                )
                
                # Zuerst den Info-Text an Anna senden
                await context.bot.send_message(chat_id=ZIEL_BENUTZER_ID, text=info_text, parse_mode='Markdown')
                
                # Dann die Originalnachricht an Anna weiterleiten
                await context.bot.forward_message(
                    chat_id=ZIEL_BENUTZER_ID,
                    from_chat_id=message.chat_id,
                    message_id=message.message_id
                )
                
                logger.info(f"Nachricht aus Gruppe '{chat.title}' an Benutzer {ZIEL_BENUTZER_ID} weitergeleitet.")
                break
                
            except Exception as e:
                logger.error(f"Fehler beim Weiterleiten an Benutzer {ZIEL_BENUTZER_ID}: {e}")

def main() -> None:
    application = Application.builder().token(BOT_TOKEN).build()

    # NEU: Den /start-Befehl registrieren
    application.add_handler(CommandHandler("start", start))

    # Handler für Nachrichten in Gruppen
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log_message = f"Bot startet... Überwacht auf {len(TRIGGER_WOERTER)} Keywords."
    if ZIEL_BENUTZER_ID:
        log_message += f" Leitet an Benutzer-ID {ZIEL_BENUTZER_ID} weiter."
    logger.info(log_message)
    
    application.run_polling()

if __name__ == "__main__":
    main()
