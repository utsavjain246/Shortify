import pytest
from app import get_db # To directly inspect DB if needed
import re # For extracting short URL from response

# Helper function to extract short URL from the success message/display
def extract_short_url_from_response(response_data_bytes):
    match = re.search(r'<a href="([^"]+)" target="_blank">([^<]+)</a>', response_data_bytes.decode('utf-8'))
    if match:
        # The link text (match.group(2)) should be the full short URL
        # The href (match.group(1)) is also the full short URL
        return match.group(2).split('/')[-1] # Return just the slug
    return None

def test_shorten_url_anonymous(client, app):
    """Test anonymous URL shortening."""
    original_url = "https://www.google.com"
    response = client.post('/', data={'original_url': original_url, 'custom_alias': ''})

    assert response.status_code == 200
    assert b"Short URL Created!" in response.data
    assert b"QR Code for" in response.data # Check alt text part
    assert b'<img src="data:image/png;base64,' in response.data # Check for img tag start

    # Check that base64 data is present and non-empty
    qr_code_match = re.search(r'<img src="data:image/png;base64,([^"]+)"', response.data.decode('utf-8'))
    assert qr_code_match is not None
    assert len(qr_code_match.group(1)) > 0 # Base64 string should not be empty

    short_url_slug = extract_short_url_from_response(response.data)
    assert short_url_slug is not None

    with app.app_context():
        with get_db() as conn:
            cur = conn.cursor()
            url_entry = cur.execute("SELECT * FROM urls WHERE short_url = ?", (short_url_slug,)).fetchone()
            assert url_entry is not None
            assert url_entry['original_url'] == original_url
            assert url_entry['user_id'] is None # Anonymous

def test_redirect_and_click_tracking(client, app):
    """Test redirection and click tracking."""
    original_url = "https://www.example.com/test-page"
    post_response = client.post('/', data={'original_url': original_url, 'custom_alias': ''})
    short_url_slug = extract_short_url_from_response(post_response.data)
    assert short_url_slug is not None

    # Access the short URL
    redirect_response = client.get(f'/{short_url_slug}', follow_redirects=False) # Don't follow redirect yet
    assert redirect_response.status_code == 302 # Check for redirect
    assert redirect_response.headers['Location'] == original_url

    with app.app_context():
        with get_db() as conn:
            cur = conn.cursor()
            url_entry = cur.execute("SELECT clicks FROM urls WHERE short_url = ?", (short_url_slug,)).fetchone()
            assert url_entry['clicks'] == 1

    # Access again to check increment
    client.get(f'/{short_url_slug}')
    with app.app_context():
        with get_db() as conn:
            cur = conn.cursor()
            url_entry = cur.execute("SELECT clicks FROM urls WHERE short_url = ?", (short_url_slug,)).fetchone()
            assert url_entry['clicks'] == 2


def test_shorten_url_custom_alias(client, app):
    """Test URL shortening with a custom alias."""
    original_url = "https://www.customurl.dev"
    custom_alias = "mycustom"
    response = client.post('/', data={'original_url': original_url, 'custom_alias': custom_alias})

    assert response.status_code == 200
    assert b"Short URL Created!" in response.data
    assert f"/{custom_alias}".encode() in response.data # Check if custom alias is in the displayed URL
    assert b'<img src="data:image/png;base64,' in response.data

    # Check that base64 data is present and non-empty
    qr_code_match = re.search(r'<img src="data:image/png;base64,([^"]+)"', response.data.decode('utf-8'))
    assert qr_code_match is not None
    assert len(qr_code_match.group(1)) > 0

    with app.app_context():
        with get_db() as conn:
            cur = conn.cursor()
            url_entry = cur.execute("SELECT * FROM urls WHERE short_url = ?", (custom_alias,)).fetchone()
            assert url_entry is not None
            assert url_entry['original_url'] == original_url

def test_shorten_url_existing_custom_alias(client):
    """Test using an already existing custom alias."""
    client.post('/', data={'original_url': "https://first.com", 'custom_alias': 'exists'})

    response = client.post('/', data={'original_url': "https://second.com", 'custom_alias': 'exists'})
    assert response.status_code == 200 # Stays on index page
    assert b"Custom alias already exists. Please choose another one." in response.data

def test_shorten_url_authenticated(client, app):
    """Test URL shortening by an authenticated user."""
    # Register and login user
    client.post('/register', data={'username': 'authuser', 'password': 'password'})
    login_response = client.post('/login', data={'username': 'authuser', 'password': 'password'}, follow_redirects=True)
    assert b"Hello, authuser!" in login_response.data # Confirm login

    original_url = "https://www.authenticated-url.com"
    post_response = client.post('/', data={'original_url': original_url, 'custom_alias': ''})
    assert post_response.status_code == 200
    short_url_slug = extract_short_url_from_response(post_response.data)
    assert short_url_slug is not None

    with app.app_context():
        with get_db() as conn:
            cur = conn.cursor()
            # Get user_id for 'authuser'
            user = cur.execute("SELECT id FROM users WHERE username = ?", ('authuser',)).fetchone()
            assert user is not None
            auth_user_id = user['id']

            url_entry = cur.execute("SELECT * FROM urls WHERE short_url = ?", (short_url_slug,)).fetchone()
            assert url_entry is not None
            assert url_entry['original_url'] == original_url
            assert url_entry['user_id'] == auth_user_id

    # Check analytics page
    analytics_response = client.get('/analytics')
    assert analytics_response.status_code == 200
    assert original_url.encode() in analytics_response.data # Check if original_url is listed
    assert short_url_slug.encode() in analytics_response.data # Check if short_url is listed
    assert b"My URLs & Analytics" in analytics_response.data
