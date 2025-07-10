import base64
import io
import os
import random
import secrets
import string

import psycopg2
import qrcode
from flask import (Flask, flash, jsonify, redirect, render_template, request,
                   url_for)
from flask_login import (LoginManager, UserMixin, current_user, login_required,
                           login_user, logout_user)
from psycopg2.extras import DictCursor
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)

# Get secrets from environment variables
app.secret_key = os.environ.get('SECRET_KEY')
DATABASE_URL = os.environ.get('POSTGRES_URL')

# --- Flask-Login Configuration ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, id, username, password_hash):
        self.id = id
        self.username = username
        self.password_hash = password_hash

@login_manager.user_loader
def load_user(user_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, username, password_hash FROM users WHERE id = %s;", (user_id,))
            user_row = cur.fetchone()
            if user_row:
                return User(id=user_row['id'], username=user_row['username'], password_hash=user_row['password_hash'])
    return None

# --- Database Functions ---
def get_db():
    """Establishes a connection to the PostgreSQL database."""
    conn = psycopg2.connect(DATABASE_URL)
    return conn

def create_tables():
    """Create database tables if they don't exist."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    api_key TEXT UNIQUE
                );
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS urls (
                    id SERIAL PRIMARY KEY,
                    original_url TEXT NOT NULL,
                    short_url TEXT UNIQUE NOT NULL,
                    clicks INTEGER DEFAULT 0,
                    user_id INTEGER,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );
            ''')
        conn.commit()

@app.cli.command("init-db")
def init_db_command():
    """CLI command to create database tables."""
    create_tables()
    print("Initialized the PostgreSQL database and created tables.")


def generate_short_url():
    """Generates a random 6-character short URL."""
    characters = string.ascii_letters + string.digits
    return ''.join(random.choices(characters, k=6))

# --- Main Application Routes ---
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        original_url = request.form['original_url']
        custom_alias = request.form.get('custom_alias')

        with get_db() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                if custom_alias:
                    short_url = custom_alias
                    cur.execute('SELECT id FROM urls WHERE short_url = %s;', (short_url,))
                    if cur.fetchone():
                        flash('Custom alias already exists. Please choose another one.', 'danger')
                        return render_template('index.html', original_url_submitted=original_url, custom_alias_submitted=custom_alias)
                else:
                    while True:
                        short_url = generate_short_url()
                        cur.execute('SELECT id FROM urls WHERE short_url = %s;', (short_url,))
                        if not cur.fetchone():
                            break
                
                user_id = current_user.id if current_user.is_authenticated else None

                cur.execute('INSERT INTO urls (original_url, short_url, user_id) VALUES (%s, %s, %s);', (original_url, short_url, user_id))
            conn.commit()

        full_short_url = request.host_url + short_url
        img = qrcode.make(full_short_url)
        buf = io.BytesIO()
        img.save(buf)
        buf.seek(0)
        qr_code_image = base64.b64encode(buf.getvalue()).decode('utf-8')

        return render_template('index.html',
                               short_url_display=full_short_url,
                               qr_code_image=qr_code_image,
                               original_url_submitted=original_url,
                               custom_alias_submitted=custom_alias)

    return render_template('index.html')

@app.route('/<short_url>')
def redirect_to_url(short_url):
    with get_db() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute('SELECT original_url FROM urls WHERE short_url = %s;', (short_url,))
            result = cur.fetchone()

            if result:
                cur.execute('UPDATE urls SET clicks = clicks + 1 WHERE short_url = %s;', (short_url,))
                conn.commit()
                return redirect(result['original_url'])
    flash('URL not found.', 'danger')
    return redirect(url_for('index'))

# --- Authentication Routes ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        with get_db() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute('SELECT id FROM users WHERE username = %s;', (username,))
                if cur.fetchone():
                    flash('Username already exists.', 'danger')
                    return redirect(url_for('register'))

                hashed_password = generate_password_hash(password)
                api_key = secrets.token_hex(16)
                cur.execute('INSERT INTO users (username, password_hash, api_key) VALUES (%s, %s, %s);',
                            (username, hashed_password, api_key))
            conn.commit()
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        with get_db() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute("SELECT id, username, password_hash FROM users WHERE username = %s;", (username,))
                user_row = cur.fetchone()
                if user_row and check_password_hash(user_row['password_hash'], password):
                    user_obj = User(id=user_row['id'], username=user_row['username'], password_hash=user_row['password_hash'])
                    login_user(user_obj)
                    next_page = request.args.get('next')
                    return redirect(next_page or url_for('index'))
        flash('Invalid username or password.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('index'))


# --- User-Specific Routes ---
@app.route('/profile')
@login_required
def profile():
    with get_db() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("SELECT api_key FROM users WHERE id = %s;", (current_user.id,))
            user_data = cur.fetchone()
    api_key = user_data['api_key'] if user_data else "API Key not found."
    return render_template('profile.html', api_key=api_key)

@app.route('/analytics')
@login_required
def analytics():
    with get_db() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute(
                "SELECT original_url, short_url, clicks FROM urls WHERE user_id = %s;",
                (current_user.id,)
            )
            user_urls = cur.fetchall()
    return render_template('analytics.html', urls=user_urls)
