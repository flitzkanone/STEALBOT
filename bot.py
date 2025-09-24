import logging
import os
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# --- KONFIGURATION WIRD AUS UMGEBUNGSVARIABLEN GELESEN ---

BOT_TOKEN = os.environ.get("BOT_TOKEN")
TRIGGER_WOERTER_STR = os.environ.get("TRIGGER_WOERTER", "")
TRIGGER_WOERTER = [word.strip().lower() for word in TRIGGER_WOERTER_STR.split(',') if word.strip()]

ZIEL_GRUPPEN_IDS_STR = os.environ.get("ZIEL_GRUPPEN_IDS", "")
ZIEL_GRUPPEN_IDS = []
if ZIEL_GRUPPEN_IDS_STR:
    try:
        ZIEL_GRUPPEN_IDS = [int(gid.strip()) for gid in ZIEL_GRUPPEN_IDS_STR.split(',') if gid.strip()]
    except ValueError:
        logging.critical("FEHLER: ZIEL_GRUPPEN_IDS enthält ungültige Zeichen.")
        exit()

if not BOT_TOKEN or not TRIGGER_WOERTER or not ZIEL_GRUPPEN_IDS:
    logging.critical("FEHLER: Eine der Umgebungsvariablen (BOT_TOKEN, TRIGGER_WOERTER, ZIEL_GRUPPEN_IDS) fehlt. Der Bot kann nicht starten.")
    exit()

# Logging einrichten
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    message = update.message
    chat = message.chat
    text_lower = message.text.lower()

    # Überprüfe, ob eines der Trigger-Wörter in der Nachricht vorkommt
    for wort in TRIGGER_WOERTER:
        if wort in text_lower:
            logger.info(f"Schlüsselwort '{wort}' in Gruppe '{chat.title}' gefunden. Leite Nachricht an {len(ZIEL_GRUPPEN_IDS)} Gruppen weiter...")
            
            # Schleife durch alle Ziel-Gruppen
            for gruppen_id in ZIEL_GRUPPEN_IDS:
                try:
                    # HIER IST DIE ÄNDERUNG: Nur noch die Originalnachricht weiterleiten
                    await context.bot.forward_message(
                        chat_id=gruppen_id,
                        from_chat_id=message.chat_id,
                        message_id=message.message_id
                    )
                    logger.info(f"-> Erfolgreich an Ziel-Gruppe {gruppen_id} weitergeleitet.")
                except Exception as e:
                    # Loggt einen Fehler, falls das Weiterleiten an eine spezifische Gruppe fehlschlägt
                    logger.error(f"Fehler beim Weiterleiten an Gruppe {gruppen_id}: {e}")
            
            # Beende die Keyword-Suche nach dem ersten Treffer, um Doppel-Weiterleitungen zu vermeiden
            break

def main() -> None:
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info(f"Bot startet... Überwacht auf {len(TRIGGER_WOERTER)} Keywords. Leitet an {len(ZIEL_GRUPPEN_IDS)} Gruppen weiter.")
    application.run_polling()

if __name__ == "__main__":
    main()
