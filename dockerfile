FROM python:3.11

WORKDIR /usr/src/app

# Copia solo i requirements per sfruttare la cache Docker
COPY requirements.txt .

# Installa i pacchetti (verrà eseguito solo se requirements.txt cambia)
RUN pip install --no-cache-dir -r requirements.txt

# Ora copia il resto dei file dell'app
COPY . .

RUN pip install -r requirements.txt

CMD ["python", "bot.py"]