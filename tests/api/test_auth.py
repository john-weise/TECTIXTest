"""
API Authentication Tests
Tests for login, logout, session management, and 2FA
"""
import pytest


@pytest.mark.api
@pytest.mark.auth
class TestAuthentication:
    """Authentication endpoint tests"""

    def test_login_success(self, client):
        """Test successful login with valid credentials"""
        response = client.post('/api/login', json={
            'username': 'testadmin',
            'password': 'TestPass123!'
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['username'] == 'testadmin'
        assert data['role'] == 'admin'

    def test_login_invalid_username(self, client):
        """Test login with non-existent username"""
        response = client.post('/api/login', json={
            'username': 'nonexistent',
            'password': 'password'
        })

        assert response.status_code == 401
        data = response.get_json()
        assert data['success'] is False

    def test_login_invalid_password(self, client):
        """Test login with incorrect password"""
        response = client.post('/api/login', json={
            'username': 'testadmin',
            'password': 'wrongpassword'
        })

        assert response.status_code == 401
        data = response.get_json()
        assert data['success'] is False

    def test_login_missing_credentials(self, client):
        """Test login with missing credentials"""
        response = client.post('/api/login', json={})

        assert response.status_code in [400, 422]

    def test_session_check_authenticated(self, client, admin_auth_headers):
        """Test session check for authenticated user"""
        response = client.get('/api/session')

        assert response.status_code == 200
        data = response.get_json()
        assert data['authenticated'] is True
        assert data['username'] == 'testadmin'

    def test_session_check_unauthenticated(self, client):
        """Test session check without authentication"""
        response = client.get('/api/session')

        assert response.status_code == 200
        data = response.get_json()
        assert data['authenticated'] is False

    def test_logout(self, client, admin_auth_headers):
        """Test logout functionality"""
        # Verify we're logged in
        response = client.get('/api/session')
        assert response.get_json()['authenticated'] is True

        # Logout
        response = client.post('/api/logout')
        assert response.status_code == 200

        # Verify we're logged out
        response = client.get('/api/session')
        assert response.get_json()['authenticated'] is False


@pytest.mark.api
@pytest.mark.auth
class TestTwoFactorAuth:
    """Two-factor authentication tests"""

    def test_2fa_status_not_enrolled(self, client, user_auth_headers):
        """Test 2FA status when not enrolled"""
        response = client.get('/api/account/2fa/status')

        assert response.status_code == 200
        data = response.get_json()
        assert data['enrolled'] is False

    def test_2fa_enrollment_start(self, client, user_auth_headers):
        """Test starting 2FA enrollment"""
        response = client.post('/api/account/2fa/start')

        assert response.status_code == 200
        data = response.get_json()
        assert 'qr_code' in data
        assert 'secret' in data

    def test_unauthorized_access_to_2fa_endpoints(self, client):
        """Test accessing 2FA endpoints without authentication"""
        endpoints = [
            '/api/account/2fa/status',
            '/api/account/2fa/start',
        ]

        for endpoint in endpoints:
            response = client.get(endpoint)
            assert response.status_code in [401, 403]


@pytest.mark.api
@pytest.mark.auth
class TestRoleBasedAccess:
    """Role-based access control tests"""

    def test_admin_can_access_admin_endpoints(self, client, admin_auth_headers):
        """Test admin can access admin-only endpoints"""
        response = client.get('/api/admin/users')

        assert response.status_code == 200

    def test_user_cannot_access_admin_endpoints(self, client, user_auth_headers):
        """Test regular user cannot access admin endpoints"""
        response = client.get('/api/admin/users')

        assert response.status_code == 403

    def test_unauthenticated_cannot_access_protected_endpoints(self, client):
        """Test unauthenticated requests are blocked"""
        protected_endpoints = [
            '/api/admin/users',
            '/api/admin/systems',
            '/api/policies',
            '/api/account/password',
        ]

        for endpoint in protected_endpoints:
            response = client.get(endpoint)
            assert response.status_code in [401, 403], f"Endpoint {endpoint} should be protected"
