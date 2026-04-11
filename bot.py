# bot.py
import os
import tempfile
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler,
    filters, ConversationHandler, CallbackQueryHandler
)
from config import BOT_TOKEN
from utils import estrai_testo_da_pdf, estrai_prodotti
from database import (
    crea_tabelle_iniziali,
    salva_utente, assegna_nome_utente, get_nome_utente,
    salva_scontrino, salva_prodotto, get_prodotti_per_scontrino,
    get_scontrini_utente, get_prodotti_in_scadenza,
    rimuovi_prodotti_scaduti, get_statistiche_spesa,
    cancella_scontrino
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime

logging.basicConfig(level=logging.INFO)

SCELTA_NOME, SCELTA_OPZIONE, RICEVI_DOCUMENTO, INSERISCI_SCADENZA, VISUALIZZA_SCONTRINO, CANCELLA_SCONTRINO, CONFERMA_CANCELLA = range(7)

utenti_temp = {}

EMOJI_CATEGORIA = {
    "frutta": "🍐", "latticini": "🧀", "verdura": "🥬",
    "carne": "🥩", "pane": "🍞", "pasta": "🍝", "generico": "📦"
}

def get_nome(telegram_id):
    return utenti_temp.get(telegram_id) or get_nome_utente(telegram_id)

def keyboard_opzioni():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 Carica PDF dello scontrino", callback_data='pdf')],
        [InlineKeyboardButton("🧾 Visualizza prodotti salvati", callback_data='visualizza')],
        [InlineKeyboardButton("📊 Le mie statistiche", callback_data='statistiche')],
        [InlineKeyboardButton("🗑️ Cancella scontrino", callback_data='cancella')],
        [InlineKeyboardButton("🚪 Esci", callback_data='fine')],
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Si, usa il mio nome 😊", callback_data='si')],
        [InlineKeyboardButton("No, rimani anonimo 😶", callback_data='no')]
    ]
    await update.message.reply_text(
        "👋 Benvenuto in EXspire!\n\nVuoi salvare il tuo nome Telegram oppure usare un nome anonimo?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SCELTA_NOME

async def scelta_nome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    telegram_id = query.from_user.id

    if query.data == 'no':
        nome = assegna_nome_utente(telegram_id)
    else:
        nome = query.from_user.first_name
        salva_utente(telegram_id, nome, query.from_user.username)

    utenti_temp[telegram_id] = nome
    return await mostra_opzioni(update, context)

async def mostra_opzioni(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    nome = get_nome(telegram_id)
    testo = f"Ciao {nome}! Cosa vuoi fare? 👇"
    if update.callback_query:
        await update.callback_query.edit_message_text(testo, reply_markup=keyboard_opzioni())
    else:
        await update.message.reply_text(testo, reply_markup=keyboard_opzioni())
    return SCELTA_OPZIONE

async def scelta_opzione(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == 'pdf':
        await query.edit_message_text("Perfetto! Inviami il file PDF dello scontrino 📄")
        return RICEVI_DOCUMENTO
    elif query.data == 'visualizza':
        return await visualizza_prodotti(update, context)
    elif query.data == 'statistiche':
        return await mostra_statistiche(update, context)
    elif query.data == 'cancella':
        return await scegli_scontrino_da_cancellare(update, context)
    elif query.data == 'fine':
        return await fine(update, context)
    elif query.data == 'menu':
        return await mostra_opzioni(update, context)

async def ricevi_documento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    documento = update.message.document
    if documento.mime_type != 'application/pdf':
        await update.message.reply_text("❌ Per favore, inviami un file PDF valido.")
        return RICEVI_DOCUMENTO

    telegram_id = update.effective_user.id
    percorso = os.path.join(tempfile.gettempdir(), f"{documento.file_unique_id}.pdf")
    new_file = await documento.get_file()
    await new_file.download_to_drive(percorso)

    testo = estrai_testo_da_pdf(percorso)
    prodotti = estrai_prodotti(testo)
    os.remove(percorso)

    if not prodotti:
        await update.message.reply_text("⚠️ Non ho trovato prodotti nel PDF. Prova con un altro scontrino.")
        return SCELTA_OPZIONE

    scontrino_id = salva_scontrino(telegram_id)
    context.user_data['prodotti'] = prodotti
    context.user_data['scontrino_id'] = scontrino_id
    context.user_data['idx'] = 0
    context.user_data['scadenze'] = []

    await update.message.reply_text(f"✅ Ho trovato {len(prodotti)} prodotti. Inseriamo le date di scadenza ⏳")
    return await chiedi_scadenza(update, context)

async def chiedi_scadenza(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prodotti = context.user_data['prodotti']
    idx = context.user_data['idx']
    nome, nome_pulito, prezzo, scontato, categoria = prodotti[idx]

    emoji = EMOJI_CATEGORIA.get(categoria, "📦")
    msg = f"{emoji} <b>{nome_pulito.title()}</b> — 💰 {prezzo:.2f}€"
    if scontato:
        msg += " 🏷️ <i>(Scontato)</i>"
    msg += f"\n📅 Inserisci la data di scadenza (gg-mm-aaaa)\n<i>{idx+1}/{len(prodotti)}</i>"

    if update.callback_query:
        await update.callback_query.edit_message_text(msg, parse_mode="HTML")
    else:
        await update.message.reply_text(msg, parse_mode="HTML")
    return INSERISCI_SCADENZA

async def salva_scadenza(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data_input = update.message.text.strip()
    try:
        data_scadenza = datetime.strptime(data_input, "%d-%m-%Y").date()
    except ValueError:
        await update.message.reply_text("❌ Formato non valido. Riprova (gg-mm-aaaa).")
        return INSERISCI_SCADENZA

    telegram_id = update.effective_user.id
    prodotti = context.user_data['prodotti']
    idx = context.user_data['idx']
    scontrino_id = context.user_data['scontrino_id']
    nome, nome_pulito, prezzo, scontato, categoria = prodotti[idx]

    context.user_data['scadenze'].append((nome_pulito, data_scadenza))
    context.user_data['idx'] += 1

    salva_prodotto(telegram_id, nome_pulito, prezzo, data_scadenza, scontato, categoria, scontrino_id)

    if context.user_data['idx'] < len(prodotti):
        return await chiedi_scadenza(update, context)

    await update.message.reply_text(
        "✅ Tutti i prodotti sono stati salvati!",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Visualizza prodotti", callback_data="visualizza")],
            [InlineKeyboardButton("🏠 Menu principale", callback_data="menu")],
        ])
    )
    return SCELTA_OPZIONE

async def visualizza_prodotti(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    telegram_id = query.from_user.id
    scontrini = get_scontrini_utente(telegram_id)

    if not scontrini:
        await query.edit_message_text(
            "❌ Nessuno scontrino caricato ancora.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu")]])
        )
        return SCELTA_OPZIONE

    bottoni = [
        [InlineKeyboardButton(f"🧾 Scontrino del {s['data_acquisto']}", callback_data=f"scontrino_{s['id']}")]
        for s in scontrini
    ]
    bottoni.append([InlineKeyboardButton("🏠 Menu", callback_data="menu")])
    await query.edit_message_text("📜 Quale scontrino vuoi vedere?", reply_markup=InlineKeyboardMarkup(bottoni))
    return VISUALIZZA_SCONTRINO

async def mostra_scontrino(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    scontrino_id = int(query.data.split('_')[1])
    prodotti = get_prodotti_per_scontrino(scontrino_id)

    if not prodotti:
        await query.edit_message_text(
            "❌ Nessun prodotto trovato.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu")]])
        )
        return SCELTA_OPZIONE

    oggi = datetime.now().date()
    testo = f"🧾 <b>Scontrino #{scontrino_id}</b>\n\n"
    for p in prodotti:
        nome, prezzo, data_scad, scontato, categoria = p
        emoji = EMOJI_CATEGORIA.get(categoria, "📦")
        giorni_rimasti = (data_scad - oggi).days
        riga = f"{emoji} {nome.title()} — 💰 {prezzo:.2f}€"
        if scontato:
            riga += " 🏷️"
        if giorni_rimasti <= 0:
            riga += " ⛔ <b>SCADUTO</b>"
        elif giorni_rimasti <= 3:
            riga += f" ⚠️ <b>Scade tra {giorni_rimasti}g</b>"
        else:
            riga += f" — 📅 {data_scad}"
        testo += riga + "\n"

    await query.edit_message_text(
        testo,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu")]])
    )
    return SCELTA_OPZIONE

async def mostra_statistiche(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    telegram_id = query.from_user.id

    generale, per_categoria = get_statistiche_spesa(telegram_id)

    if not generale or generale['totale_prodotti'] == 0:
        await query.edit_message_text(
            "📊 Nessun dato disponibile ancora. Carica il tuo primo scontrino!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu")]])
        )
        return SCELTA_OPZIONE

    testo = "📊 <b>Le tue statistiche</b>\n\n"
    testo += f"🛒 Prodotti totali: <b>{generale['totale_prodotti']}</b>\n"
    testo += f"💶 Totale speso: <b>{float(generale['totale_speso']):.2f}€</b>\n"
    testo += f"🏷️ Prodotti scontati: <b>{generale['num_scontati']}</b> ({float(generale['totale_scontati']):.2f}€ risparmiati)\n\n"
    testo += "📦 <b>Spesa per categoria:</b>\n"
    for cat in per_categoria:
        emoji = EMOJI_CATEGORIA.get(cat['categoria'], "📦")
        testo += f"{emoji} {cat['categoria'].title()}: {cat['quantita']} prodotti — {float(cat['spesa']):.2f}€\n"

    await query.edit_message_text(
        testo,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu")]])
    )
    return SCELTA_OPZIONE

# ──────────────────────────────────────────
# CANCELLA SCONTRINO
# ──────────────────────────────────────────

async def scegli_scontrino_da_cancellare(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    telegram_id = query.from_user.id
    scontrini = get_scontrini_utente(telegram_id)

    if not scontrini:
        await query.edit_message_text(
            "❌ Nessuno scontrino da cancellare.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu")]])
        )
        return SCELTA_OPZIONE

    bottoni = [
        [InlineKeyboardButton(f"🗑️ Scontrino del {s['data_acquisto']}", callback_data=f"del_{s['id']}")]
        for s in scontrini
    ]
    bottoni.append([InlineKeyboardButton("🏠 Menu", callback_data="menu")])
    await query.edit_message_text(
        "🗑️ Quale scontrino vuoi cancellare?",
        reply_markup=InlineKeyboardMarkup(bottoni)
    )
    return CANCELLA_SCONTRINO

async def conferma_cancella(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    scontrino_id = int(query.data.split('_')[1])
    context.user_data['scontrino_da_cancellare'] = scontrino_id

    await query.edit_message_text(
        f"⚠️ Sei sicuro di voler cancellare lo scontrino #{scontrino_id} e tutti i suoi prodotti?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Sì, cancella", callback_data=f"confermadel_{scontrino_id}")],
            [InlineKeyboardButton("❌ No, torna indietro", callback_data="menu")],
        ])
    )
    return CONFERMA_CANCELLA

async def esegui_cancella(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    telegram_id = query.from_user.id
    scontrino_id = int(query.data.split('_')[1])

    eliminato = cancella_scontrino(scontrino_id, telegram_id)

    if eliminato:
        await query.edit_message_text(
            f"✅ Scontrino #{scontrino_id} cancellato con successo!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu")]])
        )
    else:
        await query.edit_message_text(
            "❌ Errore durante la cancellazione.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu")]])
        )
    return SCELTA_OPZIONE

async def fine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    nome = get_nome(query.from_user.id)
    await query.edit_message_text(f"Grazie {nome}, alla prossima! 👋")
    return ConversationHandler.END

# ──────────────────────────────────────────
# JOBS SCHEDULATI
# ──────────────────────────────────────────

async def job_notifiche_scadenza(app):
    prodotti = get_prodotti_in_scadenza(giorni=3)
    for telegram_id, nome_prod, data_scad in prodotti:
        try:
            nome_utente = get_nome_utente(telegram_id)
            await app.bot.send_message(
                chat_id=telegram_id,
                text=f"⏰ Ciao {nome_utente}! Il prodotto <b>{nome_prod.title()}</b> scadrà tra 3 giorni ({data_scad}) 🛒",
                parse_mode="HTML"
            )
        except Exception as e:
            logging.warning(f"Impossibile notificare {telegram_id}: {e}")

async def job_pulizia_scaduti(app):
    eliminati = rimuovi_prodotti_scaduti()
    logging.info(f"[Pulizia] Rimossi {eliminati} prodotti scaduti.")

# ──────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────

if __name__ == '__main__':
    crea_tabelle_iniziali()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            SCELTA_NOME: [CallbackQueryHandler(scelta_nome)],
            SCELTA_OPZIONE: [
                CallbackQueryHandler(mostra_scontrino, pattern="^scontrino_"),
                CallbackQueryHandler(scelta_opzione),
            ],
            RICEVI_DOCUMENTO: [MessageHandler(filters.Document.PDF, ricevi_documento)],
            INSERISCI_SCADENZA: [MessageHandler(filters.TEXT & ~filters.COMMAND, salva_scadenza)],
            VISUALIZZA_SCONTRINO: [CallbackQueryHandler(mostra_scontrino, pattern="^scontrino_")],
            CANCELLA_SCONTRINO: [
                CallbackQueryHandler(conferma_cancella, pattern="^del_"),
                CallbackQueryHandler(mostra_opzioni, pattern="^menu$"),
            ],
            CONFERMA_CANCELLA: [
                CallbackQueryHandler(esegui_cancella, pattern="^confermadel_"),
                CallbackQueryHandler(mostra_opzioni, pattern="^menu$"),
            ],
        },
        fallbacks=[
            CommandHandler("start", start),
            CallbackQueryHandler(mostra_opzioni, pattern="^menu$"),
        ],
        per_message=False,
    )

    app.add_handler(conv_handler)

    async def post_init(application):
        scheduler = AsyncIOScheduler()
        scheduler.add_job(job_notifiche_scadenza, 'cron', hour=9, minute=0, args=[application])
        scheduler.add_job(job_pulizia_scaduti, 'cron', hour=0, minute=0, args=[application])
        scheduler.start()
        logging.info("Scheduler avviato!")

    app.post_init = post_init

    logging.info("Bot avviato!")
    app.run_polling(drop_pending_updates=True)