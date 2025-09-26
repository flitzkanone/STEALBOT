# db_handler.py
import sqlite3
import re
from datetime import datetime

DATABASE_NAME = 'bot_database.db'
PAGE_SIZE = 5 # Anzahl der Einträge pro Seite

def init_db():
    """Initialisiert die Datenbank und erstellt die Tabelle, falls sie nicht existiert."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_title TEXT NOT NULL,
            message_text TEXT NOT NULL,
            gutschein_code TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def extract_gutschein_code(text):
    """Extrahiert den Gutschein-Code nach der Regel: 'Code:' bis ' Von'."""
    # re.IGNORECASE ignoriert Groß-/Kleinschreibung für "Code:" und "Von"
    # re.DOTALL lässt den Punkt (.) auch Zeilenumbrüche umfassen
    match = re.search(r"Code:\s*(.*?)\s*Von", text, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip() # .strip() entfernt Leerzeichen am Anfang/Ende
    return None

def add_message(chat_title, message_text):
    """Fügt eine neue Nachricht zur Datenbank hinzu und extrahiert den Code."""
    code = extract_gutschein_code(message_text)
    
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO messages (chat_title, message_text, gutschein_code) VALUES (?, ?, ?)",
        (chat_title, message_text, code)
    )
    conn.commit()
    conn.close()

def get_messages(page=0):
    """Holt eine Seite mit allen Nachrichten aus der Datenbank."""
    offset = page * PAGE_SIZE
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT chat_title, message_text, timestamp FROM messages ORDER BY timestamp DESC LIMIT ? OFFSET ?",
        (PAGE_SIZE, offset)
    )
    results = cursor.fetchall()
    conn.close()
    return results

def get_codes(page=0):
    """Holt eine Seite mit Nachrichten, die einen Gutschein-Code enthalten."""
    offset = page * PAGE_SIZE
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT chat_title, gutschein_code, timestamp FROM messages WHERE gutschein_code IS NOT NULL ORDER BY timestamp DESC LIMIT ? OFFSET ?",
        (PAGE_SIZE, offset)
    )
    results = cursor.fetchall()
    conn.close()
    return results
