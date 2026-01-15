"""
API Admin Panel Tests
Tests for user management, system management, and admin operations
"""
import pytest


@pytest.mark.api
class TestUserManagement:
    """Admin user management endpoint tests"""

    def test_list_users(self, client, admin_auth_headers):
        """Test listing all users"""
        response = client.get('/api/admin/users')

        assert response.status_code == 200
        data = response.get_json()
        assert 'users' in data
        assert len(data['users']) >= 2  # testadmin and testuser

    def test_create_user(self, client, admin_auth_headers):
        """Test creating a new user"""
        response = client.post('/api/admin/users', json={
            'username': 'newuser',
            'password': 'NewPass123!',
            'role': 'user'
        })

        assert response.status_code in [200, 201]
        data = response.get_json()
        assert data['success'] is True

        # Verify user was created
        response = client.get('/api/admin/users')
        users = response.get_json()['users']
        assert any(u['username'] == 'newuser' for u in users)

    def test_create_user_duplicate_username(self, client, admin_auth_headers):
        """Test creating user with duplicate username"""
        response = client.post('/api/admin/users', json={
            'username': 'testadmin',  # Already exists
            'password': 'SomePass123!',
            'role': 'user'
        })

        assert response.status_code in [400, 409]

    def test_create_user_invalid_data(self, client, admin_auth_headers):
        """Test creating user with invalid data"""
        # Missing password
        response = client.post('/api/admin/users', json={
            'username': 'incomplete'
        })

        assert response.status_code in [400, 422]

    def test_delete_user(self, client, admin_auth_headers):
        """Test deleting a user"""
        # Create user to delete
        client.post('/api/admin/users', json={
            'username': 'tobedeleted',
            'password': 'Pass123!',
            'role': 'user'
        })

        # Delete the user
        response = client.delete('/api/admin/users/tobedeleted')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True

        # Verify user was deleted
        response = client.get('/api/admin/users')
        users = response.get_json()['users']
        assert not any(u['username'] == 'tobedeleted' for u in users)

    def test_delete_nonexistent_user(self, client, admin_auth_headers):
        """Test deleting a user that doesn't exist"""
        response = client.delete('/api/admin/users/doesnotexist')

        assert response.status_code == 404

    def test_regular_user_cannot_manage_users(self, client, user_auth_headers):
        """Test regular users cannot access user management"""
        response = client.get('/api/admin/users')

        assert response.status_code == 403


@pytest.mark.api
class TestSystemManagement:
    """Admin system management endpoint tests"""

    def test_list_systems(self, client, admin_auth_headers):
        """Test listing portfolio systems"""
        response = client.get('/api/admin/systems')

        assert response.status_code == 200
        data = response.get_json()
        assert 'systems' in data or isinstance(data, list)

    def test_add_system(self, client, admin_auth_headers):
        """Test adding a system to portfolio"""
        response = client.post('/api/admin/systems', json={
            'system_id': 'TEST-SYS-001',
            'system_name': 'Test System',
            'description': 'Test description'
        })

        assert response.status_code in [200, 201]
        data = response.get_json()
        assert data.get('success') is True or 'id' in data

    def test_add_system_missing_id(self, client, admin_auth_headers):
        """Test adding system without required system_id"""
        response = client.post('/api/admin/systems', json={
            'system_name': 'Incomplete System'
        })

        assert response.status_code in [400, 422]

    def test_upload_system_csv(self, client, admin_auth_headers, sample_csv_file):
        """Test uploading CSV for a system"""
        # First create a system
        response = client.post('/api/admin/systems', json={
            'system_id': 'CSV-TEST-001',
            'system_name': 'CSV Test System'
        })

        if response.status_code in [200, 201]:
            system_data = response.get_json()
            system_id = system_data.get('id') or system_data.get('system_id')

            # Upload CSV
            with open(sample_csv_file, 'rb') as f:
                response = client.post(
                    f'/api/admin/systems/{system_id}/csv',
                    data={'file': (f, 'test.csv')},
                    content_type='multipart/form-data'
                )

            assert response.status_code in [200, 201]

    def test_delete_system(self, client, admin_auth_headers):
        """Test removing a system from portfolio"""
        # Create system to delete
        response = client.post('/api/admin/systems', json={
            'system_id': 'DEL-TEST-001',
            'system_name': 'To Be Deleted'
        })

        if response.status_code in [200, 201]:
            system_data = response.get_json()
            system_id = system_data.get('id') or system_data.get('system_id')

            # Delete the system
            response = client.delete(f'/api/admin/systems/{system_id}')

            assert response.status_code == 200


@pytest.mark.api
class TestScanPolicies:
    """Scan policy management endpoint tests"""

    def test_list_policies(self, client, admin_auth_headers):
        """Test listing all scan policies"""
        response = client.get('/api/policies')

        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data, (list, dict))

    def test_create_scan_policy(self, client, admin_auth_headers):
        """Test creating a new scan policy"""
        response = client.post('/api/policies', json={
            'name': 'Daily Test Scan',
            'frequency': 'DAILY',
            'time_of_day': '02:00',
            'enabled': True
        })

        assert response.status_code in [200, 201]
        data = response.get_json()
        assert 'id' in data or data.get('success') is True

    def test_create_policy_invalid_frequency(self, client, admin_auth_headers):
        """Test creating policy with invalid frequency"""
        response = client.post('/api/policies', json={
            'name': 'Invalid Policy',
            'frequency': 'HOURLY',  # Not a valid option
            'enabled': True
        })

        assert response.status_code in [400, 422]

    def test_update_scan_policy(self, client, admin_auth_headers):
        """Test updating an existing scan policy"""
        # Create policy first
        response = client.post('/api/policies', json={
            'name': 'Original Name',
            'frequency': 'WEEKLY',
            'enabled': False
        })

        if response.status_code in [200, 201]:
            policy_id = response.get_json().get('id')

            # Update the policy
            response = client.put(f'/api/policies/{policy_id}', json={
                'name': 'Updated Name',
                'enabled': True
            })

            assert response.status_code == 200

    def test_delete_scan_policy(self, client, admin_auth_headers):
        """Test deleting a scan policy"""
        # Create policy to delete
        response = client.post('/api/policies', json={
            'name': 'To Delete',
            'frequency': 'MONTHLY'
        })

        if response.status_code in [200, 201]:
            policy_id = response.get_json().get('id')

            # Delete the policy
            response = client.delete(f'/api/policies/{policy_id}')

            assert response.status_code == 200
