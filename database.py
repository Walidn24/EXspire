import mysql.connector
from config import DB_HOST, DB_USER, DB_PASSWORD, DB_NAME

def connetti_db():
    return mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME
    )

# ✅ CREA LA TABELLA SE NON ESISTE
def crea_tabella_utenti():
    conn = connetti_db()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS utenti (
            id INT AUTO_INCREMENT PRIMARY KEY,
            telegram_id BIGINT NOT NULL,
            first_name TEXT,
            username TEXT
        );
    """)
    conn.commit()
    conn.close()

def salva_utente(telegram_id, first_name, username):
    conn = connetti_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM utenti WHERE telegram_id = %s", (telegram_id,))
    esiste = cursor.fetchone()
    if esiste:
        conn.close()
        return False

    cursor.execute(
        "INSERT INTO utenti (telegram_id, first_name, username) VALUES (%s, %s, %s)",
        (telegram_id, first_name, username)
    )
    conn.commit()
    conn.close()
    return True

def assegna_nome_utente(telegram_id):
    conn = connetti_db()
    cursor = conn.cursor()
    nome_anonimo = f"Utente {telegram_id % 1000}"
    cursor.execute(
        "UPDATE utenti SET first_name = %s, username = NULL WHERE telegram_id = %s",
        (nome_anonimo, telegram_id)
    )
    conn.commit()
    conn.close()
    return nome_anonimo

def get_nome_utente(telegram_id):
    conn = connetti_db()
    cursor = conn.cursor()
    cursor.execute("SELECT first_name FROM utenti WHERE telegram_id = %s", (telegram_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else "Utente"

def salva_scontrino(telegram_id):
    conn = connetti_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO scontrini (telegram_id) VALUES (%s)", (telegram_id,))
    conn.commit()
    scontrino_id = cursor.lastrowid
    conn.close()
    return scontrino_id

def salva_prodotto(telegram_id, nome, prezzo, data_scadenza, scontato, categoria, scontrino_id):
    conn = connetti_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO prodotti (telegram_id, nome, prezzo, data_scadenza, scontato, categoria, scontrino_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (telegram_id, nome, prezzo, data_scadenza, scontato, categoria, scontrino_id))
    conn.commit()
    conn.close()

def get_scontrini_utente(telegram_id):
    conn = connetti_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id FROM scontrini WHERE telegram_id = %s", (telegram_id,))
    scontrini = cursor.fetchall()
    conn.close()
    return scontrini

def get_prodotti_per_scontrino(scontrino_id):
    conn = connetti_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT nome, prezzo, data_scadenza, scontato, categoria
        FROM prodotti
        WHERE scontrino_id = %s
    """, (scontrino_id,))
    prodotti = cursor.fetchall()
    conn.close()
    return prodotti
