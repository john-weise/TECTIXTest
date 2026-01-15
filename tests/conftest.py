"""
Pytest configuration and shared fixtures for Tectix testing
"""
import pytest
import os
import tempfile
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Set test environment
os.environ['FLASK_ENV'] = 'testing'
os.environ['TESTING'] = '1'


@pytest.fixture(scope='session')
def app():
    """Create and configure a test Flask app instance"""
    import flaskapp

    # Create temporary database for testing
    db_fd, db_path = tempfile.mkstemp()

    flaskapp.app.config.update({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path}',
        'SECRET_KEY': 'test-secret-key',
        'WTF_CSRF_ENABLED': False,
    })

    # Initialize database
    with flaskapp.app.app_context():
        import db
        db.Base.metadata.create_all(bind=db.engine)

        # Create test admin user
        session = db.Session()
        admin = db.User(
            username='testadmin',
            role='admin'
        )
        admin.set_password('TestPass123!')
        session.add(admin)

        # Create test regular user
        user = db.User(
            username='testuser',
            role='user'
        )
        user.set_password('TestPass123!')
        session.add(user)

        session.commit()
        session.close()

    yield flaskapp.app

    # Cleanup
    os.close(db_fd)
    os.unlink(db_path)


@pytest.fixture
def client(app):
    """Create a test client for the app"""
    return app.test_client()


@pytest.fixture
def runner(app):
    """Create a test CLI runner"""
    return app.test_cli_runner()


@pytest.fixture
def db_session(app):
    """Create a database session for testing"""
    import db

    with app.app_context():
        session = db.Session()
        yield session
        session.rollback()
        session.close()


@pytest.fixture
def admin_auth_headers(client):
    """Get authentication headers for admin user"""
    response = client.post('/api/login', json={
        'username': 'testadmin',
        'password': 'TestPass123!'
    })

    if response.status_code == 200:
        # Session cookie is automatically handled by test client
        return {}
    else:
        pytest.fail("Failed to authenticate admin user")


@pytest.fixture
def user_auth_headers(client):
    """Get authentication headers for regular user"""
    response = client.post('/api/login', json={
        'username': 'testuser',
        'password': 'TestPass123!'
    })

    if response.status_code == 200:
        return {}
    else:
        pytest.fail("Failed to authenticate regular user")


@pytest.fixture
def sample_csv_file():
    """Create a sample CSV file for testing"""
    content = """System ID,Control,Status
TEST-001,AC-2,Compliant
TEST-001,AC-3,Non-Compliant
TEST-001,AC-6,Compliant"""

    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        f.write(content)
        temp_path = f.name

    yield temp_path

    # Cleanup
    if os.path.exists(temp_path):
        os.unlink(temp_path)


@pytest.fixture
def sample_system_data():
    """Sample system data for testing"""
    return {
        'system_id': 'TEST-SYSTEM-001',
        'system_name': 'Test System',
        'system_type': 'Major Application',
        'authorization_date': '2025-12-31'
    }


@pytest.fixture(autouse=True)
def reset_database(db_session):
    """Reset database state between tests"""
    yield
    # Cleanup happens automatically via db_session fixture rollback
