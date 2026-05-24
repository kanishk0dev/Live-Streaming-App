from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

import sqlite3
import os
import cloudinary
import cloudinary.uploader

# =========================================
# APP CONFIG
# =========================================

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'livestream-secret-key-2024')
CORS(app, resources={r"/*": {"origins": "*"}})
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

# =========================================
# CLOUDINARY CONFIG
# =========================================

cloudinary.config(
    cloud_name = os.environ.get('CLOUDINARY_CLOUD_NAME'),
    api_key    = os.environ.get('CLOUDINARY_API_KEY'),
    api_secret = os.environ.get('CLOUDINARY_API_SECRET')
)

# =========================================
# LOCAL UPLOAD FOLDERS (fallback for dev)
# =========================================

UPLOAD_IMAGE = 'uploads/images'
UPLOAD_VIDEO = 'uploads/videos'

os.makedirs(UPLOAD_IMAGE, exist_ok=True)
os.makedirs(UPLOAD_VIDEO, exist_ok=True)

# =========================================
# IN-MEMORY: rooms[streamer_user_id] = set of viewer socket_ids
# This tracks who is watching each stream right now
# =========================================

rooms = {}   # { streamer_user_id(str): set(socket_id) }

# =========================================
# DATABASE
# =========================================

DATABASE = 'database.db'


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
            profile_image TEXT,
            short_video   TEXT
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

def is_cloudinary_configured():
    return all([
        os.environ.get('CLOUDINARY_CLOUD_NAME'),
        os.environ.get('CLOUDINARY_API_KEY'),
        os.environ.get('CLOUDINARY_API_SECRET'),
    ])


def upload_image(file, user_id):
    if is_cloudinary_configured():
        result = cloudinary.uploader.upload(
            file,
            folder='livestream/images',
            public_id=f'user_{user_id}_profile',
            overwrite=True,
            resource_type='image'
        )
        return result['secure_url']
    else:
        filename = secure_filename(f"{user_id}_{file.filename}")
        path = os.path.join(UPLOAD_IMAGE, filename)
        file.save(path)
        return path


def upload_video(file, user_id):
    if is_cloudinary_configured():
        result = cloudinary.uploader.upload(
            file,
            folder='livestream/videos',
            public_id=f'user_{user_id}_video',
            overwrite=True,
            resource_type='video'
        )
        return result['secure_url']
    else:
        filename = secure_filename(f"{user_id}_{file.filename}")
        path = os.path.join(UPLOAD_VIDEO, filename)
        file.save(path)
        return path


def image_url(raw_path):
    if raw_path and raw_path.startswith('http'):
        return raw_path
    return '/' + raw_path if raw_path else ''


def broadcast_viewer_count(room_id):
    """Emit updated viewer count to everyone in the room."""
    count = len(rooms.get(room_id, set()))
    socketio.emit('viewer_count', {'count': count}, room=room_id)

# =========================================
# SERVE LOCAL UPLOADED FILES (dev only)
# =========================================

@app.route('/uploads/images/<filename>')
def serve_image(filename):
    return send_from_directory('uploads/images', filename)


@app.route('/uploads/videos/<filename>')
def serve_video(filename):
    return send_from_directory('uploads/videos', filename)

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
        cursor.execute('INSERT INTO users (email, password) VALUES (?, ?)', (email, hashed))
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

        image_path = upload_image(image, user_id)
        video_path = upload_video(video, user_id)

        conn   = connect_db()
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE users SET first_name=?, last_name=?, profile_image=?, short_video=? WHERE id=?',
            (first_name, last_name, image_path, video_path, user_id)
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
        cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
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
                'profile_image':    image_url(user['profile_image']),
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
        cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
        user = cursor.fetchone()

        if not user or not user['profile_image']:
            conn.close()
            return jsonify({'success': False, 'message': 'Complete your profile first'}), 400

        cursor.execute('''
            INSERT OR REPLACE INTO live_sessions (user_id, started_at)
            VALUES (?, CURRENT_TIMESTAMP)
        ''', (user_id,))
        conn.commit()
        conn.close()

        # Create a room for this streamer
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

        # Notify all viewers in this room that stream ended
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
            'profile_image': image_url(user['profile_image']),
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
#
# Flow:
#   Streamer  --[join_stream as host]-->  Server creates room
#   Viewer    --[join_stream as viewer]--> Server adds viewer to room
#                                          Server tells streamer "new viewer joined"
#   Streamer  --[offer]--> Server --> Viewer    (WebRTC offer)
#   Viewer    --[answer]--> Server --> Streamer (WebRTC answer)
#   Both      --[ice_candidate]--> Server --> other side (ICE candidates)
# =========================================

@socketio.on('connect')
def on_connect():
    pass


@socketio.on('disconnect')
def on_disconnect():
    sid = request.sid
    # Remove viewer from any room they were in
    for room_id, viewers in list(rooms.items()):
        if sid in viewers:
            viewers.discard(sid)
            leave_room(room_id)
            # Tell streamer a viewer left
            emit('viewer_left', {'sid': sid}, room=room_id)
            broadcast_viewer_count(room_id)
            break


@socketio.on('join_stream')
def on_join_stream(data):
    """
    data = { room_id: str(streamer_user_id), role: 'host' | 'viewer' }
    """
    room_id = str(data.get('room_id'))
    role    = data.get('role', 'viewer')
    sid     = request.sid

    join_room(room_id)

    if role == 'host':
        # Host joins — initialise room if needed
        if room_id not in rooms:
            rooms[room_id] = set()
        emit('joined_as_host', {'room_id': room_id})

    else:
        # Viewer joins — add to room set
        if room_id not in rooms:
            # Stream doesn't exist
            emit('stream_not_found', {})
            return

        rooms[room_id].add(sid)
        # Tell the host a new viewer arrived (host needs to send an offer)
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


# ---- WebRTC signaling relay ----

@socketio.on('offer')
def on_offer(data):
    """Streamer sends offer to a specific viewer."""
    # data = { target_sid, sdp }
    emit('offer', {
        'sdp':        data['sdp'],
        'sender_sid': request.sid
    }, room=data['target_sid'])


@socketio.on('answer')
def on_answer(data):
    """Viewer sends answer back to streamer."""
    # data = { target_sid, sdp }
    emit('answer', {
        'sdp':        data['sdp'],
        'sender_sid': request.sid
    }, room=data['target_sid'])


@socketio.on('ice_candidate')
def on_ice_candidate(data):
    """Relay ICE candidates between streamer and viewer."""
    # data = { target_sid, candidate }
    emit('ice_candidate', {
        'candidate':  data['candidate'],
        'sender_sid': request.sid
    }, room=data['target_sid'])

# =========================================
# RUN APP
# =========================================

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)