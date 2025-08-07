from flask import Flask, jsonify, request, render_template
import tensorflow as tf
import numpy as np
import psutil
import datetime
import sqlite3
from ollama_lib import OllamaClient
from scapy.all import sniff
from scapy.layers.inet import IP, TCP, UDP
import ipaddress
import threading
import requests
import re
import os
from collections import deque
from transformers import TFAutoModel, AutoConfig
import GPUtil
from huggingface_hub import hf_hub_download
from flask_socketio import SocketIO, emit
import time
import eventlet

# Clé d'API Groq et en-têtes
GROQ_API_KEY = "gsk_xxx"
GROQ_HEADERS = {
    "Authorization": f"Bearer {GROQ_API_KEY}",
    "Content-Type": "application/json"
}

app = Flask(__name__)
socketio = SocketIO(app)

# Chemin et identifiants du modèle Hugging Face
MODEL_PATH = 'SecIDS-CNN.h5'
MODEL_ID = "Keyven/SecIDS-CNN"
FILENAME = "SecIDS-CNN.h5"

# Remplacez 'your_token_here' par votre token réel
HF_TOKEN = "hf_XXX"

# Vérifier si le modèle est déjà présent localement, sinon le télécharger
if not os.path.exists(MODEL_PATH):
    print("Téléchargement du modèle depuis Hugging Face...")
    try:
        model_file = hf_hub_download(repo_id=MODEL_ID, filename=FILENAME, use_auth_token=HF_TOKEN)
        model = tf.keras.models.load_model(model_file)
        model.save(MODEL_PATH)
        print("Modèle téléchargé et sauvegardé avec succès.")
    except Exception as e:
        print(f"Erreur lors du téléchargement du modèle : {e}")
else:
    print("Chargement du modèle depuis le stockage local...")
    model = tf.keras.models.load_model(MODEL_PATH)
    print("Modèle chargé avec succès depuis le stockage local.")

# Initialiser le client Ollama
ollama_client = OllamaClient(base_url="http://localhost:11434")

def get_db_connection():
    conn = sqlite3.connect('system_metrics.db', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def initialize_database():
    with get_db_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS network_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip TEXT,
                type TEXT,
                country TEXT,
                summary TEXT,
                blacklisted TEXT,
                attacks INTEGER,
                reports INTEGER,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_network_requests_timestamp ON network_requests (timestamp);")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                log TEXT
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs (timestamp);")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                cpu REAL,
                memory REAL,
                disk REAL,
                network INTEGER
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_metrics_timestamp ON metrics (timestamp);")
        conn.commit()

initialize_database()

def get_ip_country(ip):
    try:
        if ":" in ip or ipaddress.ip_address(ip).is_private:
            return "Non vérifiable"
        response = requests.get(f"https://geolocation-db.com/json/{ip}&position=true").json()
        country = response.get("country_name", "Inconnu")
        city = response.get("city", "Inconnu")
        state = response.get("state", "Inconnu")
        return f"{country}, {city}, {state}"
    except (requests.RequestException, ValueError):
        return "Erreur"

MAX_NETWORK_REQUESTS = 1000
network_requests = deque(maxlen=MAX_NETWORK_REQUESTS)

@app.route('/system-info', methods=['GET'])
def system_info():
    try:
        cpu_freq = psutil.cpu_freq().current if psutil.cpu_freq() else 'N/A'
        cpu_cores = psutil.cpu_count(logical=False)
        cpu_usage = psutil.cpu_percent()
        memory = psutil.virtual_memory().total
        disk = psutil.disk_usage('/').total

        gpus = GPUtil.getGPUs()
        if gpus:
            gpu_usage = f"{gpus[0].load * 100:.2f}%"
            gpu_memory_used = f"{gpus[0].memoryUsed} MB"
            gpu_memory_total = f"{gpus[0].memoryTotal} MB"
        else:
            gpu_usage = gpu_memory_used = gpu_memory_total = "N/A"

        battery = psutil.sensors_battery()
        power_usage = battery.percent if battery else 'N/A'

        system_info_data = {
            "cpu_frequency": cpu_freq,
            "cpu_cores": cpu_cores,
            "cpu_usage": cpu_usage,
            "gpu_usage": gpu_usage,
            "gpu_memory_used": gpu_memory_used,
            "gpu_memory_total": gpu_memory_total,
            "power_usage": power_usage,
            "memory_total": memory,
            "disk_total": disk
        }

        print("System Info:", system_info_data)
        return jsonify(system_info_data)

    except Exception as e:
        print("Erreur lors de la récupération des informations système :", e)
        return jsonify({"error": "Erreur lors de la récupération des informations système"}), 500

def analyze_packet_with_cnn(packet_data):
    prediction = model.predict(np.array([packet_data]))[0]
    return "suspect" if prediction[1] > 0.5 else "normal"

def send_system_metrics():
    while True:
        cpu_usage = psutil.cpu_percent()
        memory_usage = psutil.virtual_memory().percent
        disk_usage = psutil.disk_usage('/').percent

        socketio.emit('update_metrics', {
            'cpu_usage': cpu_usage,
            'memory_usage': memory_usage,
            'disk_usage': disk_usage,
            'cpu_frequency': psutil.cpu_freq().current,
            'cpu_cores': psutil.cpu_count(),
            'gpu_usage': 'N/A',
            'gpu_memory_used': 'N/A',
            'gpu_memory_total': 'N/A',
            'power_usage': 'N/A',
            'memory_total': psutil.virtual_memory().total,
            'disk_total': psutil.disk_usage('/').total
        })

        logs = fetch_recent_logs()
        network_data = fetch_recent_network_data()

        payload = {
            "model": "llama3-8b-8192",
            "messages": [
                {"role": "system", "content": f"System metrics : CPU: {cpu_usage}%, RAM: {memory_usage}%, Disque: {disk_usage}%."},
                {"role": "user", "content": f"Logs : {logs}, Réseau : {network_data}"}
            ]
        }

        try:
            response = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=GROQ_HEADERS, json=payload)
            assistant_message = response.json().get("choices", [{}])[0].get("message", {}).get("content", "Pas de réponse")
            save_log(f"Réponse IA : {assistant_message}")
        except requests.RequestException as e:
            print(f"Erreur lors de la requête à Groq : {e}")

        time.sleep(5)

def fetch_recent_logs():
    with get_db_connection() as conn:
        rows = conn.execute("SELECT log FROM logs ORDER BY timestamp DESC LIMIT 5").fetchall()
    return [row["log"] for row in rows]

def fetch_recent_network_data():
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT ip, country, summary FROM network_requests ORDER BY timestamp DESC LIMIT 5"
        ).fetchall()
    return [{"ip": r["ip"], "country": r["country"], "summary": r["summary"]} for r in rows]

@socketio.on('connect')
def handle_connect():
    print("Client connecté")
    socketio.start_background_task(send_system_metrics)

@socketio.on('new_log')
def handle_new_log(log_data):
    socketio.emit('new_log', log_data)

@socketio.on('new_network_request')
def handle_new_network_request(network_data):
    socketio.emit('new_network_request', network_data)

def packet_callback(packet):
    if packet.haslayer(IP) and (packet.haslayer(TCP) or packet.haslayer(UDP)):
        ip = packet[IP].src
        summary = packet.summary()

        excluded_ips = {"144.76.114.3", "159.89.102.253"}
        if ip in excluded_ips or ipaddress.ip_address(ip).is_private or ":" in ip:
            country = "Locale/IPv6 ou exclue"
            is_blacklisted = False
            attacks = reports = 0
        else:
            country = get_ip_country(ip)
            status = check_ip_blacklist_cached(ip)
            is_blacklisted = status["blacklisted"]
            attacks = status["attacks"]
            reports = status["reports"]

        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO network_requests (ip, type, country, summary, blacklisted, attacks, reports) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ip, "IPv4", country, summary, "Oui" if is_blacklisted else "Non", attacks, reports)
            )
            conn.commit()

        log_message = f"Paquet réseau de {ip} ({country}) - Blacklisté : {is_blacklisted}"
        save_log(log_message)
        if is_blacklisted:
            notify_ai(log_message)

@app.route('/logs', methods=['GET'])
def get_logs():
    page = int(request.args.get('page', 1))
    page_size = 50
    offset = (page - 1) * page_size
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT timestamp, log FROM logs ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            (page_size, offset)
        ).fetchall()
    return jsonify([{"timestamp": r["timestamp"], "log": r["log"]} for r in rows])

@app.route('/search-logs', methods=['POST'])
def search_logs():
    search_term = request.json.get('query', '')
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT timestamp, log FROM logs WHERE log LIKE ? ORDER BY timestamp DESC",
            ('%' + search_term + '%',)
        ).fetchall()
    return jsonify([{"timestamp": r["timestamp"], "log": r["log"]} for r in rows])

def save_metrics(cpu, memory, disk, network):
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO metrics (timestamp, cpu, memory, disk, network) VALUES (?, ?, ?, ?, ?)",
            (datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), cpu, memory, disk, network)
        )
        conn.commit()

def save_log(log):
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO logs (timestamp, log) VALUES (?, ?)",
            (datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), log)
        )
        conn.commit()

def notify_ai(message):
    short_prompt = f"{message}\nRéponds succinctement, 1 à 2 phrases maximum."
    response = ollama_client.generate(prompt=short_prompt)
    save_log(f"Notification IA : {response}")

def analyze_metrics(cpu, memory, disk):
    if cpu > 85 or memory > 80 or disk > 90:
        message = f"Alerte : Charge système élevée - CPU : {cpu}%, RAM : {memory}%, Disque : {disk}%."
        notify_ai(message)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/server-status', methods=['GET'])
def server_status():
    cpu = psutil.cpu_percent(interval=1)
    memory = psutil.virtual_memory().percent
    disk = psutil.disk_usage('/').percent

    print(f"CPU: {cpu}, Memory: {memory}, Disk: {disk}")

    save_metrics(cpu, memory, disk, 0)
    analyze_metrics(cpu, memory, disk)

    return jsonify({
        "cpu_usage": cpu,
        "memory_usage": memory,
        "disk_usage": disk
    })

def check_ip_blacklist_cached(ip):
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT blacklisted, attacks, reports FROM network_requests WHERE ip = ?",
            (ip,)
        ).fetchone()
        if row:
            return {
                "blacklisted": row["blacklisted"] == "Oui",
                "attacks": row["attacks"],
                "reports": row["reports"]
            }

        url = f"http://api.blocklist.de/api.php?ip={ip}&format=json"
        try:
            response = requests.get(url)
            data = response.json() if response.status_code == 200 else {}
            attacks = data.get("attacks", 0)
            blacklisted = attacks > 0
            reports = data.get("reports", 0)

            conn.execute(
                "INSERT INTO network_requests (ip, blacklisted, attacks, reports) VALUES (?, ?, ?, ?)",
                (ip, "Oui" if blacklisted else "Non", attacks, reports)
            )
            conn.commit()

            return {"blacklisted": blacklisted, "attacks": attacks, "reports": reports}
        except requests.RequestException:
            return {"blacklisted": False, "attacks": 0, "reports": 0}

def extract_ip_from_message(message):
    ip_pattern = r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b'
    match = re.search(ip_pattern, message)
    return match.group(0) if match else None

def initialize_groq_client():
    return {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

@app.route('/chat', methods=['POST'])
def chat_with_groq():
    data = request.get_json()
    user_message = data.get('message', '')

    cpu = psutil.cpu_percent(interval=1)
    memory = psutil.virtual_memory().percent
    disk = psutil.disk_usage('/').percent

    logs = fetch_recent_logs()
    network_data = fetch_recent_network_data()

    context_message = (
        f"{user_message}\n"
        f"Metrics système : CPU: {cpu}%, mémoire: {memory}%, disque: {disk}%.\n"
        f"Logs : {logs}, réseau : {network_data}\n"
        "Réponds succinctement."
    )

    payload = {
        "model": "llama3-8b-8192",
        "messages": [{"role": "user", "content": context_message}]
    }

    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=GROQ_HEADERS, json=payload
        )
        assistant_message = response.json().get("choices", [{}])[0].get("message", {}).get("content", "Pas de réponse")
    except requests.RequestException as e:
        print("Erreur lors de la requête à Groq :", e)
        assistant_message = f"Erreur lors de la requête à Groq : {e}"

    save_log(f"Utilisateur : {user_message}, IA : {assistant_message}")
    return jsonify({"response": assistant_message})

@app.route('/network-requests', methods=['GET'])
def get_network_requests():
    try:
        page = int(request.args.get('page', 1))
        page_size = 50
        offset = (page - 1) * page_size
        with get_db_connection() as conn:
            rows = conn.execute(
                "SELECT ip, type, country, summary, blacklisted, attacks, reports, timestamp "
                "FROM network_requests ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                (page_size, offset)
            ).fetchall()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        print(f"Erreur lors de la récupération des requêtes réseau : {e}")
        return jsonify({"error": "Erreur lors de la récupération des requêtes réseau"}), 500

def start_sniffing():
    sniff(prn=packet_callback, store=0)

if __name__ == '__main__':
    threading.Thread(target=start_sniffing, daemon=True).start()
    app.run(debug=True, port=5000, use_reloader=False)
