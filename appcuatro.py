from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
import time
from threading import Lock, Thread
from collections import deque
import sqlite3
from mercadopago import SDK

app = Flask(__name__, template_folder='templates')
socketio = SocketIO(app, async_mode='threading')
thread_lock = Lock()

# Configuración de Mercado Pago
mp = SDK("TEST-44493711284061-030923-0d8c10ba1485ca86a11efda3fc48d68f-320701222")

# Estado del juego
players = {}
timer = 240  # Tiempo inicial en segundos
pool = 0
game_active = False
last_press_sid = None
last_winners = deque(maxlen=5)

# Inicialización de la base de datos
def init_db():
    conn = sqlite3.connect('forti_quest.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS players (sid TEXT PRIMARY KEY, name TEXT, forti INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS winners (id INTEGER PRIMARY KEY AUTOINCREMENT, sid TEXT, name TEXT, prize REAL, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

init_db()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/create_payment', methods=['POST'])
def create_payment():
    sid = request.json.get('sid')
    if not sid or sid not in players:
        return jsonify({'error': 'Jugador no encontrado'}), 400

    preference = {
        "items": [
            {
                "title": "Forti Recarga (1000 Forti)",
                "quantity": 1,
                "currency_id": "ARS",
                "unit_price": 10.0
            }
        ],
        "back_urls": {
            "success": "http://127.0.0.1:5000/",
            "failure": "http://127.0.0.1:5000/",
            "pending": "http://127.0.0.1:5000/"
        },
        "auto_return": "approved",
        "notification_url": "https://9847-2800-810-497-1380-3d1b-a17f-23b-39c9.ngrok-free.app",
        "external_reference": sid
    }
    response = mp.preference().create(preference)
    preference_id = response["response"]["id"]
    return jsonify({'preference_id': preference_id, 'init_point': response["response"]["init_point"]})

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if not data or 'id' not in data:
        return jsonify({'status': 'ignored'}), 200

    payment_id = data.get('id')
    payment = mp.payment().get(payment_id)
    payment_status = payment["response"]["status"]
    sid = payment["response"].get("external_reference")

    if payment_status == 'approved' and sid in players:
        with thread_lock:
            players[sid]['forti'] += 1000
        update_player_in_db(sid, players[sid]['name'], players[sid]['forti'])
        emit('update_forti', {'forti': players[sid]['forti'], 'sid': sid}, room=sid)
        return jsonify({'status': 'success'}), 200
    return jsonify({'status': 'ignored'}), 200

@socketio.on('connect')
def handle_connect():
    sid = request.sid
    with thread_lock:
        players[sid] = {'name': f'Jugador_{sid[:5]}', 'forti': 1000, 'last_press': 0}
    emit('update_pool', {'pool': pool})
    emit('update_timer', {'timer': timer})
    emit('update_forti', {'forti': players[sid]['forti'], 'sid': sid})
    emit('update_winners', {'winners': list(last_winners)})
    save_player(sid, players[sid]['name'], players[sid]['forti'])

@socketio.on('register_name')
def handle_register_name(data):
    sid = request.sid
    name = data.get('name', '').strip()
    if name and sid not in [player.get('sid') for player in last_winners if 'sid' in player]:
        with thread_lock:
            players[sid] = players.get(sid, {'forti': 0})
            players[sid]['name'] = name
            players[sid]['forti'] = 1000
            players[sid]['last_press'] = 0
        update_player_in_db(sid, name, players[sid]['forti'])
        emit('update_forti', {'forti': players[sid]['forti'], 'sid': sid}, broadcast=True)
        emit('name_updated', {'sid': sid, 'name': name}, broadcast=True)

@socketio.on('get_forti')
def handle_get_forti():
    sid = request.sid
    emit('update_forti', {'forti': players.get(sid, {}).get('forti', 0), 'sid': sid})

@socketio.on('press_button')
def handle_press_button():
    global timer, pool, game_active, last_press_sid
    sid = request.sid

    with thread_lock:
        if sid not in players:
            emit('error', {'message': 'Jugador no registrado'})
            return
        if players[sid].get('forti', 0) < 100:
            emit('error', {'message': 'No tienes suficientes Forti (100 requeridos)'})
            return

        players[sid]['forti'] -= 100
        pool += 100
        last_press_sid = sid
        players[sid]['last_press'] = time.time()
        timer = 240  # Reiniciar el temporizador a 240 segundos
        game_active = True
        print(f"Botón presionado - SID: {sid}, game_active: {game_active}, timer: {timer}")
        update_player_in_db(sid, players[sid]['name'], players[sid]['forti'])

    emit('update_pool', {'pool': pool}, broadcast=True)
    emit('update_timer', {'timer': timer}, broadcast=True)
    emit('button_pressed', {'sid': sid, 'name': players[sid]['name']}, broadcast=True)
    emit('update_forti', {'forti': players[sid]['forti'], 'sid': sid}, broadcast=True)

def game_loop():
    global timer, pool, game_active, last_press_sid, players, last_winners
    while True:
        with thread_lock:
            if game_active and timer > 0:
                timer -= 1
                socketio.emit('update_timer', {'timer': timer}, broadcast=True)
                print(f"Temporizador: {timer}")
            elif game_active and timer == 0 and last_press_sid and last_press_sid in players:
                winner_forti = pool * 0.9
                founder_forti = pool * 0.09
                next_pool = pool * 0.01
                players[last_press_sid]['forti'] += int(winner_forti)
                pool = next_pool
                last_winners.append({
                    'sid': last_press_sid,
                    'name': players[last_press_sid]['name'],
                    'prize': winner_forti
                })
                save_winner(last_press_sid, players[last_press_sid]['name'], winner_forti)
                socketio.emit('game_over', {
                    'winner_sid': last_press_sid,
                    'winner_name': players[last_press_sid]['name'],
                    'prize': winner_forti,
                    'pool': pool
                }, broadcast=True)
                socketio.emit('update_forti', {
                    'forti': players[last_press_sid]['forti'],
                    'sid': last_press_sid
                }, broadcast=True)
                socketio.emit('update_winners', {'winners': list(last_winners)}, broadcast=True)
                game_active = False
                last_press_sid = None
        time.sleep(1)

def save_player(sid, name, forti):
    conn = sqlite3.connect('forti_quest.db')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO players (sid, name, forti) VALUES (?, ?, ?)", (sid, name, forti))
    conn.commit()
    conn.close()

def update_player_in_db(sid, name, forti):
    save_player(sid, name, forti)

def save_winner(sid, name, prize):
    conn = sqlite3.connect('forti_quest.db')
    c = conn.cursor()
    c.execute("INSERT INTO winners (sid, name, prize) VALUES (?, ?, ?)", (sid, name, prize))
    conn.commit()
    conn.close()

if __name__ == '__main__':
    game_thread = Thread(target=game_loop, daemon=True)  # Corregido: Usamos Thread en lugar de threading.Thread
    game_thread.start()
    socketio.run(app, debug=True)