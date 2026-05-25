from flask import Flask, request, jsonify, render_template, send_from_directory, Response
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

import sqlite3
import os
import base64
import mimetypes

# =========================================
# APP CONFIG
# =========================================

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'livestream-secret-key-2024')
CORS(app, resources={r"/*": {"origins": "*"}})
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

# =========================================
# IN-MEMORY: rooms[streamer_user_id] = set of viewer socket_ids
# =========================================

rooms = {}

# =========================================
# DATABASE
# =========================================

DATABASE = os.environ.get('DATABASE_PATH', 'database.db')


def connect_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            email         TEXT UNIQUE,
            password      TEXT,
            first_name    TEXT,
            last_name     TEXT,
            profile_image BLOB,
            profile_image_mime TEXT,
            short_video   BLOB,
            short_video_mime   TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS live_sessions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER UNIQUE,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    conn.commit()
    conn.close()


init_db()

# =========================================
# HELPERS
# =========================================

def broadcast_viewer_count(room_id):
    count = len(rooms.get(room_id, set()))
    socketio.emit('viewer_count', {'count': count}, room=room_id)

# =========================================
# FRONTEND ROUTES
# =========================================

@app.route('/')
def welcome_page():
    return render_template('index.html')

@app.route('/login-page')
def login_page():
    return render_template('login.html')

@app.route('/signup-page')
def signup_page():
    return render_template('signup.html')

@app.route('/profile-page')
def profile_page():
    return render_template('profile.html')

@app.route('/landing-page')
def landing_page():
    return render_template('landing.html')

@app.route('/go-live-page')
def go_live_page():
    return render_template('go-live.html')

@app.route('/watch-page')
def watch_page():
    return render_template('watch.html')

# =========================================
# SERVE IMAGE FROM DATABASE
# =========================================

@app.route('/user-image/<int:user_id>')
def user_image(user_id):
    try:
        conn   = connect_db()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT profile_image, profile_image_mime FROM users WHERE id = ?',
            (user_id,)
        )
        row = cursor.fetchone()
        conn.close()

        if not row or not row['profile_image']:
            return '', 404

        mime = row['profile_image_mime'] or 'image/jpeg'
        return Response(row['profile_image'], mimetype=mime)

    except Exception as e:
        return '', 500

# =========================================
# SERVE VIDEO FROM DATABASE
# =========================================

@app.route('/user-video/<int:user_id>')
def user_video(user_id):
    try:
        conn   = connect_db()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT short_video, short_video_mime FROM users WHERE id = ?',
            (user_id,)
        )
        row = cursor.fetchone()
        conn.close()

        if not row or not row['short_video']:
            return '', 404

        mime = row['short_video_mime'] or 'video/webm'
        return Response(row['short_video'], mimetype=mime)

    except Exception as e:
        return '', 500

# =========================================
# SIGNUP API
# =========================================

@app.route('/signup', methods=['POST'])
def signup():
    try:
        data     = request.json
        email    = data.get('email', '').strip().lower()
        password = data.get('password', '')

        if not email or not password:
            return jsonify({'success': False, 'message': 'Email and Password required'}), 400

        hashed = generate_password_hash(password)
        conn   = connect_db()
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO users (email, password) VALUES (?, ?)',
            (email, hashed)
        )
        conn.commit()
        conn.close()

        return jsonify({'success': True, 'message': 'Signup successful'})

    except sqlite3.IntegrityError:
        return jsonify({'success': False, 'message': 'User already exists'}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# =========================================
# LOGIN API
# =========================================

@app.route('/login', methods=['POST'])
def login():
    try:
        data     = request.json
        email    = data.get('email', '').strip().lower()
        password = data.get('password', '')

        if not email or not password:
            return jsonify({'success': False, 'message': 'Email and Password required'}), 400

        conn   = connect_db()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE email = ?', (email,))
        user = cursor.fetchone()
        conn.close()

        if not user:
            return jsonify({'success': False, 'message': 'User not found'}), 404

        if not check_password_hash(user['password'], password):
            return jsonify({'success': False, 'message': 'Incorrect password'}), 401

        profile_complete = bool(
            user['first_name'] and
            user['profile_image'] and
            user['short_video']
        )

        return jsonify({
            'success':          True,
            'message':          'Login successful',
            'user_id':          user['id'],
            'profile_complete': profile_complete
        })

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# =========================================
# COMPLETE PROFILE API
# =========================================

@app.route('/complete-profile/<int:user_id>', methods=['POST'])
def complete_profile(user_id):
    try:
        first_name = request.form.get('first_name', '').strip()
        last_name  = request.form.get('last_name', '').strip()
        image      = request.files.get('profile_image')
        video      = request.files.get('short_video')

        if not first_name or not last_name:
            return jsonify({'success': False, 'message': 'Full name required'}), 400
        if not image:
            return jsonify({'success': False, 'message': 'Profile image required'}), 400
        if not video:
            return jsonify({'success': False, 'message': 'Short video required'}), 400

        # Read file bytes and mime types
        image_data = image.read()
        image_mime = image.mimetype or 'image/jpeg'

        video_data = video.read()
        video_mime = video.mimetype or 'video/webm'

        conn   = connect_db()
        cursor = conn.cursor()
        cursor.execute(
            '''UPDATE users
               SET first_name=?, last_name=?,
                   profile_image=?, profile_image_mime=?,
                   short_video=?,   short_video_mime=?
               WHERE id=?''',
            (first_name, last_name,
             image_data, image_mime,
             video_data, video_mime,
             user_id)
        )
        conn.commit()
        conn.close()

        return jsonify({'success': True, 'message': 'Profile completed successfully'})

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# =========================================
# GET USER API
# =========================================

@app.route('/get-user/<int:user_id>')
def get_user(user_id):
    try:
        conn   = connect_db()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT id, first_name, last_name, profile_image FROM users WHERE id = ?',
            (user_id,)
        )
        user = cursor.fetchone()
        conn.close()

        if not user:
            return jsonify({'success': False, 'message': 'User not found'}), 404

        return jsonify({
            'success': True,
            'user': {
                'id':               user['id'],
                'first_name':       user['first_name'],
                'last_name':        user['last_name'],
                'profile_image':    f'/user-image/{user_id}' if user['profile_image'] else '',
                'profile_complete': bool(user['first_name'] and user['profile_image'])
            }
        })

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# =========================================
# START LIVE API
# =========================================

@app.route('/start-live/<int:user_id>', methods=['POST'])
def start_live(user_id):
    try:
        conn   = connect_db()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT id, profile_image FROM users WHERE id = ?',
            (user_id,)
        )
        user = cursor.fetchone()

        if not user or not user['profile_image']:
            conn.close()
            return jsonify({'success': False, 'message': 'Complete your profile first'}), 400

        cursor.execute(
            '''INSERT OR REPLACE INTO live_sessions (user_id, started_at)
               VALUES (?, CURRENT_TIMESTAMP)''',
            (user_id,)
        )
        conn.commit()
        conn.close()

        room_id = str(user_id)
        if room_id not in rooms:
            rooms[room_id] = set()

        return jsonify({'success': True, 'message': 'Live started'})

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# =========================================
# STOP LIVE API
# =========================================

@app.route('/stop-live/<int:user_id>', methods=['POST', 'GET'])
def stop_live(user_id):
    try:
        conn   = connect_db()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM live_sessions WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()

        room_id = str(user_id)
        socketio.emit('stream_ended', {}, room=room_id)
        rooms.pop(room_id, None)

        return jsonify({'success': True, 'message': 'Live stopped'})

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# =========================================
# LIVE USERS API
# =========================================

@app.route('/live-users')
def live_users():
    try:
        conn   = connect_db()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT u.id, u.first_name, u.last_name, u.profile_image, ls.started_at
            FROM users u
            INNER JOIN live_sessions ls ON u.id = ls.user_id
            WHERE u.profile_image IS NOT NULL
        ''')
        users = cursor.fetchall()
        conn.close()

        users_list = [{
            'id':            user['id'],
            'first_name':    user['first_name'],
            'last_name':     user['last_name'],
            'profile_image': f'/user-image/{user["id"]}',
            'started_at':    user['started_at'],
            'viewer_count':  len(rooms.get(str(user['id']), set()))
        } for user in users]

        return jsonify({'success': True, 'users': users_list})

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# =========================================
# VIEWER COUNT API
# =========================================

@app.route('/viewer-count/<int:user_id>')
def viewer_count(user_id):
    count = len(rooms.get(str(user_id), set()))
    return jsonify({'success': True, 'count': count})

# =========================================
# SOCKET.IO — WebRTC SIGNALING
# =========================================

@socketio.on('connect')
def on_connect():
    pass


@socketio.on('disconnect')
def on_disconnect():
    sid = request.sid
    for room_id, viewers in list(rooms.items()):
        if sid in viewers:
            viewers.discard(sid)
            leave_room(room_id)
            emit('viewer_left', {'sid': sid}, room=room_id)
            broadcast_viewer_count(room_id)
            break


@socketio.on('join_stream')
def on_join_stream(data):
    room_id = str(data.get('room_id'))
    role    = data.get('role', 'viewer')
    sid     = request.sid

    join_room(room_id)

    if role == 'host':
        if room_id not in rooms:
            rooms[room_id] = set()
        emit('joined_as_host', {'room_id': room_id})
    else:
        if room_id not in rooms:
            emit('stream_not_found', {})
            return
        rooms[room_id].add(sid)
        emit('viewer_joined', {'sid': sid}, room=room_id, skip_sid=sid)
        broadcast_viewer_count(room_id)
        emit('joined_as_viewer', {'room_id': room_id})


@socketio.on('leave_stream')
def on_leave_stream(data):
    room_id = str(data.get('room_id'))
    sid     = request.sid
    if room_id in rooms:
        rooms[room_id].discard(sid)
        emit('viewer_left', {'sid': sid}, room=room_id)
        broadcast_viewer_count(room_id)
    leave_room(room_id)


@socketio.on('offer')
def on_offer(data):
    emit('offer', {
        'sdp':        data['sdp'],
        'sender_sid': request.sid
    }, room=data['target_sid'])


@socketio.on('answer')
def on_answer(data):
    emit('answer', {
        'sdp':        data['sdp'],
        'sender_sid': request.sid
    }, room=data['target_sid'])


@socketio.on('ice_candidate')
def on_ice_candidate(data):
    emit('ice_candidate', {
        'candidate':  data['candidate'],
        'sender_sid': request.sid
    }, room=data['target_sid'])

# =========================================
# RUN APP
# =========================================

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)