import pytest
import tempfile
import os
from app import app as flask_app # Import your Flask app instance
from app import create_table # Import your create_table function

@pytest.fixture
def app():
    """Create and configure a new app instance for each test."""
    # Create a temporary file for the SQLite DB
    db_fd, db_path = tempfile.mkstemp()

    flask_app.config.update({
        "TESTING": True,
        "DATABASE": db_path, # Use the temporary database
        "SECRET_KEY": "testsecretkey", # Known secret key for testing
        "WTF_CSRF_ENABLED": False, # Disable CSRF for forms if you were using Flask-WTF
        "LOGIN_DISABLED": False, # Ensure login is not disabled for auth tests
    })

    # Create the database tables in the temporary database
    with flask_app.app_context():
        create_table()

    yield flask_app

    # Close and remove the temporary database file
    os.close(db_fd)
    os.unlink(db_path)

@pytest.fixture
def client(app):
    """A test client for the app."""
    return app.test_client()

@pytest.fixture
def runner(app):
    """A test runner for click commands."""
    return app.test_cli_runner()
