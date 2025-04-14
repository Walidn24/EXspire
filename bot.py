# bot.py
import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler,
    filters, ConversationHandler, CallbackQueryHandler
)
from config import BOT_TOKEN
from utils import estrai_testo_da_pdf, estrai_prodotti
from database import (
    salva_utente, assegna_nome_utente, get_nome_utente,
    salva_scontrino, salva_prodotto, get_prodotti_per_scontrino,
    get_scontrini_utente
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime
from functools import partial
from crea_tabelle_db import crea_tabelle_iniziali

logging.basicConfig(level=logging.INFO)

SCELTA_NOME, SCELTA_OPZIONE, RICEVI_DOCUMENTO, INSERISCI_SCADENZA, VISUALIZZA_SCONTRINO = range(5)

utenti_temp = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    keyboard = [
        [InlineKeyboardButton("Sì 😊", callback_data='si')],
        [InlineKeyboardButton("No 😶", callback_data='no')]
    ]
    await update.message.reply_text(
        "Vuoi salvare il tuo nome Telegram oppure usare un nome anonimo?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SCELTA_NOME

async def scelta_nome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    telegram_id = query.from_user.id

    if query.data == 'no':
        nome_generato = assegna_nome_utente(telegram_id)
        utenti_temp[telegram_id] = nome_generato
        salva_utente(telegram_id, None, None)
    else:
        utenti_temp[telegram_id] = query.from_user.first_name
        salva_utente(telegram_id, query.from_user.first_name, query.from_user.username)

    return await mostra_opzioni(update, context)

async def mostra_opzioni(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    nome = utenti_temp.get(telegram_id, get_nome_utente(telegram_id))
    keyboard = [
        [InlineKeyboardButton("📄 Carica PDF dello scontrino", callback_data='pdf')],
        [InlineKeyboardButton("🧾 Visualizza prodotti salvati", callback_data='visualizza')]
    ]
    markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(f"Ciao {nome}! Scegli un'opzione 👇", reply_markup=markup)
    else:
        await update.message.reply_text(f"Ciao {nome}! Scegli un'opzione 👇", reply_markup=markup)
    return SCELTA_OPZIONE

async def scelta_opzione(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == 'pdf':
        await query.edit_message_text("Perfetto! Inviami il file PDF dello scontrino 📄")
        return RICEVI_DOCUMENTO
    elif query.data == 'visualizza':
        return await visualizza_prodotti(update, context)
    elif query.data == 'fine':
        return await fine(update, context)

async def ricevi_documento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    documento = update.message.document
    if documento.mime_type != 'application/pdf':
        await update.message.reply_text("❌ Per favore, inviami un file PDF valido.")
        return RICEVI_DOCUMENTO

    telegram_id = update.effective_user.id
    percorso = f"{documento.file_unique_id}.pdf"
    new_file = await documento.get_file()
    await new_file.download_to_drive(percorso)

    testo = estrai_testo_da_pdf(percorso)
    prodotti = estrai_prodotti(testo)
    os.remove(percorso)

    scontrino_id = salva_scontrino(telegram_id)
    context.user_data['prodotti'] = prodotti
    context.user_data['scontrino_id'] = scontrino_id
    context.user_data['idx'] = 0
    context.user_data['scadenze'] = []

    await update.message.reply_text(f"✅ Ho trovato {len(prodotti)} prodotti. Inseriamo le date ⏳")
    return await chiedi_scadenza(update, context)

async def chiedi_scadenza(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prodotti = context.user_data['prodotti']
    idx = context.user_data['idx']
    nome, nome_pulito, prezzo, scontato, categoria = prodotti[idx]

    emoji_categoria = {
        "frutta": "🍐", "latticini": "🧀", "verdura": "🥬",
        "carne": "🥩", "pane": "🍞", "pasta": "🍝", "generico": "📦"
    }.get(categoria, "📦")

    msg = f"{emoji_categoria} {nome_pulito.title()} - 💰 {prezzo}€"
    if scontato:
        msg += " (Scontato 🏷️)"
    msg += "\n📅 Inserisci la data di scadenza (gg-mm-aaaa)"
    await update.message.reply_text(msg)
    return INSERISCI_SCADENZA

async def salva_scadenza(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data_input = update.message.text
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
    else:
        oggi = datetime.now().date()
        for nome_prod, data in context.user_data['scadenze']:
            giorni = (data - oggi).days
            if giorni == 3:
                context.job_queue.run_once(
                    callback=partial(notifica_scadenza, telegram_id=telegram_id, nome_prod=nome_prod),
                    when=1,
                    name=f"notifica_{telegram_id}_{nome_prod}"
                )

        await update.message.reply_text("✅ Prodotti salvati!\nVuoi visualizzarli?", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Sì 🔍", callback_data="visualizza")],
            [InlineKeyboardButton("No 👋", callback_data="fine")]
        ]))
        return SCELTA_OPZIONE

async def notifica_scadenza(ctx, telegram_id, nome_prod):
    await ctx.bot.send_message(
        chat_id=telegram_id,
        text=f"⏰ {utenti_temp.get(telegram_id, get_nome_utente(telegram_id))}, il prodotto \"{nome_prod.title()}\" scadrà tra 3 giorni! 🛒"
    )

async def visualizza_prodotti(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    telegram_id = query.from_user.id
    scontrini = get_scontrini_utente(telegram_id)

    if not scontrini:
        await query.edit_message_text("❌ Nessuno scontrino caricato.")
        return ConversationHandler.END

    bottoni = [
        [InlineKeyboardButton(f"Scontrino {i+1}", callback_data=f"scontrino_{s['id']}")]
        for i, s in enumerate(scontrini)
    ]
    await query.edit_message_text("📜 Quale scontrino vuoi vedere?", reply_markup=InlineKeyboardMarkup(bottoni))
    return VISUALIZZA_SCONTRINO

async def mostra_scontrino(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    scontrino_id = int(query.data.split('_')[1])
    prodotti = get_prodotti_per_scontrino(scontrino_id)

    if not prodotti:
        await query.edit_message_text("❌ Nessun prodotto trovato.")
        return ConversationHandler.END

    testo = f"🧾 Scontrino {scontrino_id}:\n"
    for p in prodotti:
        emoji = {
            "frutta": "🍐", "latticini": "🧀", "verdura": "🥬",
            "carne": "🥩", "pane": "🍞", "pasta": "🍝", "generico": "📦"
        }.get(p[4], "📦")

        testo += f"{emoji} {p[0].title()} — 💰 {p[1]}€ — Scade il {p[2]}"
        if p[3]: testo += " 🔖"
        testo += f" — Categoria: {p[4]}\n"

    await query.edit_message_text(testo)
    return ConversationHandler.END

async def fine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    telegram_id = query.from_user.id
    nome = utenti_temp.get(telegram_id, get_nome_utente(telegram_id))
    await query.edit_message_text(f"Grazie {nome}, alla prossima! 👋")
    return ConversationHandler.END

if __name__ == '__main__':
    try:
        crea_tabelle_iniziali()
    except Exception as e:
        print(f"Error creating tables: {e}")
        pass
    
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            SCELTA_NOME: [CallbackQueryHandler(scelta_nome)],
            SCELTA_OPZIONE: [CallbackQueryHandler(scelta_opzione)],
            RICEVI_DOCUMENTO: [MessageHandler(filters.Document.PDF, ricevi_documento)],
            INSERISCI_SCADENZA: [MessageHandler(filters.TEXT & ~filters.COMMAND, salva_scadenza)],
            VISUALIZZA_SCONTRINO: [CallbackQueryHandler(mostra_scontrino)],
        },
        fallbacks=[CommandHandler("start", start)],
    )
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(fine, pattern="^fine$"))
    scheduler = AsyncIOScheduler()
    scheduler.start()
    app.run_polling()
