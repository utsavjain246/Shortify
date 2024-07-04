from flask import Flask, request, redirect, render_template, url_for, flash
import sqlite3
import string
import random

app = Flask(__name__)
app.secret_key = 'supersecretkey'

DATABASE = 'database.db'

def get_db():
    conn = sqlite3.connect(DATABASE)
    return conn

def create_table():
    with get_db() as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS urls (id INTEGER PRIMARY KEY, original_url TEXT, short_url TEXT)')
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
                    flash('Custom alias already exists. Please choose another one.', 'danger')
                    return redirect(url_for('index'))
            else:
                short_url = generate_short_url()
                while conn.execute('SELECT * FROM urls WHERE short_url = ?', (short_url,)).fetchone():
                    short_url = generate_short_url()
            
            conn.execute('INSERT INTO urls (original_url, short_url) VALUES (?, ?)', (original_url, short_url))
            conn.commit()
            flash(f'Short URL created: {request.host_url}{short_url}', 'success')
        return redirect(url_for('index'))
    return render_template('index.html')

@app.route('/<short_url>')
def redirect_to_url(short_url):
    with get_db() as conn:
        result = conn.execute('SELECT original_url FROM urls WHERE short_url = ?', (short_url,)).fetchone()
        if result:
            return redirect(result[0])
        else:
            flash('Invalid URL', 'danger')
            return redirect(url_for('index'))

if __name__ == '__main__':
    create_table()
    app.run(debug=True)
