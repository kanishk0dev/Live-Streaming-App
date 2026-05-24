from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

import sqlite3
import os


# =========================================
# APP CONFIG
# =========================================

app = Flask(__name__)
CORS(app)

# =========================================
# UPLOAD FOLDERS
# =========================================

UPLOAD_IMAGE = 'uploads/images'
UPLOAD_VIDEO = 'uploads/videos'

os.makedirs(UPLOAD_IMAGE, exist_ok=True)
os.makedirs(UPLOAD_VIDEO, exist_ok=True)

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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE,
            password TEXT,
            first_name TEXT,
            last_name TEXT,
            profile_image TEXT,
            short_video TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS live_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    conn.commit()
    conn.close()


init_db()

# =========================================
# SERVE UPLOADED FILES
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

# =========================================
# SIGNUP API
# =========================================

@app.route('/signup', methods=['POST'])
def signup():
    try:
        data = request.json
        email = data.get('email')
        password = data.get('password')

        if not email or not password:
            return jsonify({'success': False, 'message': 'Email and Password required'}), 400

        hashed_password = generate_password_hash(password)

        conn = connect_db()
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO users (email, password) VALUES (?, ?)',
            (email, hashed_password)
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
        data = request.json
        email = data.get('email')
        password = data.get('password')

        if not email or not password:
            return jsonify({'success': False, 'message': 'Email and Password required'}), 400

        conn = connect_db()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE email = ?', (email,))
        user = cursor.fetchone()
        conn.close()

        if not user:
            return jsonify({'success': False, 'message': 'User not found'}), 404

        if not check_password_hash(user['password'], password):
            return jsonify({'success': False, 'message': 'Incorrect password'}), 401

        # Check if profile is complete
        profile_complete = bool(user['first_name'] and user['profile_image'] and user['short_video'])

        return jsonify({
            'success': True,
            'message': 'Login successful',
            'user_id': user['id'],
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
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        image = request.files.get('profile_image')
        video = request.files.get('short_video')

        if not first_name or not last_name:
            return jsonify({'success': False, 'message': 'Full name required'}), 400

        if not image:
            return jsonify({'success': False, 'message': 'Profile image required'}), 400

        if not video:
            return jsonify({'success': False, 'message': 'Short video required'}), 400

        image_name = secure_filename(f"{user_id}_{image.filename}")
        video_name = secure_filename(f"{user_id}_{video.filename}")

        image_path = os.path.join(UPLOAD_IMAGE, image_name)
        video_path = os.path.join(UPLOAD_VIDEO, video_name)

        image.save(image_path)
        video.save(video_path)

        conn = connect_db()
        cursor = conn.cursor()
        cursor.execute(
            '''UPDATE users SET first_name=?, last_name=?, profile_image=?, short_video=? WHERE id=?''',
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
        conn = connect_db()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
        user = cursor.fetchone()
        conn.close()

        if not user:
            return jsonify({'success': False, 'message': 'User not found'}), 404

        return jsonify({
            'success': True,
            'user': {
                'id': user['id'],
                'first_name': user['first_name'],
                'last_name': user['last_name'],
                'profile_image': user['profile_image'],
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
        conn = connect_db()
        cursor = conn.cursor()

        # Check user has complete profile
        cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
        user = cursor.fetchone()

        if not user or not user['profile_image']:
            conn.close()
            return jsonify({'success': False, 'message': 'Complete your profile first'}), 400

        # Insert or replace live session
        cursor.execute('''
            INSERT OR REPLACE INTO live_sessions (user_id, started_at)
            VALUES (?, CURRENT_TIMESTAMP)
        ''', (user_id,))

        conn.commit()
        conn.close()

        return jsonify({'success': True, 'message': 'Live started'})

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# =========================================
# STOP LIVE API
# =========================================

@app.route('/stop-live/<int:user_id>', methods=['POST', 'GET'])
def stop_live(user_id):
    try:
        conn = connect_db()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM live_sessions WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()

        return jsonify({'success': True, 'message': 'Live stopped'})

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# =========================================
# LIVE USERS API — only currently live users
# =========================================

@app.route('/live-users')
def live_users():
    try:
        conn = connect_db()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT u.id, u.first_name, u.last_name, u.profile_image, ls.started_at
            FROM users u
            INNER JOIN live_sessions ls ON u.id = ls.user_id
            WHERE u.profile_image IS NOT NULL
        ''')
        users = cursor.fetchall()
        conn.close()

        users_list = []
        for user in users:
            users_list.append({
                'id': user['id'],
                'first_name': user['first_name'],
                'last_name': user['last_name'],
                'profile_image': '/' + user['profile_image'],
                'started_at': user['started_at']
            })

        return jsonify({'success': True, 'users': users_list})

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# =========================================
# RUN APP
# =========================================

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)