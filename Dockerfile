# Usa un'immagine base con Python preinstallato e slim per essere più leggero
FROM python:3.9-slim-buster

# Imposta il working directory
WORKDIR /app

# Copia i requisiti e installali
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Installa le dipendenze di sistema necessarie per Screaming Frog
# NOTA: Queste dipendenze possono variare leggermente a seconda della versione di SF o dell'immagine base
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    cabextract \
    libgconf-2-4 \
    xfonts-utils \
    libxtst6 \
    libnss3 \
    libasound2 \
    libxcomposite1 \
    libxrandr2 \
    libgtk-3-0 \
    && rm -rf /var/lib/apt/lists/*

# Scarica e installa Screaming Frog SEO Spider CLI
# Controlla sempre l'ultima versione disponibile sul sito di Screaming Frog!
ARG SF_VERSION="19.1" # Aggiorna questo numero di versione
ARG SF_FILENAME="screamingfrogseospider_${SF_VERSION}.deb"
ARG SF_URL="https://download.screamingfrog.co.uk/products/seo-spider/${SF_VERSION}/${SF_FILENAME}"

RUN wget ${SF_URL} -O /tmp/${SF_FILENAME} \
    && dpkg -i /tmp/${SF_FILENAME} \
    && rm /tmp/${SF_FILENAME}

# Copia l'applicazione FastAPI
COPY app/ ./app/

# Copia la cartella config (se esiste)
COPY config/ ./config/

# Crea la directory di output per i crawl
RUN mkdir -p /app/data/crawls

# Espone la porta su cui girerà FastAPI
EXPOSE 8000

# Comando per avviare Uvicorn (il server ASGI per FastAPI)
# --host 0.0.0.0 permette l'accesso da qualsiasi interfaccia di rete
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
