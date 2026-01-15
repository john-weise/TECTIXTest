# Tectix Test Suite

This directory contains automated tests for the Tectix platform.

## Quick Start

```bash
# Install dependencies
./run_tests.sh install

# Run quick smoke tests (2 min)
./run_tests.sh quick

# Run all tests (15-20 min)
./run_tests.sh all

# Run with coverage report
./run_tests.sh coverage
```

## Directory Structure

```
tests/
├── conftest.py              # Shared fixtures and configuration
├── unit/                    # Unit tests
│   ├── test_models.py      # Database model tests
│   └── test_helpers.py     # Helper function tests
├── api/                     # API endpoint tests
│   ├── test_auth.py        # Authentication tests
│   └── test_admin.py       # Admin panel tests
└── integration/             # Integration tests
    └── test_scan_workflow.py  # End-to-end workflow tests
```

## Test Categories

### Unit Tests
Test individual functions and classes in isolation.

```bash
pytest tests/unit -v -m unit
```

### API Tests
Test RESTful API endpoints.

```bash
pytest tests/api -v -m api
```

### Integration Tests
Test complete workflows across multiple components.

```bash
pytest tests/integration -v -m integration
```

## Writing New Tests

### 1. Backend Test Example

```python
import pytest

@pytest.mark.unit
def test_user_creation(db_session):
    """Test creating a new user"""
    import db

    user = db.User(username='testuser', role='user')
    user.set_password('TestPass123!')

    db_session.add(user)
    db_session.commit()

    assert user.id is not None
    assert user.check_password('TestPass123!')
```

### 2. API Test Example

```python
@pytest.mark.api
def test_login_endpoint(client):
    """Test login API endpoint"""
    response = client.post('/api/login', json={
        'username': 'testadmin',
        'password': 'TestPass123!'
    })

    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
```

### 3. Integration Test Example

```python
@pytest.mark.integration
def test_scan_workflow(client, admin_auth_headers):
    """Test complete scan workflow"""
    # Add system
    response = client.post('/api/admin/systems', json={
        'system_id': 'TEST-001'
    })
    assert response.status_code == 201

    # Run scan
    response = client.post('/process', json={
        'system_id': 'TEST-001'
    })
    assert response.status_code == 200
```

## Available Fixtures

### Database Fixtures
- `db_session` - Database session with automatic rollback
- `sample_system_data` - Sample system data dictionary
- `sample_csv_file` - Temporary CSV file for testing

### Authentication Fixtures
- `admin_auth_headers` - Authenticated admin session
- `user_auth_headers` - Authenticated user session

### Application Fixtures
- `app` - Flask application instance
- `client` - Test client for making requests

## Test Markers

Tests can be marked with pytest markers:

```python
@pytest.mark.unit        # Unit test
@pytest.mark.api         # API test
@pytest.mark.integration # Integration test
@pytest.mark.auth        # Authentication test
@pytest.mark.slow        # Slow running test (>5s)
```

Run specific markers:
```bash
pytest -m unit           # Only unit tests
pytest -m "not slow"     # Skip slow tests
pytest -m "api and auth" # API auth tests only
```

## Coverage

Generate coverage reports:

```bash
# HTML report
pytest --cov=. --cov-report=html
open htmlcov/index.html

# Terminal report
pytest --cov=. --cov-report=term-missing

# XML report (for CI)
pytest --cov=. --cov-report=xml
```

## CI/CD Integration

Tests run automatically on:
- Every push to repository
- Every pull request
- Daily at 2 AM UTC
- Manual workflow dispatch

View results: GitHub Actions tab

## Troubleshooting

### Tests fail with import errors
```bash
# Make sure dependencies are installed
pip install -r requirements-dev.txt
```

### Database errors
```bash
# Reset test database
rm -f test.db
pytest tests/
```

### Slow tests
```bash
# Skip slow tests
pytest -m "not slow"

# Run tests in parallel
pytest -n auto
```

### Flaky tests
```bash
# Run failing test multiple times
pytest tests/api/test_auth.py::test_login -v --count=10
```

## Best Practices

1. **Keep tests independent** - No test should depend on another
2. **Use descriptive names** - `test_admin_can_delete_user` not `test_1`
3. **One assertion per test** - Makes failures easier to debug
4. **Mock external services** - Don't call real APIs in tests
5. **Clean up after tests** - Use fixtures for setup/teardown
6. **Fast tests** - Keep unit tests under 100ms each

## Resources

- [pytest Documentation](https://docs.pytest.org)
- [Flask Testing](https://flask.palletsprojects.com/en/latest/testing/)
- [Automation Guide](../AUTOMATION_GUIDE.md)
