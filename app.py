from flask import Flask, request, redirect, render_template, url_for, flash, current_app, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import psycopg2
from psycopg2.extras import DictCursor
import string
import random
import qrcode
import io
import base64
import secrets
import os

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev') 

# Vercel will set this environment variable for Vercel Postgres
DATABASE_URL = os.environ.get('POSTGRES_URL')

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

def get_db():
    conn = psycopg2.connect(DATABASE_URL)
    conn.cursor_factory = DictCursor # Allows accessing columns by name
    return conn

def create_table():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute('''
                CREATE TABLE IF NOT EXISTS urls (
                    id SERIAL PRIMARY KEY,
                    original_url TEXT,
                    short_url TEXT UNIQUE,
                    clicks INTEGER DEFAULT 0,
                    user_id INTEGER,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    api_key TEXT UNIQUE
                );
            ''')
        conn.commit()

# Create a Flask CLI command to initialize the database
@app.cli.command("init-db")
def init_db_command():
    """Initializes the database tables."""
    create_table()
    print("Initialized the PostgreSQL database.")

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        original_url = request.form['original_url']
        custom_alias = request.form['custom_alias']
        
        with get_db() as conn:
            with conn.cursor() as cur:
                if custom_alias:
                    short_url = custom_alias
                    cur.execute('SELECT id FROM urls WHERE short_url = %s;', (short_url,))
                    if cur.fetchone():
                        flash('Custom alias already exists. Please choose another one.', 'danger')
                        return render_template('index.html',
                                               original_url_submitted=original_url,
                                               custom_alias_submitted=custom_alias)
                else:
                    while True:
                        short_url = generate_short_url()
                        cur.execute('SELECT id FROM urls WHERE short_url = %s;', (short_url,))
                        if not cur.fetchone():
                            break
                
                user_id = current_user.id if current_user.is_authenticated else None

                cur.execute('INSERT INTO urls (original_url, short_url, user_id) VALUES (%s, %s, %s);',
                             (original_url, short_url, user_id))
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


def generate_short_url():
    characters = string.ascii_letters + string.digits
    return ''.join(random.choices(characters, k=6))


@app.route('/<short_url>')
def redirect_to_url(short_url):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT original_url FROM urls WHERE short_url = %s;', (short_url,))
            result = cur.fetchone()

            if result:
                cur.execute('UPDATE urls SET clicks = clicks + 1 WHERE short_url = %s;', (short_url,))
                conn.commit()
                return redirect(result['original_url'])
            else:
                flash('Invalid URL', 'danger')
                return redirect(url_for('index'))
