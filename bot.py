import os
import logging
import re
from datetime import datetime
from threading import Thread
from flask import Flask

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, error
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

# --- Grundlegende Konfiguration und Logging ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Laden der Umgebungsvariablen ---
try:
    BOT_TOKEN = os.environ['BOT_TOKEN']
    ZIEL_BENUTZER_ID = int(os.environ['ZIEL_BENUTZER_ID'])
    DATA_CHANNEL_ID = int(os.environ['DATA_CHANNEL_ID'])
    # Trigger-Wörter werden in eine Liste von Kleinbuchstaben umgewandelt
    TRIGGER_WOERTER = [word.strip().lower() for word in os.environ['TRIGGER_WOERTER'].split(',')]
except KeyError as e:
    logger.error(f"FEHLER: Die Umgebungsvariable {e} wurde nicht gesetzt. Der Bot kann nicht starten.")
    exit()

# --- Globale Speicher für den Zustand ---
# Speichert die Gruppen, in denen der Bot ist: {chat_id: 'Gruppenname'}
known_groups = {}
# Speichert den Live-Überwachungsstatus: {user_id: target_chat_id}
live_monitoring_status = {}
# Speichert Nachrichten-IDs zum späteren Löschen: {user_id: [message_id_1, message_id_2, ...]}
cleanup_message_ids = {}

# --- Flask Web Server für Render ---
# Render benötigt einen Web-Service, der auf einem Port lauscht.
app = Flask(__name__)

@app.route('/')
def index():
    return "Bot is running"

def run_flask():
    # Starte den Flask-Server auf dem von Render vorgegebenen Port
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

# --- Hilfsfunktionen ---
async def cleanup_chat(context: ContextTypes.DEFAULT_TYPE):
    """Löscht alle für die letzte Aktion relevanten Nachrichten."""
    user_id = ZIEL_BENUTZER_ID
    if user_id in cleanup_message_ids:
        for msg_id in cleanup_message_ids[user_id]:
            try:
                await context.bot.delete_message(chat_id=user_id, message_id=msg_id)
            except error.BadRequest:
                # Nachricht wurde bereits gelöscht oder ist nicht vorhanden
                pass
        cleanup_message_ids[user_id].clear()


# --- Kernfunktionen & Command Handler ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verarbeitet den /start Befehl und zeigt das Hauptmenü an."""
    user_id = update.effective_user.id

    if user_id != ZIEL_BENUTZER_ID:
        await update.message.reply_text(f"Hallo! Deine Benutzer-ID lautet: `{user_id}`. Bitte trage diese als `ZIEL_BENUTZER_ID` in den Umgebungsvariablen ein, um den Bot zu nutzen.", parse_mode='Markdown')
        return

    # Alte Nachrichten und Menüs aufräumen
    await cleanup_chat(context)
    # Die /start Nachricht des Users ebenfalls löschen
    cleanup_message_ids.setdefault(user_id, []).append(update.message.message_id)

    keyboard = [
        [InlineKeyboardButton("Gespeicherte Nachrichten", callback_data='view_all_0')],
        [InlineKeyboardButton("Gutschein-Codes", callback_data='view_codes_0')],
    ]

    # Dynamisch Knöpfe für jede bekannte Gruppe hinzufügen
    if known_groups:
        keyboard.append([InlineKeyboardButton("--- Live-Überwachung ---", callback_data='noop')])
        for group_id, group_name in known_groups.items():
            keyboard.append([InlineKeyboardButton(f"📡 {group_name}", callback_data=f'live_{group_id}')])

    reply_markup = InlineKeyboardMarkup(keyboard)
    sent_msg = await context.bot.send_message(
        chat_id=user_id,
        text="Willkommen im VIPANNA2008BOT Kontrollzentrum!",
        reply_markup=reply_markup
    )
    # Die ID der Menü-Nachricht zum späteren Aufräumen speichern
    cleanup_message_ids.setdefault(user_id, []).append(sent_msg.message_id)


async def handle_group_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verarbeitet Nachrichten aus allen Gruppen."""
    message = update.message
    text = message.text or message.caption
    chat_id = message.chat_id
    user_id = ZIEL_BENUTZER_ID # Nachrichten gehen immer an den Ziel-Benutzer

    if not text:
        return

    # 1. Live-Überwachung prüfen
    if user_id in live_monitoring_status and live_monitoring_status[user_id] == chat_id:
        timestamp = datetime.now().strftime('%H:%M:%S')
        forwarded_msg = await message.forward(chat_id=user_id)
        # Zeitstempel als Antwort auf die weitergeleitete Nachricht senden
        reply_msg = await context.bot.send_message(
            chat_id=user_id,
            text=f"_{timestamp}_",
            reply_to_message_id=forwarded_msg.message_id,
            parse_mode='Markdown'
        )
        cleanup_message_ids.setdefault(user_id, []).extend([forwarded_msg.message_id, reply_msg.message_id])


    # 2. Auf Schlüsselwörter prüfen und im Hintergrund speichern
    if any(keyword in text.lower() for keyword in TRIGGER_WOERTER):
        try:
            # Nachricht in den Datenkanal weiterleiten, um sie zu speichern
            await message.forward(chat_id=DATA_CHANNEL_ID)
            logger.info(f"Nachricht aus Gruppe {chat_id} wegen Keyword gespeichert.")

            # Spezifische Extraktion für Gutschein-Codes
            if "code:" in text.lower():
                # Finde alles nach "Code:" (ignoriert Groß/Kleinschreibung)
                match = re.search(r'code:\s*(.*)', text, re.IGNORECASE)
                if match and match.group(1):
                    code = match.group(1).strip()
                    # Speichere den Code als separate, durchsuchbare Nachricht
                    await context.bot.send_message(chat_id=DATA_CHANNEL_ID, text=f"EXTRACTED_CODE: {code}")
                    logger.info(f"Gutschein-Code '{code}' extrahiert und gespeichert.")

        except Exception as e:
            logger.error(f"Fehler beim Speichern der Nachricht im Datenkanal: {e}")


async def new_group_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Wird ausgeführt, wenn der Bot zu einer neuen Gruppe hinzugefügt wird."""
    for member in update.message.new_chat_members:
        if member.id == context.bot.id:
            chat = update.effective_chat
            known_groups[chat.id] = chat.title
            logger.info(f"Bot wurde zur Gruppe '{chat.title}' ({chat.id}) hinzugefügt.")
            await context.bot.send_message(
                chat_id=ZIEL_BENUTZER_ID,
                text=f"✅ Bot zur Gruppe '{chat.title}' hinzugefügt. Sie ist jetzt für die Live-Überwachung verfügbar."
            )


# --- Callback Query Handler (für Knöpfe) ---

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verarbeitet alle Klicks auf Inline-Knöpfe."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    data = query.data

    # Altes Menü bereinigen
    await cleanup_chat(context)
    if query.message:
        cleanup_message_ids.setdefault(user_id, []).append(query.message.message_id)

    # --- DATENANSICHT ---
    if data.startswith('view_all_') or data.startswith('view_codes_'):
        page = int(data.split('_')[-1])
        is_codes_only = data.startswith('view_codes_')
        
        try:
            # Die letzten 200 Nachrichten-IDs aus dem Kanal holen (Telegram-Limit)
            # Für eine echte Datenbank wäre dies effizienter
            messages = await context.bot.get_chat_history(chat_id=DATA_CHANNEL_ID, limit=200)
            
            if is_codes_only:
                content = [m for m in messages if m.text and m.text.startswith("EXTRACTED_CODE:")]
                title = "Gutschein-Codes"
            else:
                content = [m for m in messages if not (m.text and m.text.startswith("EXTRACTED_CODE:"))]
                title = "Gespeicherte Nachrichten"

            if not content:
                sent_msg = await query.edit_message_text(text="Keine passenden Nachrichten gefunden.")
                cleanup_message_ids.setdefault(user_id, []).append(sent_msg.message_id)
                return

            # Paginierung (5 Einträge pro Seite)
            items_per_page = 5
            start_index = page * items_per_page
            end_index = start_index + items_per_page
            page_content = content[start_index:end_index]

            # Nachrichten für die Anzeige vorbereiten und senden
            for item in reversed(page_content): # Neueste zuerst
                 # Weiterleiten, um die Originalnachricht zu sehen
                fw_msg = await item.forward(chat_id=user_id)
                cleanup_message_ids.setdefault(user_id, []).append(fw_msg.message_id)

            # Navigationsknöpfe erstellen
            keyboard = []
            row = []
            if page > 0:
                row.append(InlineKeyboardButton("◀️ Zurück", callback_data=f'view_{"codes" if is_codes_only else "all"}_{page - 1}'))
            
            row.append(InlineKeyboardButton("🏠 Schließen & Aufräumen", callback_data='cleanup'))

            if end_index < len(content):
                row.append(InlineKeyboardButton("Vor ▶️", callback_data=f'view_{"codes" if is_codes_only else "all"}_{page + 1}'))
            
            keyboard.append(row)
            reply_markup = InlineKeyboardMarkup(keyboard)

            nav_msg = await context.bot.send_message(
                chat_id=user_id,
                text=f"Seite {page + 1} der {title}",
                reply_markup=reply_markup
            )
            cleanup_message_ids.setdefault(user_id, []).append(nav_msg.message_id)

        except Exception as e:
            logger.error(f"Fehler beim Abrufen der Daten aus dem Kanal: {e}")
            await context.bot.send_message(chat_id=user_id, text="Fehler beim Abrufen der Daten.")

    # --- LIVE-ÜBERWACHUNG STARTEN ---
    elif data.startswith('live_'):
        target_chat_id = int(data.split('_')[1])
        live_monitoring_status[user_id] = target_chat_id
        group_name = known_groups.get(target_chat_id, "Unbekannte Gruppe")

        keyboard = [[InlineKeyboardButton("⏹️ Beenden & Aufräumen", callback_data=f'stoplive_{target_chat_id}')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        control_msg = await context.bot.send_message(
            chat_id=user_id,
            text=f"🔴 Live-Überwachung für '{group_name}' gestartet.\nAlle Nachrichten werden jetzt hier angezeigt.",
            reply_markup=reply_markup
        )
        cleanup_message_ids.setdefault(user_id, []).append(control_msg.message_id)

    # --- LIVE-ÜBERWACHUNG BEENDEN ---
    elif data.startswith('stoplive_'):
        if user_id in live_monitoring_status:
            del live_monitoring_status[user_id]
        
        await cleanup_chat(context)
        await context.bot.send_message(chat_id=user_id, text="Live-Überwachung beendet und Chat aufgeräumt. Starte neu mit /start.")

    # --- AUFRÄUMEN ---
    elif data == 'cleanup':
        await cleanup_chat(context)
        await context.bot.send_message(chat_id=user_id, text="Ansicht geschlossen und Chat aufgeräumt. Starte neu mit /start.")

    # --- Leere Aktion (z.B. für Titel) ---
    elif data == 'noop':
        pass


def main():
    """Startet den Bot."""
    # Starte den Flask-Server in einem eigenen Thread
    flask_thread = Thread(target=run_flask)
    flask_thread.start()

    # Erstelle die Application und übergebe den Bot-Token
    application = Application.builder().token(BOT_TOKEN).build()

    # Registriere die Handler
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    # Handler für das Hinzufügen zu einer neuen Gruppe
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_group_handler))
    # Handler für alle Text- & Mediennachrichten in Gruppen
    application.add_handler(MessageHandler(filters.ChatType.GROUP & (filters.TEXT | filters.CAPTION), handle_group_messages))
    
    # Starte den Bot
    logger.info("Bot wird gestartet...")
    application.run_polling()

if __name__ == '__main__':
    main()
