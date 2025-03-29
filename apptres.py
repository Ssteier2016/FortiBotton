from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
import time
from threading import Lock, Thread
from collections import deque
import sqlite3
from mercadopago import SDK

app = Flask(__name__)
socketio = SocketIO(app, async_mode='threading')
thread_lock = Lock()

# Configuración de Mercado Pago
mp = SDK("TEST-44493711284061-030923-0d8c10ba1485ca86a11efda3fc48d68f-320701222")
FOUNDER_USER_ID = "320701222"

# Estado del juego
players = {}
timer = 240  # Temporizador reducido a 240 segundos
pool = 0
game_active = False
last_press_sid = None
last_winners = deque(maxlen=5)

def init_db():
    conn = sqlite3.connect('forti_quest.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS players
                 (sid TEXT PRIMARY KEY, name TEXT, phone TEXT UNIQUE, forti INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS winners
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, sid TEXT, name TEXT, prize REAL, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

init_db()

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('connect')
def handle_connect():
    sid = request.sid
    with thread_lock:
        players[sid] = {'name': 'Jugador_' + sid[:5], 'forti': 1000, 'last_press': 0}
    emit('update_pool', {'pool': pool})
    emit('update_timer', {'timer': timer})
    emit('update_forti', {'forti': players[sid]['forti'], 'sid': sid})
    emit('update_winners', {'winners': list(last_winners)})

@socketio.on('register_name')
def handle_register_name(data):
    sid = request.sid
    name = data['name']
    phone = data['phone']
    if name and phone and phone.isdigit():
        with thread_lock:
            players[sid] = {'name': name, 'phone': phone, 'forti': 1000}
        save_player(sid, name, phone, players[sid]['forti'])
        emit('name_updated', {'sid': sid, 'name': name}, broadcast=True)

@socketio.on('press_button')
def handle_press_button():
    global timer, pool, game_active, last_press_sid
    sid = request.sid

    if sid not in players or players[sid]['forti'] < 100:
        emit('error', {'message': 'No tienes suficientes forti (100 requeridos)'})
        return

    with thread_lock:
        players[sid]['forti'] -= 100
        pool += 100
        last_press_sid = sid
        players[sid]['last_press'] = time.time()
        timer = 240  # Se reinicia a 240 segundos
        game_active = True

    emit('update_pool', {'pool': pool}, broadcast=True)
    emit('update_timer', {'timer': timer}, broadcast=True)
    emit('button_pressed', {'sid': sid}, broadcast=True)
    emit('update_forti', {'forti': players[sid]['forti'], 'sid': sid}, broadcast=True)
    update_player_in_db(sid, players[sid]['name'], players[sid]['phone'], players[sid]['forti'])


def start_timer():
    global timer, game_active
    while True:
        time.sleep(1)
        with thread_lock:
            if game_active and timer > 0:
                timer -= 1
                socketio.emit('update_timer', {'timer': timer}, broadcast=True)
            elif game_active and timer == 0:
                game_active = False
                socketio.emit('game_over', {
                    'winner_sid': last_press_sid,
                    'winner_name': players.get(last_press_sid, {}).get('name', 'Desconocido'),
                    'prize': pool * 0.9,
                    'pool': pool * 0.01
                }, broadcast=True)
                last_press_sid = None


def save_player(sid, name, phone, forti):
    conn = sqlite3.connect('forti_quest.db')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO players (sid, name, phone, forti) VALUES (?, ?, ?, ?)", (sid, name, phone, forti))
    conn.commit()
    conn.close()

def update_player_in_db(sid, name, phone, forti):
    save_player(sid, name, phone, forti)

if __name__ == '__main__':
    game_thread = Thread(target=start_timer, daemon=True)
    game_thread.start()
    socketio.run(app, debug=False)