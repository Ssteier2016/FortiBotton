from flask import Flask, render_template
from flask_socketio import SocketIO, emit
import time
from threading import Lock

app = Flask(__name__)
socketio = SocketIO(app, async_mode='threading')
thread_lock = Lock()

# Estado del juego
players = {}  # {sid: {'forti': saldo, 'last_press': timestamp}}
timer = 240  # 240 segundos
pool = 0  # Pozo acumulado
game_active = False
last_press_sid = None

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('connect')
def handle_connect():
    sid = request.sid
    players[sid] = {'forti': 0, 'last_press': 0}
    emit('update_pool', {'pool': pool})
    emit('update_timer', {'timer': timer})

@socketio.on('press_button')
def handle_press_button():
    global timer, pool, game_active, last_press_sid
    sid = request.sid

    # Verificar si el jugador tiene suficiente forti
    if players[sid]['forti'] < 100:
        emit('error', {'message': 'No tienes suficientes forti (100 requeridos)'})
        return

    # Restar 100 forti
    players[sid]['forti'] -= 100
    pool += 100  # Añadir al pozo
    last_press_sid = sid
    players[sid]['last_press'] = time.time()
    timer = 240  # Reiniciar temporizador
    game_active = True

    # Notificar a todos los jugadores
    emit('update_pool', {'pool': pool}, broadcast=True)
    emit('update_timer', {'timer': timer}, broadcast=True)
    emit('button_pressed', {'sid': sid}, broadcast=True)

def game_loop():
    global timer, pool, game_active, last_press_sid
    while True:
        with thread_lock:
            if game_active and timer > 0:
                timer -= 1
                socketio.emit('update_timer', {'timer': timer})
                if timer == 0 and last_press_sid:
                    # Ganador: último en presionar
                    winner_forti = pool * 0.9  # 90% al ganador
                    founder_forti = pool * 0.09  # 9% al fundador
                    next_pool = pool * 0.01  # 1% al próximo pozo
                    players[last_press_sid]['forti'] += winner_forti
                    pool = next_pool  # Reiniciar pozo con 1%

                    # Notificar ganador
                    socketio.emit('game_over', {
                        'winner_sid': last_press_sid,
                        'prize': winner_forti,
                        'pool': pool
                    }, broadcast=True)
                    game_active = False
                    last_press_sid = None
            time.sleep(1)

# Iniciar el bucle del juego en un hilo separado
import threading
if __name__ == '__main__':
    game_thread = threading.Thread(target=game_loop)
    game_thread.daemon = True
    game_thread.start()
    socketio.run(app, debug=True)
    import mercadopago

sdk = mercadopago.SDK("TU_ACCESS_TOKEN")

@socketio.on('deposit')
def handle_deposit(data):
    amount = data['amount']
    preference = {
        "items": [{
            "title": "Depósito de Forti",
            "quantity": 1,
            "currency_id": "ARS",
            "unit_price": amount
        }]
    }
    response = sdk.preference().create(preference)
    emit('payment_url', {'url': response['response']['sandbox_init_point']})