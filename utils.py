import fitz  # PyMuPDF
import re

def estrai_testo_da_pdf(percorso_pdf):
    with fitz.open(percorso_pdf) as pdf:
        testo = ""
        for pagina in pdf:
            testo += pagina.get_text()
    return testo

def estrai_prodotti(testo):
    righe = testo.split("\n")
    prodotti = []
    
    blacklist = [
        "TOTALE", "di cui", "PAGAMENTO", "DOCUMENTO", "IVA", "CARTA",
        "FATTURA", "RICEVUTA", "OPER", "CASSA", "PUNTI", "ESSER", "POLIZZA",
        "VERTI", "S.p.A", "Offerta", "Neg.", "auto", "Mastercard", "VISA",
        "CREDITO", "BANCOMAT", "PAGATO", "borsa", "shopper", "sacchetto",
        "sconto", "SCONTO", "Sconto", "PRESTAZIONE", "EURO", "RESTO"
    ]

    for i, riga in enumerate(righe):
        if any(termine.lower() in riga.lower() for termine in blacklist):
            continue

        match = re.search(r"(.+?)\s+(\d+,\d{2})", riga)
        if match:
            nome = match.group(1).strip()
            prezzo = float(match.group(2).replace(",", "."))
            nome_pulito = nome.lower()

            # Filtri aggiuntivi per sicurezza
            if any(termine in nome_pulito for termine in ["shopper", "sconto", "sacchetto", "borsa"]):
                continue

            scontato = False
            if i + 1 < len(righe) and "SCONTO" in righe[i + 1].upper():
                scontato = True

            categoria = riconosci_categoria(nome_pulito)
            prodotti.append((nome, nome_pulito, prezzo, scontato, categoria))

    return prodotti

def riconosci_categoria(nome):
    nome = nome.lower()
    if any(parola in nome for parola in ["pera", "pere", "mele", "banana", "anguria", "frutta", "ananas", "kiwi", "uva", "mela"]):
        return "frutta"
    elif any(parola in nome for parola in ["insalata", "verdura", "zucchina", "carota", "pomodoro", "cavolo", "broccolo"]):
        return "verdura"
    elif any(parola in nome for parola in ["latte", "yogurt", "formaggio", "mozzarella", "gorgonzola", "burro", "parmigiano", "gorg", "gorg.gran"]):
        return "latticini"
    elif any(parola in nome for parola in ["carne", "pollo", "bistecca", "salsiccia", "prosciutto", "speck"]):
        return "carne"
    elif any(parola in nome for parola in ["pane", "grissini", "panino", "pizza", "focaccia"]):
        return "pane"
    elif any(parola in nome for parola in ["pasta", "riso", "spaghetti", "penne", "fusilli"]):
        return "pasta"
    else:
        return "generico"
