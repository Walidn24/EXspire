import psycopg2
import psycopg2.extras
from config import DATABASE_URL
from datetime import date

def connetti_db():
    return psycopg2.connect(DATABASE_URL)

# ──────────────────────────────────────────
# TABELLE
# ──────────────────────────────────────────

def crea_tabelle_iniziali():
    conn = connetti_db()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS utenti (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT NOT NULL UNIQUE,
            first_name TEXT,
            username TEXT
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scontrini (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT NOT NULL,
            data_acquisto DATE DEFAULT CURRENT_DATE
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS prodotti (
            id SERIAL PRIMARY KEY,
            scontrino_id INT REFERENCES scontrini(id) ON DELETE CASCADE,
            telegram_id BIGINT NOT NULL,
            nome TEXT,
            prezzo FLOAT,
            data_scadenza DATE,
            scontato BOOLEAN DEFAULT FALSE,
            categoria TEXT
        );
    """)

    conn.commit()
    cursor.close()
    conn.close()
    print("[OK] Tabelle PostgreSQL create (se non esistevano gia).")

# ──────────────────────────────────────────
# UTENTI
# ──────────────────────────────────────────

def salva_utente(telegram_id, first_name, username):
    conn = connetti_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO utenti (telegram_id, first_name, username)
        VALUES (%s, %s, %s)
        ON CONFLICT (telegram_id) DO NOTHING
    """, (telegram_id, first_name, username))
    conn.commit()
    cursor.close()
    conn.close()

def assegna_nome_utente(telegram_id):
    nome_anonimo = f"Utente {telegram_id % 1000}"
    conn = connetti_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO utenti (telegram_id, first_name, username)
        VALUES (%s, %s, NULL)
        ON CONFLICT (telegram_id) DO UPDATE SET first_name = EXCLUDED.first_name, username = NULL
    """, (telegram_id, nome_anonimo))
    conn.commit()
    cursor.close()
    conn.close()
    return nome_anonimo

def get_nome_utente(telegram_id):
    conn = connetti_db()
    cursor = conn.cursor()
    cursor.execute("SELECT first_name FROM utenti WHERE telegram_id = %s", (telegram_id,))
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    return result[0] if result else "Utente"

# ──────────────────────────────────────────
# SCONTRINI
# ──────────────────────────────────────────

def salva_scontrino(telegram_id, data_acquisto=None):
    conn = connetti_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO scontrini (telegram_id, data_acquisto) VALUES (%s, %s) RETURNING id",
        (telegram_id, data_acquisto or date.today())
    )
    scontrino_id = cursor.fetchone()[0]
    conn.commit()
    cursor.close()
    conn.close()
    return scontrino_id

def get_scontrini_utente(telegram_id):
    conn = connetti_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute(
        "SELECT id, data_acquisto FROM scontrini WHERE telegram_id = %s ORDER BY id DESC",
        (telegram_id,)
    )
    scontrini = cursor.fetchall()
    cursor.close()
    conn.close()
    return scontrini

# ──────────────────────────────────────────
# PRODOTTI
# ──────────────────────────────────────────

def salva_prodotto(telegram_id, nome, prezzo, data_scadenza, scontato, categoria, scontrino_id):
    conn = connetti_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO prodotti (telegram_id, nome, prezzo, data_scadenza, scontato, categoria, scontrino_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (telegram_id, nome, prezzo, data_scadenza, scontato, categoria, scontrino_id))
    conn.commit()
    cursor.close()
    conn.close()

def get_prodotti_per_scontrino(scontrino_id):
    conn = connetti_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT nome, prezzo, data_scadenza, scontato, categoria
        FROM prodotti
        WHERE scontrino_id = %s
        ORDER BY data_scadenza ASC
    """, (scontrino_id,))
    prodotti = cursor.fetchall()
    cursor.close()
    conn.close()
    return prodotti

def get_prodotti_in_scadenza(giorni=3):
    """Ritorna i prodotti che scadono tra esattamente N giorni."""
    conn = connetti_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT telegram_id, nome, data_scadenza
        FROM prodotti
        WHERE data_scadenza = CURRENT_DATE + (%s * INTERVAL '1 day')
    """, (giorni,))
    prodotti = cursor.fetchall()
    cursor.close()
    conn.close()
    return prodotti

def rimuovi_prodotti_scaduti():
    """Elimina i prodotti con data_scadenza nel passato."""
    conn = connetti_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM prodotti WHERE data_scadenza < CURRENT_DATE")
    eliminati = cursor.rowcount
    conn.commit()
    cursor.close()
    conn.close()
    return eliminati

# ──────────────────────────────────────────
# STATISTICHE SPESA
# ──────────────────────────────────────────

def get_statistiche_spesa(telegram_id):
    conn = connetti_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cursor.execute("""
        SELECT
            COUNT(*) AS totale_prodotti,
            COALESCE(SUM(prezzo), 0) AS totale_speso,
            COUNT(CASE WHEN scontato THEN 1 END) AS num_scontati,
            COALESCE(SUM(CASE WHEN scontato THEN prezzo ELSE 0 END), 0) AS totale_scontati
        FROM prodotti
        WHERE telegram_id = %s
    """, (telegram_id,))
    generale = cursor.fetchone()

    cursor.execute("""
        SELECT categoria, COUNT(*) AS quantita, COALESCE(SUM(prezzo), 0) AS spesa
        FROM prodotti
        WHERE telegram_id = %s
        GROUP BY categoria
        ORDER BY spesa DESC
    """, (telegram_id,))
    per_categoria = cursor.fetchall()

    cursor.close()
    conn.close()
    return generale, per_categoria

def cancella_scontrino(scontrino_id, telegram_id):
    """Cancella uno scontrino e tutti i suoi prodotti (CASCADE)."""
    conn = connetti_db()
    cursor = conn.cursor()
    # Verifica che lo scontrino appartenga all'utente
    cursor.execute(
        "DELETE FROM scontrini WHERE id = %s AND telegram_id = %s",
        (scontrino_id, telegram_id)
    )
    eliminato = cursor.rowcount > 0
    conn.commit()
    cursor.close()
    conn.close()
    return eliminato