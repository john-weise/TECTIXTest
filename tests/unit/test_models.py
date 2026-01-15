"""
Unit Tests for Database Models
Tests for User, System, ScanPolicy, and other models
"""
import pytest
from datetime import datetime


@pytest.mark.unit
class TestUserModel:
    """User model unit tests"""

    def test_create_user(self, db_session):
        """Test creating a user"""
        import db

        user = db.User(
            username='unittest_user',
            role='user'
        )
        user.set_password('TestPassword123!')

        db_session.add(user)
        db_session.commit()

        assert user.id is not None
        assert user.username == 'unittest_user'
        assert user.role == 'user'

    def test_password_hashing(self, db_session):
        """Test password is hashed, not stored in plain text"""
        import db

        user = db.User(username='hashtest', role='user')
        password = 'MySecurePassword123!'
        user.set_password(password)

        # Password should be hashed
        assert user.password_hash != password
        assert len(user.password_hash) > 20

        # Should be able to verify correct password
        assert user.check_password(password) is True

        # Should reject incorrect password
        assert user.check_password('WrongPassword') is False

    def test_user_roles(self, db_session):
        """Test user role assignment"""
        import db

        admin = db.User(username='admin_test', role='admin')
        user = db.User(username='user_test', role='user')

        db_session.add_all([admin, user])
        db_session.commit()

        assert admin.role == 'admin'
        assert user.role == 'user'

    def test_2fa_secret_storage(self, db_session):
        """Test 2FA secret can be stored and retrieved"""
        import db

        user = db.User(username='2fa_test', role='user')
        user.totp_secret = 'JBSWY3DPEHPK3PXP'

        db_session.add(user)
        db_session.commit()

        retrieved = db_session.query(db.User).filter_by(username='2fa_test').first()
        assert retrieved.totp_secret == 'JBSWY3DPEHPK3PXP'


@pytest.mark.unit
class TestSystemModel:
    """System model unit tests"""

    def test_create_system_csv(self, db_session):
        """Test creating a system CSV record"""
        import db

        system = db.SystemCSV(
            system_id='TEST-001',
            csv_path='/path/to/csv/file.csv'
        )

        db_session.add(system)
        db_session.commit()

        assert system.id is not None
        assert system.system_id == 'TEST-001'
        assert system.csv_path == '/path/to/csv/file.csv'
        assert system.last_scanned is None  # Not scanned yet

    def test_update_last_scanned(self, db_session):
        """Test updating last_scanned timestamp"""
        import db

        system = db.SystemCSV(
            system_id='TEST-002',
            csv_path='/path/to/file.csv'
        )
        db_session.add(system)
        db_session.commit()

        # Update last scanned
        now = datetime.utcnow()
        system.last_scanned = now
        db_session.commit()

        retrieved = db_session.query(db.SystemCSV).filter_by(system_id='TEST-002').first()
        assert retrieved.last_scanned is not None
        assert retrieved.last_scanned == now


@pytest.mark.unit
class TestScanPolicyModel:
    """Scan policy model unit tests"""

    def test_create_scan_policy(self, db_session):
        """Test creating a scan policy"""
        import db

        policy = db.ScanPolicy(
            name='Test Daily Scan',
            frequency='DAILY',
            time_of_day='02:00',
            enabled=True
        )

        db_session.add(policy)
        db_session.commit()

        assert policy.id is not None
        assert policy.name == 'Test Daily Scan'
        assert policy.frequency == 'DAILY'
        assert policy.enabled is True

    def test_scan_policy_frequencies(self, db_session):
        """Test different scan frequencies"""
        import db

        frequencies = ['DAILY', 'WEEKLY', 'BIWEEKLY', 'MONTHLY']

        for freq in frequencies:
            policy = db.ScanPolicy(
                name=f'Test {freq} Scan',
                frequency=freq,
                enabled=True
            )
            db_session.add(policy)

        db_session.commit()

        for freq in frequencies:
            retrieved = db_session.query(db.ScanPolicy).filter_by(frequency=freq).first()
            assert retrieved is not None
            assert retrieved.frequency == freq

    def test_policy_system_enrollment(self, db_session):
        """Test enrolling systems in a policy"""
        import db

        # Create policy
        policy = db.ScanPolicy(
            name='Enrollment Test',
            frequency='WEEKLY',
            enabled=True
        )

        # Create systems
        system1 = db.SystemCSV(system_id='ENROLL-001', csv_path='/path1.csv')
        system2 = db.SystemCSV(system_id='ENROLL-002', csv_path='/path2.csv')

        db_session.add_all([policy, system1, system2])
        db_session.commit()

        # Note: Actual enrollment logic would depend on the relationship structure
        # This is a placeholder for the relationship testing
        assert policy.id is not None
        assert system1.id is not None
        assert system2.id is not None
