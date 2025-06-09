import pytest
from app import get_db # To directly inspect DB if needed

def test_register_page(client):
    """Test that the registration page loads."""
    response = client.get('/register')
    assert response.status_code == 200
    assert b"<h2>Register</h2>" in response.data
    assert b"Username" in response.data
    assert b"Password" in response.data

def test_login_page(client):
    """Test that the login page loads."""
    response = client.get('/login')
    assert response.status_code == 200
    assert b"<h2>Login</h2>" in response.data
    assert b"Username" in response.data
    assert b"Password" in response.data

def test_successful_registration(client, app):
    """Test successful user registration."""
    response = client.post('/register', data={
        'username': 'testuser',
        'password': 'password123'
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b"Registration successful! Please login." in response.data
    assert b"<h2>Login</h2>" in response.data # Should be redirected to login page

    # Check if user is in the database
    with app.app_context():
        with get_db() as conn:
            cur = conn.cursor()
            user = cur.execute("SELECT * FROM users WHERE username = ?", ('testuser',)).fetchone()
            assert user is not None
            assert user['username'] == 'testuser'
            assert user['api_key'] is not None # Check API key was generated

def test_registration_existing_username(client, app):
    """Test registration with an existing username."""
    # First, register a user
    client.post('/register', data={'username': 'testuser', 'password': 'password123'})

    # Attempt to register the same username again
    response = client.post('/register', data={
        'username': 'testuser',
        'password': 'anotherpassword'
    }, follow_redirects=True)
    assert response.status_code == 200 # Stays on register page
    assert b"Username already exists. Please choose a different one." in response.data
    assert b"<h2>Register</h2>" in response.data # Should remain on register page

def test_successful_login_logout(client, app):
    """Test successful login and then logout."""
    # Register user first
    client.post('/register', data={'username': 'loginuser', 'password': 'password123'})

    # Test login
    response = client.post('/login', data={
        'username': 'loginuser',
        'password': 'password123'
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b"Logged in successfully!" in response.data
    assert b'<h1 class="card-title text-center">Shortify</h1>' in response.data # Main heading on index page
    assert b"Hello, loginuser!" in response.data
    assert b"Logout" in response.data

    # Test logout
    response = client.get('/logout', follow_redirects=True)
    assert response.status_code == 200
    assert b"You have been logged out." in response.data
    assert b'<h1 class="card-title text-center">Shortify</h1>' in response.data # Main heading on index page
    assert b"Login" in response.data # Login link should be visible again
    assert b"Hello, loginuser!" not in response.data

def test_login_invalid_username(client):
    """Test login with an invalid username."""
    response = client.post('/login', data={
        'username': 'nonexistentuser',
        'password': 'password123'
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b"Invalid username or password." in response.data
    assert b"<h2>Login</h2>" in response.data # Should remain on login page

def test_login_invalid_password(client):
    """Test login with an invalid password."""
    # Register user first
    client.post('/register', data={'username': 'testuser', 'password': 'password123'})

    response = client.post('/login', data={
        'username': 'testuser',
        'password': 'wrongpassword'
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b"Invalid username or password." in response.data
    assert b"<h2>Login</h2>" in response.data # Should remain on login page
