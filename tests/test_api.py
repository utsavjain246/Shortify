import pytest
import json
from app import get_db, app as flask_app # Added flask_app for app_context

# Helper to create a user and return their details including API key
def create_user_for_api_test(client, username, password):
    client.post('/register', data={'username': username, 'password': password})
    with flask_app.app_context(): # Use app_context from imported flask_app
        with get_db() as conn:
            cur = conn.cursor()
            user_row = cur.execute("SELECT api_key FROM users WHERE username = ?", (username,)).fetchone()
            assert user_row is not None, f"User {username} not found after registration attempt."
            return {"username": username, "password": password, "api_key": user_row['api_key']}

@pytest.fixture
def api_user(client):
    """Provides a registered user with an API key for API tests."""
    return create_user_for_api_test(client, 'apiuser', 'apipassword')

# --- Tests for /api/shorten ---

def test_api_shorten_successful(client, api_user):
    response = client.post('/api/shorten', json={
        'api_key': api_user['api_key'],
        'original_url': 'https://example.com/api-test'
    })
    assert response.status_code == 201
    data = response.get_json()
    assert 'short_url' in data
    assert data['original_url'] == 'https://example.com/api-test'
    # The problematic assertion was: assert api_user['username'] in data['short_url']
    # This is removed as request.host_url in tests is just 'localhost'.

    # Verify in DB
    short_slug = data['short_url'].split('/')[-1]
    with flask_app.app_context():
        with get_db() as conn:
            cur = conn.cursor()
            url_entry = cur.execute("SELECT * FROM urls WHERE short_url = ?", (short_slug,)).fetchone()
            user_entry = cur.execute("SELECT id FROM users WHERE username = ?", (api_user['username'],)).fetchone()
            assert url_entry is not None
            assert url_entry['original_url'] == 'https://example.com/api-test'
            assert url_entry['user_id'] == user_entry['id']

def test_api_shorten_custom_alias(client, api_user):
    response = client.post('/api/shorten', json={
        'api_key': api_user['api_key'],
        'original_url': 'https://custom.example.com',
        'custom_alias': 'apicustom1'
    })
    assert response.status_code == 201
    data = response.get_json()
    assert data['short_url'].endswith('/apicustom1')

def test_api_shorten_existing_custom_alias(client, api_user):
    client.post('/api/shorten', json={ # First one
        'api_key': api_user['api_key'],
        'original_url': 'https://firstcustom.com',
        'custom_alias': 'apiexists'
    })
    response = client.post('/api/shorten', json={ # Second attempt
        'api_key': api_user['api_key'],
        'original_url': 'https://secondcustom.com',
        'custom_alias': 'apiexists'
    })
    assert response.status_code == 409
    data = response.get_json()
    assert 'error' in data
    assert data['error'] == "Custom alias already exists"

def test_api_shorten_missing_original_url(client, api_user):
    response = client.post('/api/shorten', json={'api_key': api_user['api_key']})
    assert response.status_code == 400
    data = response.get_json()
    assert data['error'] == "Original URL is missing"

def test_api_shorten_missing_api_key(client):
    response = client.post('/api/shorten', json={'original_url': 'https://noapikey.com'})
    assert response.status_code == 401
    data = response.get_json()
    assert data['error'] == "API key is missing"

def test_api_shorten_invalid_api_key(client):
    response = client.post('/api/shorten', json={
        'api_key': 'invalidkey123',
        'original_url': 'https://invalidkey.com'
    })
    assert response.status_code == 401
    data = response.get_json()
    assert data['error'] == "Invalid API key"

def test_api_shorten_malformed_json(client, api_user):
    response = client.post('/api/shorten', data='not a json string', content_type='application/json')
    assert response.status_code == 400
    data = response.get_json()
    assert data['error'] == "Invalid JSON payload"


# --- Tests for /api/analytics/<short_url_slug> ---

def test_api_analytics_successful(client, api_user):
    # Shorten a URL first
    shorten_response = client.post('/api/shorten', json={
        'api_key': api_user['api_key'],
        'original_url': 'https://analytics-test.com'
    })
    short_url_slug = shorten_response.get_json()['short_url'].split('/')[-1]

    analytics_response = client.get(f'/api/analytics/{short_url_slug}', headers={'X-API-Key': api_user['api_key']})
    assert analytics_response.status_code == 200
    data = analytics_response.get_json()
    assert data['original_url'] == 'https://analytics-test.com'
    assert data['short_url'].endswith(f'/{short_url_slug}')
    assert data['clicks'] == 0

def test_api_analytics_click_update(client, api_user):
    shorten_response = client.post('/api/shorten', json={
        'api_key': api_user['api_key'],
        'original_url': 'https://clicktest.com'
    })
    short_url_slug = shorten_response.get_json()['short_url'].split('/')[-1]

    # Visit the URL to increment clicks
    client.get(f'/{short_url_slug}')
    client.get(f'/{short_url_slug}')

    analytics_response = client.get(f'/api/analytics/{short_url_slug}', headers={'X-API-Key': api_user['api_key']})
    assert analytics_response.status_code == 200
    data = analytics_response.get_json()
    assert data['clicks'] == 2

def test_api_analytics_unauthorized_url(client, api_user):
    # User 1 (api_user) creates a URL
    shorten_res_user1 = client.post('/api/shorten', json={
        'api_key': api_user['api_key'], 'original_url': 'https://user1url.com'
    })
    slug_user1 = shorten_res_user1.get_json()['short_url'].split('/')[-1]

    # User 2
    user2 = create_user_for_api_test(client, 'apiuser2', 'apipassword2')

    # User 2 tries to access User 1's URL analytics
    analytics_response = client.get(f'/api/analytics/{slug_user1}', headers={'X-API-Key': user2['api_key']})
    assert analytics_response.status_code == 404 # or 403, based on implementation (currently 404)
    data = analytics_response.get_json()
    assert data['error'] == "Short URL not found or not authorized"


def test_api_analytics_invalid_api_key(client):
    # No need to create a URL, just try with invalid key
    response = client.get('/api/analytics/any_slug', headers={'X-API-Key': 'totallyfakekey'})
    assert response.status_code == 401
    data = response.get_json()
    assert data['error'] == "Invalid API key"

def test_api_analytics_missing_api_key_header(client):
    response = client.get('/api/analytics/any_slug') # No X-API-Key header
    assert response.status_code == 401
    data = response.get_json()
    assert data['error'] == "API key is missing from X-API-Key header"

def test_api_analytics_non_existent_slug(client, api_user):
    response = client.get('/api/analytics/nonexistentslug123', headers={'X-API-Key': api_user['api_key']})
    assert response.status_code == 404
    data = response.get_json()
    assert data['error'] == "Short URL not found"
