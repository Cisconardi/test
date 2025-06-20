from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
import subprocess
import os
import shutil
import uuid
import asyncio
import glob

app = FastAPI(title="Screaming Frog CLI API",
              description="API to run Screaming Frog CLI crawls and retrieve results.",
              version="1.0.0")

# Percorsi interni al container
CRAWL_DATA_DIR = "/app/data/crawls"
# Rimuovi LICENCE_PATH fisso, ora sarà gestito via variabile d'ambiente
CONFIG_DIR = "/app/config"

# Assicurati che le directory esistano all'avvio
os.makedirs(CRAWL_DATA_DIR, exist_ok=True)
os.makedirs(CONFIG_DIR, exist_ok=True)

# Modello per la richiesta di crawl (resta invariato)
class CrawlRequest(BaseModel):
    url: str
    config_file: str = "default_config.seospider"
    export_format: str = "csv"
    export_type: str = "all_links"

# Modello per lo stato del crawl (resta invariato)
class CrawlStatus(BaseModel):
    crawl_id: str
    status: str
    url: str
    output_path: str = None
    error_message: str = None
    results_ready: bool = False

# Dizionario per tenere traccia dei crawl in corso (resta invariato)
active_crawls = {}

# Funzione per eseguire il crawl in background
async def run_screaming_frog_crawl(crawl_id: str, request: CrawlRequest):
    crawl_output_dir = os.path.join(CRAWL_DATA_DIR, crawl_id)
    os.makedirs(crawl_output_dir, exist_ok=True) # Questa riga dovrebbe essere indentata correttamente

    # --- INIZIO MODIFICA PER LA GESTIONE DELLA LICENZA (CON NOME E CHIAVE) ---
    sf_user_dir = os.path.expanduser("~/.screamingfrog/seospider/")
    os.makedirs(sf_user_dir, exist_ok=True) # <<< Questa è la riga 50 nel tuo esempio di errore

    sf_licence_name = os.getenv("SF_LICENSE_NAME")
    sf_licence_key = os.getenv("SF_LICENCE_KEY")

    if sf_licence_name and sf_licence_key:
        licence_file_path = os.path.join(sf_user_dir, "licence.txt")
        try:
            with open(licence_file_path, "w") as f:
                f.write(sf_licence_name + "\n")
                f.write(sf_licence_key + "\n")
            print(f"Licenza Screaming Frog (nome e chiave) scritta con successo in {licence_file_path}")
        except IOError as e:
            active_crawls[crawl_id].error_message = f"Errore scrittura licenza: {e}"
            active_crawls[crawl_id].status = "failed"
            print(f"ERRORE: Impossibile scrivere il file di licenza: {e}")
            return
    else:
        print("ATTENZIONE: Variabili d'ambiente SF_LICENSE_NAME o SF_LICENCE_KEY non trovate. Il crawl sarà limitato a 500 URL.")
    # --- FINE MODIFICA PER LA GESTIONE DELLA LICENZA ---


    # Costruisci il comando base per Screaming Frog CLI (resto invariato)
    command = [
        "screamingfrogseospider",
        "--crawl", request.url,
        "--headless",
        "--output-folder", crawl_output_dir,
        "--timestamped-output",
      "--accepteula",
    ]

    # ... (resto della logica per config_file, export_format, esecuzione subprocess, etc. - resta invariato) ...

    # Aggiungi il file di configurazione se specificato e presente
    config_full_path = os.path.join(CONFIG_DIR, request.config_file)
    if request.config_file != "default_config.seospider" and not os.path.exists(config_full_path):
        active_crawls[crawl_id].error_message = f"Config file '{request.config_file}' not found."
        active_crawls[crawl_id].status = "failed"
        return

    if os.path.exists(config_full_path):
        command.extend(["--config", config_full_path])

    # Aggiungi le opzioni di export
    if request.export_format == "csv":
        command.extend(["--export-csv", request.export_type])
    elif request.export_format == "json":
        command.extend(["--export-json", request.export_type])
    else:
        active_crawls[crawl_id].error_message = "Invalid export_format. Must be 'csv' or 'json'."
        active_crawls[crawl_id].status = "failed"
        return

    # Avvia il processo Screaming Frog
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode == 0:
            active_crawls[crawl_id].status = "completed"
            active_crawls[crawl_id].results_ready = True
            print(f"Crawl {crawl_id} completed for {request.url}")
        else:
            active_crawls[crawl_id].status = "failed"
            active_crawls[crawl_id].error_message = stderr.decode(errors='ignore')
            print(f"Crawl {crawl_id} failed for {request.url}. Error: {stderr.decode(errors='ignore')}")

        active_crawls[crawl_id].output_path = crawl_output_dir

    except Exception as e:
        active_crawls[crawl_id].status = "failed"
        active_crawls[crawl_id].error_message = str(e)
        print(f"Exception during crawl {crawl_id}: {e}")

# --- API Endpoints ---

@app.post("/crawl/", response_model=CrawlStatus, summary="Avvia un nuovo crawl con Screaming Frog")
async def start_new_crawl(request: CrawlRequest, background_tasks: BackgroundTasks):
    """
    Avvia un nuovo crawl di Screaming Frog in background.
    """
    crawl_id = str(uuid.uuid4())
    active_crawls[crawl_id] = CrawlStatus(
        crawl_id=crawl_id,
        status="running",
        url=request.url,
        output_path=os.path.join(CRAWL_DATA_DIR, crawl_id)
    )

    background_tasks.add_task(run_screaming_frog_crawl, crawl_id, request)

    return active_crawls[crawl_id]

@app.get("/crawl/status/{crawl_id}", response_model=CrawlStatus, summary="Controlla lo stato di un crawl")
async def get_crawl_status(crawl_id: str):
    """
    Recupera lo stato di un crawl specificato dall'ID.
    """
    if crawl_id not in active_crawls:
        raise HTTPException(status_code=404, detail="Crawl ID not found.")
    return active_crawls[crawl_id]

@app.get("/crawl/results/{crawl_id}", summary="Scarica i risultati del crawl")
async def get_crawl_results(crawl_id: str):
    """
    Scarica il file di output principale (CSV/JSON) per un crawl completato.
    """
    if crawl_id not in active_crawls:
        raise HTTPException(status_code=404, detail="Crawl ID not found.")

    crawl_info = active_crawls[crawl_id]
    if crawl_info.status != "completed" or not crawl_info.results_ready:
        raise HTTPException(status_code=400, detail="Crawl not yet completed or failed.")

    output_dir = crawl_info.output_path
    if not os.path.exists(output_dir):
        raise HTTPException(status_code=500, detail="Output directory not found for completed crawl.")

    # Trova il file di output più probabile (es. internal_all.csv/json)
    # Screaming Frog crea nomi di file con timestamp e una parte come 'internal_all'
    # Cerchiamo il file con l'estensione e il tipo di export richiesto
    
    # Esempio: cerca un file che finisce con '_internal_all.csv' o '_all.json'
    # Questo è un po' euristico, potrebbe essere migliorato se si sapesse esattamente il nome
    
    expected_filename_part = f"_{crawl_info.export_type}.{crawl_info.export_format}"
    
    # Usa glob per trovare il file corrispondente al pattern
    list_of_files = glob.glob(os.path.join(output_dir, f"*{expected_filename_part}"))
    
    if not list_of_files:
        # Se non trova il file specifico, prova a cercare qualsiasi file csv/json
        list_of_files = glob.glob(os.path.join(output_dir, f"*.{crawl_info.export_format}"))
    
    if not list_of_files:
        raise HTTPException(status_code=404, detail=f"No {crawl_info.export_format} results found in {output_dir}. Make sure export_type is correct.")
    
    # Prendi l'ultimo file modificato, o il primo trovato
    latest_file = max(list_of_files, key=os.path.getmtime) if list_of_files else None

    if latest_file and os.path.exists(latest_file):
        return FileResponse(path=latest_file, filename=os.path.basename(latest_file),
                            media_type=f"text/{crawl_info.export_format}" if crawl_info.export_format == "csv" else "application/json")
    else:
        raise HTTPException(status_code=404, detail=f"Result file not found: {latest_file}")


@app.post("/config/upload/", summary="Carica un file di configurazione Screaming Frog")
async def upload_config_file(file: UploadFile = File(...)):
    """
    Carica un file .seospider personalizzato da utilizzare per i crawl.
    Il nome del file caricato sarà quello con cui potrai referenziarlo nei crawl.
    """
    if not file.filename.endswith(".seospider"):
        raise HTTPException(status_code=400, detail="Invalid file type. Only .seospider files are allowed.")

    file_path = os.path.join(CONFIG_DIR, file.filename)
    try:
        async with asyncio.Lock(): # Usa un lock per evitare race conditions sulla scrittura
            with open(file_path, "wb") as buffer:
                content = await file.read()
                buffer.write(content)
        return {"message": f"Config file '{file.filename}' uploaded successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not upload file: {e}")

@app.get("/config/list/", summary="Elenca i file di configurazione disponibili")
async def list_config_files():
    """
    Elenca tutti i file di configurazione .seospider disponibili per l'uso.
    """
    try:
        config_files = [f for f in os.listdir(CONFIG_DIR) if f.endswith(".seospider")]
        return {"config_files": config_files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing config files: {e}")
