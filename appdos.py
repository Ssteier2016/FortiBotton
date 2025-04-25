import eventlet
eventlet.monkey_patch()
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import time
from threading import Lock, Thread
from collections import deque
import sqlite3
import mercadopago
import smtplib
from email.mime.text import MIMEText
import random
import base64
import logging
import requests
import os

app = Flask(__name__, template_folder='templates')
CORS(app)
socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins="*")
thread_lock = Lock()

# Configuración de Mercado Pago
sdk = mercadopago.SDK("APP_USR-44493711284061-030923-7fd16a9d7e9c28d5cfec9eaa4be42df8-320701222")
FOUNDER_USER_ID = "320701222"
ACCESS_TOKEN = "APP_USR-44493711284061-030923-7fd16a9d7e9c28d5cfec9eaa4be42df8-320701222"
NGROK_URL = os.environ.get("NGROK_URL", "https://fortigame.onrender.com")

# Configuración de Email
EMAIL = os.environ.get("SMTP_USER", "rod.arena7@gmail.com")
PASSWORD = os.environ.get("SMTP_PASSWORD", "fwwxtandjsxtrwrz")

# Configuración de Telegram
TELEGRAM_TOKEN = "7961738160:AAFs9T1_55PW1JsvRwiRHo4oUy1vN_NbgSg"
TELEGRAM_ADMIN_CHAT_ID = "1624130940"

# Configuración de logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Estado del juego
players = {}
online_players = set()
last_press_time = 0
pool = 0
game_active = False
last_press_sid = None
last_winners = deque(maxlen=10)
verification_codes = {}
chat_history = deque(maxlen=50)

# Funciones de base de datos envueltas en tpool
def execute_db_operation(func, *args):
    return eventlet.tpool.execute(func, *args)

def init_db_blocking():
    conn = sqlite3.connect('forti_quest.db')
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='players'")
    table_exists = c.fetchone()
    if table_exists:
        c.execute("PRAGMA table_info(players)")
        columns = [col[1] for col in c.fetchall()]
        expected_columns = ['sid', 'username', 'name', 'phone', 'password', 'forti', 'last_press', 'pool', 'telegram_id', 'cvu', 'last_payment_id', 'email']
        if not all(col in columns for col in expected_columns):
            logger.info("Esquema de la tabla 'players' incorrecto. Recreando...")
            c.execute("DROP TABLE players")
            table_exists = False
    if not table_exists:
        c.execute('''CREATE TABLE players 
                     (sid TEXT PRIMARY KEY, username TEXT UNIQUE, name TEXT, phone TEXT, password TEXT, 
                      forti INTEGER, last_press REAL, pool INTEGER DEFAULT 0, telegram_id TEXT, cvu TEXT, 
                      last_payment_id TEXT, email TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS transactions 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, sid TEXT, type TEXT, amount REAL, 
                  status TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS winners 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, sid TEXT, username TEXT, prize INTEGER, 
                  timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS game_state 
                 (key TEXT PRIMARY KEY, value INTEGER)''')
    c.execute("INSERT OR IGNORE INTO game_state (key, value) VALUES ('pool', 1000)")
    conn.commit()
    conn.close()

def init_db():
    execute_db_operation(init_db_blocking)

def load_game_state_blocking():
    global pool
    conn = sqlite3.connect('forti_quest.db')
    c = conn.cursor()
    c.execute("SELECT value FROM game_state WHERE key = 'pool'")
    result = c.fetchone()
    pool = result[0] if result else 1000
    conn.close()

def load_game_state():
    execute_db_operation(load_game_state_blocking)

def save_game_state_blocking():
    conn = sqlite3.connect('forti_quest.db')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO game_state (key, value) VALUES ('pool', ?)", (pool,))
    conn.commit()
    conn.close()

def save_game_state():
    execute_db_operation(save_game_state_blocking)

def load_players_from_db_blocking():
    global players
    conn = sqlite3.connect('forti_quest.db')
    c = conn.cursor()
    c.execute("SELECT sid, username, name, phone, password, forti, last_press, pool, telegram_id, cvu, last_payment_id, email FROM players")
    for row in c.fetchall():
        players[row[0]] = {
            'username': row[1], 'name': row[2], 'phone': row[3], 'password': row[4],
            'forti': row[5], 'last_press': row[6], 'pool': row[7],
            'telegram_id': row[8], 'cvu': row[9], 'last_payment_id': row[10], 'email': row[11]
        }
    conn.close()

def load_players_from_db():
    execute_db_operation(load_players_from_db_blocking)

def save_player_blocking(sid, username, name, phone, password, forti, last_press, pool, telegram_id=None, cvu=None, last_payment_id=None, email=None):
    conn = sqlite3.connect('forti_quest.db')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO players (sid, username, name, phone, password, forti, last_press, pool, telegram_id, cvu, last_payment_id, email) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
              (sid, username, name, phone, password, forti, last_press, pool, telegram_id, cvu, last_payment_id, email))
    conn.commit()
    conn.close()

def save_player(sid, username, name, phone, password, forti, last_press, pool, telegram_id=None, cvu=None, last_payment_id=None, email=None):
    execute_db_operation(save_player_blocking, sid, username, name, phone, password, forti, last_press, pool, telegram_id, cvu, last_payment_id, email)

def update_player_in_db(sid, username, name, phone, password, forti, last_press, pool, telegram_id=None, cvu=None, last_payment_id=None, email=None):
    save_player(sid, username, name, phone, password, forti, last_press, pool, telegram_id, cvu, last_payment_id, email)

def save_transaction_blocking(sid, type, amount, status):
    conn = sqlite3.connect('forti_quest.db')
    c = conn.cursor()
    c.execute("INSERT INTO transactions (sid, type, amount, status) VALUES (?, ?, ?, ?)",
              (sid, type, amount, status))
    conn.commit()
    conn.close()

def save_transaction(sid, type, amount, status):
    execute_db_operation(save_transaction_blocking, sid, type, amount, status)

def save_winner_blocking(sid, username, prize):
    conn = sqlite3.connect('forti_quest.db')
    c = conn.cursor()
    c.execute("INSERT INTO winners (sid, username, prize) VALUES (?, ?, ?)", (sid, username, prize))
    conn.commit()
    conn.close()

def save_winner(sid, username, prize):
    execute_db_operation(save_winner_blocking, sid, username, prize)

# Funciones de notificación envueltas en tpool
def send_withdrawal_email_blocking(username, name, amount, cvu):
    subject = f"Solicitud de Retiro - {username}"
    body = f"El jugador {username} ({name}) ha solicitado un retiro de {amount} Forti.\nCVU/CBU/Alias: {cvu}\nPor favor, procesa el retiro manualmente."
    msg = MIMEText(body, 'plain', 'utf-8')
    msg['Subject'] = subject
    msg['From'] = EMAIL
    msg['To'] = EMAIL
    with smtplib.SMTP('smtp.gmail.com', 587) as server:
        server.starttls()
        server.login(EMAIL, PASSWORD)
        server.send_message(msg)
    logger.info(f"Email enviado para retiro de {username} por {amount} Forti a {EMAIL}")

def send_withdrawal_email(username, name, amount, cvu):
    try:
        eventlet.tpool.execute(send_withdrawal_email_blocking, username, name, amount, cvu)
    except Exception as e:
        logger.error(f"Error al enviar email desde {EMAIL}: {e}")
        raise

def send_telegram_message_blocking(chat_id, message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": message}
    response = requests.post(url, json=payload)
    response.raise_for_status()
    logger.info(f"Mensaje enviado a Telegram: {message} a chat_id {chat_id}")

def send_telegram_message(chat_id, message):
    try:
        eventlet.tpool.execute(send_telegram_message_blocking, chat_id, message)
    except Exception as e:
        logger.error(f"Error al enviar mensaje a Telegram: {e}")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/generate_payment_link', methods=['POST'])
def generate_payment_link():
    sid = request.json.get('sid')
    amount = request.json.get('amount')
    if not sid or sid not in players:
        return jsonify({'error': 'Jugador no encontrado'}), 400
    if not amount or amount < 1:
        return jsonify({'error': 'Monto inválido'}), 400
    preference_data = {
        "items": [{"title": f"Recarga de {amount} Forti", "quantity": 1, "currency_id": "ARS", "unit_price": float(amount)}],
        "external_reference": sid,
        "notification_url": f"{NGROK_URL}/webhook"
    }
    response = sdk.preference().create(preference_data)
    if "response" in response and "init_point" in response["response"]:
        return jsonify({'payment_link': response["response"]["init_point"]})
    return jsonify({'error': 'No se pudo generar el enlace de pago'}), 500

@app.route('/create_payment', methods=['POST'])
def create_payment():
    sid = request.json.get('sid')
    amount = request.json.get('amount', 100)
    if not sid or sid not in players:
        return jsonify({'error': 'Jugador no encontrado'}), 400
    if players[sid]['forti'] < amount:
        return jsonify({'error': f'No tienes suficientes Forti ({amount} requeridos)'})
    transaction_id = f"{sid}_{int(time.time())}"
    preference = {
        "items": [{"title": f"Recarga de {amount} Forti", "quantity": 1, "currency_id": "ARS", "unit_price": float(amount)}],
        "notification_url": f"{NGROK_URL}/webhook",
        "external_reference": transaction_id
    }
    response = sdk.preference().create(preference)
    if "response" in response and "id" in response["response"]:
        return jsonify({'preference_id': response["response"]["id"]})
    return jsonify({'error': 'No se pudo crear el pago'}), 500

@app.route('/ipn', methods=['POST'])
def ipn():
    data = request.json
    if not data or 'data' not in data or 'id' not in data['data']:
        return '', 200
    payment_id = data['data']['id']
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    def fetch_payment_blocking():
        return requests.get(f"https://api.mercadopago.com/v1/payments/{payment_id}", headers=headers).json()
    payment_info = eventlet.tpool.execute(fetch_payment_blocking)
    if payment_info.get("status") == "approved":
        sid = payment_info.get("external_reference")
        amount = payment_info.get("transaction_amount")
        with thread_lock:
            if sid in players:
                players[sid]['forti'] += int(amount)
                update_player_in_db(sid, players[sid]['username'], players[sid]['name'], 
                                  players[sid]['phone'], players[sid]['password'], 
                                  players[sid]['forti'], players[sid]['last_press'], 
                                  players[sid]['pool'], players[sid].get('telegram_id'), 
                                  players[sid].get('cvu'), payment_id, players[sid].get('email'))
                save_transaction(sid, "deposit", amount, "completed")
                socketio.emit('update_forti', {'forti': players[sid]['forti'], 'sid': sid}, room=sid)
    return '', 200

@app.route('/webhook', methods=['POST', 'GET'])
def webhook():
    try:
        if request.method == 'POST':
            data = request.get_json(silent=True)
            if data and 'data' in data and 'id' in data['data']:
                payment_id = data['data']['id']
                logger.info(f"Webhook JSON recibido: payment_id={payment_id}")
            else:
                return jsonify({'status': 'ignored'}), 200
        else:
            payment_id = request.args.get('id') or request.args.get('data.id')
            topic = request.args.get('topic') or request.args.get('type')
            logger.info(f"Webhook URL recibido: id={payment_id}, topic={topic}")
            if not payment_id or topic != 'payment':
                return jsonify({'status': 'ignored'}), 200

        payment = sdk.payment().get(payment_id)
        if "response" not in payment:
            logger.error(f"Error al consultar pago {payment_id}: {payment}")
            return jsonify({'status': 'error', 'message': 'Error al consultar el pago'}), 500
        
        payment_response = payment["response"]
        payment_status = payment_response.get("status")
        external_ref = payment_response.get("external_reference")
        amount = payment_response.get("transaction_amount")
        
        if not all([payment_status, external_ref, amount]):
            logger.error(f"Datos incompletos: status={payment_status}, external_ref={external_ref}, amount={amount}")
            return jsonify({'status': 'error', 'message': 'Datos incompletos'}), 500
        
        sid = external_ref.split('_')[0] if '_' in external_ref else external_ref
        
        if payment_status == 'approved' and sid in players:
            with thread_lock:
                players[sid]['forti'] += int(amount)
                update_player_in_db(sid, players[sid]['username'], players[sid]['name'], 
                                  players[sid]['phone'], players[sid]['password'], 
                                  players[sid]['forti'], players[sid]['last_press'], 
                                  players[sid]['pool'], players[sid].get('telegram_id'), 
                                  players[sid].get('cvu'), payment_id, players[sid].get('email'))
                save_transaction(sid, "deposit", amount, "completed")
            socketio.emit('update_forti', {'forti': players[sid]['forti'], 'sid': sid}, room=sid)
            logger.info(f"Pago aprobado: SID={sid}, Forti añadidos={amount}")
            return jsonify({'status': 'success'}), 200
        
        logger.info(f"Pago ignorado: status={payment_status}, SID={sid}")
        return jsonify({'status': 'ignored'}), 200
    except Exception as e:
        logger.error(f"Error en el webhook: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/test_recharge', methods=['POST'])
def test_recharge():
    sid = request.json.get('sid')
    amount = request.json.get('amount', 200)
    if sid in players:
        with thread_lock:
            players[sid]['forti'] += amount
            update_player_in_db(sid, players[sid]['username'], players[sid]['name'], 
                              players[sid]['phone'], players[sid]['password'], 
                              players[sid]['forti'], players[sid]['last_press'], 
                              players[sid]['pool'], players[sid].get('telegram_id'), 
                              players[sid].get('cvu'), players[sid].get('last_payment_id'), 
                              players[sid].get('email'))
        emit('update_forti', {'forti': players[sid]['forti'], 'sid': sid}, room=sid)
        logger.info(f"Recarga de prueba: SID={sid}, Forti añadidos={amount}")
        return jsonify({'status': 'success'}), 200
    return jsonify({'error': 'Jugador no encontrado'}), 400

@app.route('/notificacion_pago', methods=['POST'])
def notificacion_pago():
    data = request.get_json()
    logger.info(f"Notificación recibida: {data}")
    return jsonify({"status": "ok"}), 200

@app.route('/transactions', methods=['GET'])
def get_transactions():
    sid = request.args.get('sid')
    if not sid or sid not in players:
        return jsonify({'error': 'Jugador no encontrado'}), 400
    def fetch_transactions_blocking():
        conn = sqlite3.connect('forti_quest.db')
        c = conn.cursor()
        c.execute("SELECT type, amount, status, timestamp FROM transactions WHERE sid = ? ORDER BY timestamp DESC", (sid,))
        transactions = [{'type': row[0], 'amount': row[1], 'status': row[2], 'timestamp': row[3]} for row in c.fetchall()]
        conn.close()
        return transactions
    transactions = execute_db_operation(fetch_transactions_blocking)
    return jsonify({'transactions': transactions})

@app.route('/update_cvu', methods=['POST'])
def update_cvu():
    data = request.get_json()
    sid = data.get('sid')
    cvu = data.get('cvu')
    email = data.get('email')
    if not sid or sid not in players:
        return jsonify({'error': 'Jugador no encontrado'}), 400
    if not cvu or len(cvu) < 5:
        return jsonify({'error': 'CVU/CBU/Alias inválido'}), 400
    if not email:
        return jsonify({'error': 'Email requerido'}), 400
    with thread_lock:
        player = players[sid]
        update_player_in_db(sid, player['username'], player['name'], player['phone'], 
                          player['password'], player['forti'], player['last_press'], 
                          player['pool'], player.get('telegram_id'), cvu, 
                          player.get('last_payment_id'), email)
        players[sid]['cvu'] = cvu
        players[sid]['email'] = email
    return jsonify({'success': True, 'message': 'CVU/CBU/Alias y email actualizados'})

@app.route('/withdraw', methods=['POST'])
def withdraw():
    data = request.get_json()
    sid = data.get('sid')
    amount = data.get('amount')
    logger.info(f"Intento de retiro: SID={sid}, Monto={amount}")
    if not sid or sid not in players:
        return jsonify({"success": False, "message": "Usuario no encontrado"}), 400
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "Monto inválido"}), 400
    if amount <= 0:
        return jsonify({"success": False, "message": "Monto inválido"}), 400
    with thread_lock:
        player = players[sid]
        if player['forti'] < amount:
            return jsonify({"success": False, "message": "Fondos insuficientes"}), 400
        if not player.get('cvu'):
            return jsonify({"success": False, "message": "Debes configurar tu CVU/CBU/Alias primero"}), 400
        player['forti'] -= amount
        update_player_in_db(sid, player['username'], player['name'], player['phone'], 
                          player['password'], player['forti'], player['last_press'], 
                          player['pool'], player.get('telegram_id'), player['cvu'], 
                          player.get('last_payment_id'), player.get('email'))
        save_transaction(sid, "withdrawal", amount, "pending")
        try:
            send_withdrawal_email(player['username'], player['name'], amount, player['cvu'])
            telegram_msg = f"Retiro solicitado por {player['username']} ({player['name']}):\nMonto: ${amount}\nCVU: {player['cvu']}"
            send_telegram_message(TELEGRAM_ADMIN_CHAT_ID, telegram_msg)
        except Exception as e:
            logger.error(f"Fallo al notificar retiro: {e}")
            save_transaction(sid, "withdrawal", amount, "failed")
            return jsonify({"success": False, "message": "Error al procesar notificaciones del retiro"}), 500
        socketio.emit('update_forti', {'forti': player['forti'], 'sid': sid}, room=sid)
    return jsonify({"success": True, "message": "Retiro solicitado, será procesado en 1-2 días", "amount": amount})

@app.route('/v2', methods=['POST'])
def verify_code():
    data = request.get_json()
    sid = data.get('sid')
    code = data.get('code')
    logger.debug(f"Procesando /v2: SID={sid}, Código={code}")
    if not sid or not code:
        return jsonify({"success": False, "message": "Falta SID o código"}), 400
    if sid in verification_codes and verification_codes[sid] == code:
        with thread_lock:
            player = players[sid]
            save_player(sid, player['username'], player['name'], player['phone'], 
                       player['password'], player['forti'], player['last_press'], 
                       player['pool'], player.get('telegram_id'), player.get('cvu'), 
                       player.get('last_payment_id'), player.get('email'))
            player['forti'] = 1000
            update_player_in_db(sid, player['username'], player['name'], player['phone'], 
                               player['password'], player['forti'], player['last_press'], 
                               player['pool'], player.get('telegram_id'), player.get('cvu'), 
                               player.get('last_payment_id'), player.get('email'))
            online_players.add(sid)
            del verification_codes[sid]
        logger.debug("/v2 completado")
        return jsonify({"success": True, "username": player['username']})
    logger.debug("/v2 fallido: Código inválido")
    return jsonify({"success": False, "message": "Código inválido"}), 400

@app.route('/winners', methods=['GET'])
def get_winners():
    def fetch_winners_blocking():
        conn = sqlite3.connect('forti_quest.db')
        c = conn.cursor()
        c.execute("SELECT username, prize, timestamp FROM winners ORDER BY timestamp DESC LIMIT 5")
        winners = [{'username': row[0], 'prize': row[1], 'timestamp': row[2]} for row in c.fetchall()]
        conn.close()
        return winners
    winners = execute_db_operation(fetch_winners_blocking)
    return jsonify({'winners': winners})

@socketio.on('connect')
def handle_connect():
    sid = request.sid
    with thread_lock:
        if sid not in players:
            players[sid] = {'username': '', 'name': '', 'phone': '', 'password': '', 'forti': 1000, 
                           'last_press': 0, 'pool': 0, 'telegram_id': None, 'cvu': None, 
                           'last_payment_id': None, 'email': None}
        online_players.add(sid)
    emit('update_pool', {'pool': pool})
    emit('update_forti', {'forti': players[sid]['forti'], 'sid': sid})
    socketio.emit('update_online_players', {'online_players': [{'sid': sid, 'name': players[sid]['name']} for sid in online_players if players[sid]['name']]})
    emit('chat_history', {'messages': list(chat_history)}, room=sid)
    logger.info(f"Jugador conectado: SID={sid}")

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    with thread_lock:
        if sid in online_players:
            online_players.remove(sid)
            socketio.emit('update_online_players', {'online_players': [{'sid': s, 'name': players[s]['name']} for s in online_players if players[s]['name']]})
    logger.info(f"Jugador desconectado: SID={sid}")

@socketio.on('logout')
def handle_logout():
    sid = request.sid
    with thread_lock:
        if sid in online_players:
            online_players.remove(sid)
        if sid in players:
            players[sid]['username'] = ''
            players[sid]['name'] = ''
    socketio.emit('update_online_players', {'online_players': [{'sid': s, 'name': players[s]['name']} for s in online_players if players[s]['name']]})
    emit('logout_result', {'success': True}, room=sid)
    logger.info(f"Jugador cerró sesión: SID={sid}")

@socketio.on('login')
def handle_login(data):
    username = data.get('username')
    password = data.get('password')
    sid = request.sid
    def login_blocking():
        conn = sqlite3.connect('forti_quest.db')
        c = conn.cursor()
        c.execute("SELECT sid, username, name, phone, password, forti, last_press, pool, telegram_id, cvu, last_payment_id, email FROM players WHERE username = ? AND password = ?", (username, password))
        user = c.fetchone()
        conn.close()
        return user
    user = execute_db_operation(login_blocking)
    if user:
        with thread_lock:
            players[sid] = {
                'username': user[1], 'name': user[2], 'phone': user[3], 'password': user[4],
                'forti': user[5], 'last_press': user[6], 'pool': user[7],
                'telegram_id': user[8], 'cvu': user[9], 'last_payment_id': user[10], 'email': user[11]
            }
            if sid not in online_players and players[sid]['name']:
                online_players.add(sid)
        emit('login_result', {"success": True, "username": username}, room=sid)
        emit('update_forti', {'forti': players[sid]['forti'], 'sid': sid}, room=sid)
        socketio.emit('update_online_players', {'online_players': [{'sid': s, 'name': players[s]['name']} for s in online_players if players[s]['name']]})
        logger.info(f"Inicio de sesión exitoso: SID={sid}, Username={username}")
    else:
        emit('login_result', {"success": False, "message": "Usuario o contraseña incorrectos"}, room=sid)
        logger.info(f"Inicio de sesión fallido: SID={sid}, Username={username}")

@socketio.on('register')
def handle_register(data):
    username = data.get('username')
    name = data.get('name', '').strip()
    phone = data.get('phone', '').strip()
    password = data.get('password')
    telegram_id = data.get('telegram_id')
    email = data.get('email', '').strip()
    sid = request.sid
    logger.info(f"Intento de registro: SID={sid}, Username={username}, Name={name}, Phone={phone}, Telegram={telegram_id}, Email={email}")
    
    def check_user_blocking():
        conn = sqlite3.connect('forti_quest.db')
        c = conn.cursor()
        c.execute("SELECT * FROM players WHERE username = ?", (username,))
        existing_user = c.fetchone()
        c.execute("SELECT * FROM players WHERE telegram_id = ?", (telegram_id,))
        existing_telegram = c.fetchone()
        conn.close()
        return existing_user, existing_telegram
    
    existing_user, existing_telegram = execute_db_operation(check_user_blocking)
    if existing_user:
        emit('register_result', {"success": False, "message": "Usuario ya existe"}, room=sid)
        logger.info(f"Registro fallido: SID={sid}, Username={username}, Motivo=Usuario ya existe")
        return
    if not telegram_id:
        emit('register_result', {"success": False, "message": "Debes proporcionar tu ID de Telegram"}, room=sid)
        return
    if existing_telegram:
        emit('register_result', {"success": False, "message": "Este ID de Telegram ya está registrado"}, room=sid)
        return
    
    verification_code = str(random.randint(1000, 9999))
    verification_codes[sid] = verification_code
    
    message = f"Tu código de verificación para Forti Quest es: {verification_code}"
    send_telegram_message(telegram_id, message)
    
    with thread_lock:
        players[sid] = {'username': username, 'name': name, 'phone': phone, 'password': password, 
                        'forti': 0, 'last_press': 0, 'pool': 0, 'telegram_id': telegram_id, 
                        'cvu': None, 'last_payment_id': None, 'email': email}
    emit('register_result', {"success": True, "message": "Revisa tu Telegram para el código de verificación", 
                            "verificationCode": verification_code, "phone": phone}, room=sid)
    logger.info(f"Código de verificación {verification_code} enviado a Telegram {telegram_id} para SID: {sid}")

@socketio.on('verify_account')
def handle_verify_account(data):
    sid = data.get('sid')
    code = data.get('code')
    logger.info(f"Intento de verificación: SID={sid}, Código esperado={verification_codes.get(sid)}")
    if sid in verification_codes and verification_codes[sid] == code:
        with thread_lock:
            player = players[sid]
            save_player(sid, player['username'], player['name'], player['phone'], 
                       player['password'], player['forti'], player['last_press'], 
                       player['pool'], player.get('telegram_id'), player.get('cvu'), 
                       player.get('last_payment_id'), player.get('email'))
            player['forti'] = 1000
            update_player_in_db(sid, player['username'], player['name'], player['phone'], 
                              player['password'], player['forti'], player['last_press'], 
                              player['pool'], player.get('telegram_id'), player.get('cvu'), 
                              player.get('last_payment_id'), player.get('email'))
            online_players.add(sid)
            del verification_codes[sid]
        emit('verify_result', {"success": True, "username": player['username']}, room=sid)
        emit('update_forti', {'forti': player['forti'], 'sid': sid}, room=sid)
        socketio.emit('update_online_players', {'online_players': [{'sid': s, 'name': players[s]['name']} for s in online_players if players[s]['name']]})
        logger.info(f"Verificación exitosa: SID={sid}, Username={player['username']}")
    else:
        emit('verify_result', {"success": False, "message": "Código incorrecto o expirado"}, room=sid)
        logger.info(f"Verificación fallida: SID={sid}")

@socketio.on('press_button')
def handle_press_button():
    global last_press_time, pool, game_active, last_press_sid
    sid = request.sid
    with thread_lock:
        if sid not in players or not players[sid].get('username'):
            emit('error', {'message': 'Debes registrarte e iniciar sesión primero'})
            return
        if players[sid].get('forti', 0) < 100:
            emit('error', {'message': 'No tienes suficientes Forti (100 requeridos)'})
            return
        players[sid]['forti'] -= 100
        pool += 100
        last_press_sid = sid
        last_press_time = time.time()
        game_active = True
        players[sid]['last_press'] = last_press_time
        update_player_in_db(sid, players[sid]['username'], players[sid]['name'], 
                          players[sid]['phone'], players[sid]['password'], 
                          players[sid]['forti'], last_press_time, 
                          players[sid]['pool'], players[sid].get('telegram_id'), 
                          players[sid].get('cvu'), players[sid].get('last_payment_id'), 
                          players[sid].get('email'))
    emit('update_pool', {'pool': pool}, broadcast=True)
    emit('update_forti', {'forti': players[sid]['forti'], 'sid': sid}, broadcast=True)
    emit('button_pressed', {'sid': sid, 'name': players[sid]['name']}, broadcast=True)
    emit('reset_timer', {'initial_time': 240}, broadcast=True)
    save_game_state()

@socketio.on('timer_expired')
def handle_timer_expired():
    global last_press_time, pool, game_active, last_press_sid, players, last_winners
    with thread_lock:
        if game_active and last_press_sid and last_press_sid in players:
            winner_forti = int(pool * 0.9)
            founder_forti = int(pool * 0.09)
            next_pool = int(pool * 0.01)
            players[last_press_sid]['forti'] += winner_forti
            players[last_press_sid]['pool'] = next_pool
            pool = next_pool
            logger.info(f"Comisión simulada al fundador: ${founder_forti} para FOUNDER_USER_ID={FOUNDER_USER_ID}")
            last_winners.append({'sid': last_press_sid, 'name': players[last_press_sid]['name'], 'prize': winner_forti})
            save_winner(last_press_sid, players[last_press_sid]['username'], winner_forti)
            socketio.emit('game_over', {'winner_sid': last_press_sid, 'winner_name': players[last_press_sid]['name'], 
                                       'prize': winner_forti, 'pool': pool})
            socketio.emit('update_forti', {'forti': players[last_press_sid]['forti'], 'sid': last_press_sid})
            socketio.emit('update_pool', {'pool': pool})
            socketio.emit('update_winners', {'winners': list(last_winners)})
            socketio.emit('reset_timer', {'initial_time': 0})
            game_active = False
            last_press_sid = None
    save_game_state()

@socketio.on('send_message')
def handle_send_message(data):
    sid = request.sid
    message = data.get('message', '').strip()
    message_type = data.get('type', 'text')
    logger.info(f"Procesando mensaje: SID={sid}, Type={message_type}, Message={message[:20]}...")
    if sid not in players or not players[sid].get('username'):
        emit('chat_error', {'message': 'Debes iniciar sesión para enviar mensajes'}, room=sid)
        return
    if not message:
        emit('chat_error', {'message': 'El mensaje no puede estar vacío'}, room=sid)
        return
    chat_message = {'username': players[sid]['username'], 'message': message, 'type': message_type}
    with thread_lock:
        chat_history.append(chat_message)
    socketio.emit('new_message', chat_message, broadcast=True)
    logger.info(f"Mensaje enviado: {chat_message}")

@socketio.on('some_game_event')
def handle_game_event(data):
    sid = request.sid
    if sid in players:
        prize = 1000
        save_winner(sid, players[sid]['username'], prize)

def game_loop():
    global last_press_time, game_active, last_press_sid
    while True:
        socketio.sleep(1)
        if game_active and last_press_time > 0:
            elapsed = time.time() - last_press_time
            if elapsed >= 240:
                with thread_lock:
                    if game_active and last_press_sid and last_press_sid in players:
                        socketio.emit('timer_expired', {})
                        logger.info("Temporizador expiró, forzando timer_expired")
                last_press_time = 0

if __name__ == '__main__':
    load_players_from_db()
    load_game_state()
    port = int(os.environ.get("PORT", 5000))
    game_thread = Thread(target=game_loop, daemon=True)
    game_thread.start()
    socketio.run(app, host='0.0.0.0', port=port, debug=True)
