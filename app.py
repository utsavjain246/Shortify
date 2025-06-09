from flask import Flask, request, redirect, render_template, url_for, flash, current_app # Added current_app
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import sqlite3
import string
import random
from flask import jsonify # Added for API responses
import qrcode
import io
import base64
import secrets # For API key generation

app = Flask(__name__)
app.secret_key = 'supersecretkey' # Make sure this is a strong, random key in production

# DATABASE = 'database.db' # This will now be set via app.config

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login' # The route to redirect to for login_required views

class User(UserMixin):
    def __init__(self, id, username, password_hash):
        self.id = id
        self.username = username
        self.password_hash = password_hash

    # UserMixin provides get_id, is_authenticated, is_active, is_anonymous

@login_manager.user_loader
def load_user(user_id):
    with get_db() as conn:
        cur = conn.cursor()
        user_row = cur.execute("SELECT id, username, password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
        if user_row:
            return User(id=user_row[0], username=user_row[1], password_hash=user_row[2])
    return None

def get_db():
    # Use current_app.config to get the database path, default to 'database.db' if not set
    db_path = current_app.config.get('DATABASE', 'database.db')
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row # Allows accessing columns by name
    return conn

def create_table():
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS urls (
                id INTEGER PRIMARY KEY,
                original_url TEXT,
                short_url TEXT,
                clicks INTEGER DEFAULT 0,
                user_id INTEGER,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                api_key TEXT UNIQUE
            )
        ''')
        conn.commit()

def generate_short_url():
    characters = string.ascii_letters + string.digits
    short_url = ''.join(random.choices(characters, k=6))
    return short_url

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        original_url = request.form['original_url']
        custom_alias = request.form['custom_alias']
        
        with get_db() as conn:
            if custom_alias:
                short_url = custom_alias
                result = conn.execute('SELECT * FROM urls WHERE short_url = ?', (short_url,)).fetchone()
                if result:
                    # Flash message is handled by base.html, but we need to pass data to re-render form
                    flash('Custom alias already exists. Please choose another one.', 'danger')
                    return render_template('index.html',
                                           original_url_submitted=original_url,
                                           custom_alias_submitted=custom_alias)
            else:
                short_url = generate_short_url()
                while conn.execute('SELECT * FROM urls WHERE short_url = ?', (short_url,)).fetchone():
                    short_url = generate_short_url()
            
            user_id = current_user.id if current_user.is_authenticated else None

            conn.execute('INSERT INTO urls (original_url, short_url, user_id) VALUES (?, ?, ?)',
                         (original_url, short_url, user_id))
            conn.commit()

            # Generate QR code
            full_short_url = request.host_url + short_url
            img = qrcode.make(full_short_url)
            buf = io.BytesIO()
            img.save(buf)
            buf.seek(0)
            qr_code_image = base64.b64encode(buf.getvalue()).decode('utf-8')

            # Re-render index.html with the results, instead of redirecting
            return render_template('index.html',
                                   short_url_display=full_short_url,
                                   qr_code_image=qr_code_image,
                                   original_url_submitted=original_url,
                                   custom_alias_submitted=custom_alias)

    # For GET requests or if POST fails before QR generation (e.g. alias exists)
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        with get_db() as conn:
            cur = conn.cursor()
            user_exists = cur.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()

            if user_exists:
                flash('Username already exists. Please choose a different one.', 'danger')
                return redirect(url_for('register'))

            hashed_password = generate_password_hash(password)
            # Generate a unique API key
            api_key = secrets.token_hex(16)
            while cur.execute("SELECT * FROM users WHERE api_key = ?", (api_key,)).fetchone():
                api_key = secrets.token_hex(16) # Regenerate if somehow not unique

            cur.execute('INSERT INTO users (username, password_hash, api_key) VALUES (?, ?, ?)',
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
            cur = conn.cursor()
            user_row = cur.execute("SELECT id, username, password_hash FROM users WHERE username = ?", (username,)).fetchone()

            if user_row and check_password_hash(user_row['password_hash'], password):
                user_obj = User(id=user_row['id'], username=user_row['username'], password_hash=user_row['password_hash'])
                login_user(user_obj)
                flash('Logged in successfully!', 'success')
                next_page = request.args.get('next')
                return redirect(next_page or url_for('index'))
            else:
                flash('Invalid username or password.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('index'))

@app.route('/profile')
@login_required
def profile():
    with get_db() as conn:
        cur = conn.cursor()
        user_data = cur.execute("SELECT api_key FROM users WHERE id = ?", (current_user.id,)).fetchone()
    api_key = user_data['api_key'] if user_data else "No API Key found. Please re-register or contact support." # Should not happen with new registration logic
    return render_template('profile.html', api_key=api_key)

@app.route('/analytics')
@login_required
def analytics():
    with get_db() as conn:
        cur = conn.cursor()
        user_urls = cur.execute(
            "SELECT original_url, short_url, clicks FROM urls WHERE user_id = ?",
            (current_user.id,)
        ).fetchall()
    return render_template('analytics.html', urls=user_urls)

@app.route('/<short_url>')
def redirect_to_url(short_url):
    with get_db() as conn:
        cur = conn.cursor()
        # Fetch the original URL
        result = cur.execute('SELECT original_url FROM urls WHERE short_url = ?', (short_url,)).fetchone()

        if result:
            # Increment click count
            cur.execute('UPDATE urls SET clicks = clicks + 1 WHERE short_url = ?', (short_url,))
            conn.commit()
            return redirect(result['original_url']) # Access by column name
        else:
            flash('Invalid URL', 'danger')
            return redirect(url_for('index'))

if __name__ == '__main__':
    create_table()
    # The placeholder login route is now replaced by the full implementation above.
    app.run(debug=True)


@app.route('/api/shorten', methods=['POST'])
def api_shorten_url():
    # Use silent=True to prevent raising an exception on malformed JSON,
    # allowing our custom 'if not data:' check to handle it.
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON payload"}), 400

    api_key = data.get('api_key')
    original_url = data.get('original_url')
    custom_alias = data.get('custom_alias') # Optional

    if not api_key:
        return jsonify({"error": "API key is missing"}), 401

    if not original_url:
        return jsonify({"error": "Original URL is missing"}), 400

    with get_db() as conn:
        cur = conn.cursor()
        user_row = cur.execute("SELECT id FROM users WHERE api_key = ?", (api_key,)).fetchone()

        if not user_row:
            return jsonify({"error": "Invalid API key"}), 401

        user_id = user_row['id']
        short_url_slug = ""

        if custom_alias:
            existing_url = cur.execute("SELECT id FROM urls WHERE short_url = ?", (custom_alias,)).fetchone()
            if existing_url:
                return jsonify({"error": "Custom alias already exists"}), 409 # 409 Conflict
            short_url_slug = custom_alias
        else:
            while True:
                short_url_slug = generate_short_url()
                if not cur.execute("SELECT id FROM urls WHERE short_url = ?", (short_url_slug,)).fetchone():
                    break

        try:
            cur.execute("INSERT INTO urls (original_url, short_url, user_id) VALUES (?, ?, ?)",
                        (original_url, short_url_slug, user_id))
            conn.commit()
        except sqlite3.Error as e:
            return jsonify({"error": f"Database error: {e}"}), 500

        full_short_url = request.host_url + short_url_slug
        return jsonify({"short_url": full_short_url, "original_url": original_url}), 201


@app.route('/api/analytics/<string:short_url_slug>', methods=['GET'])
def api_get_analytics(short_url_slug):
    api_key = request.headers.get('X-API-Key')

    if not api_key:
        return jsonify({"error": "API key is missing from X-API-Key header"}), 401

    with get_db() as conn:
        cur = conn.cursor()
        user_row = cur.execute("SELECT id FROM users WHERE api_key = ?", (api_key,)).fetchone()

        if not user_row:
            return jsonify({"error": "Invalid API key"}), 401

        authenticated_user_id = user_row['id']

        # Query for the URL, its user_id, and clicks
        url_data = cur.execute("SELECT original_url, user_id, clicks FROM urls WHERE short_url = ?",
                               (short_url_slug,)).fetchone()

        if not url_data:
            return jsonify({"error": "Short URL not found"}), 404

        # Authorization check: Does this URL belong to the authenticated user?
        if url_data['user_id'] != authenticated_user_id:
            # Return 404 to not reveal existence of the URL to unauthorized users
            return jsonify({"error": "Short URL not found or not authorized"}), 404
            # Or, more explicitly: return jsonify({"error": "Not authorized to view analytics for this URL"}), 403


        full_short_url = request.host_url + short_url_slug
        return jsonify({
            "original_url": url_data['original_url'],
            "short_url": full_short_url,
            "clicks": url_data['clicks']
        }), 200
