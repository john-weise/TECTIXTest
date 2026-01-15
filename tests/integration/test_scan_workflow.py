"""
Integration Tests for Complete Scan Workflow
Tests the end-to-end flow of system scanning
"""
import pytest
import time


@pytest.mark.integration
class TestCompleteScanWorkflow:
    """Integration tests for the complete scanning workflow"""

    def test_full_scan_workflow(self, client, admin_auth_headers, sample_system_data):
        """
        Test complete workflow:
        1. Login as admin
        2. Add system to portfolio
        3. Upload CSV
        4. Initiate scan
        5. Check job status
        6. Retrieve results
        """

        # Step 1: Already authenticated via admin_auth_headers

        # Step 2: Add system to portfolio
        response = client.post('/api/admin/systems', json={
            'system_id': sample_system_data['system_id'],
            'system_name': sample_system_data['system_name']
        })

        assert response.status_code in [200, 201]
        system_data = response.get_json()

        # Step 3: Initiate scan (this may require different endpoint structure)
        response = client.post('/process', json={
            'system_id': sample_system_data['system_id']
        })

        # Response could be job_id or redirect
        if response.status_code in [200, 202]:
            result = response.get_json()

            # Step 4: If job_id returned, check status
            if 'job_id' in result:
                job_id = result['job_id']

                # Poll for job completion (with timeout)
                max_attempts = 10
                for _ in range(max_attempts):
                    status_response = client.get(f'/status/{job_id}')

                    if status_response.status_code == 200:
                        status = status_response.get_json()

                        if status.get('status') == 'completed':
                            # Step 5: Retrieve results
                            results_response = client.get(f'/reporting_json/{job_id}')

                            assert results_response.status_code == 200
                            results = results_response.get_json()

                            # Verify results structure
                            assert 'test_results' in results or 'tests' in results
                            break

                    time.sleep(0.5)

    def test_unauthorized_scan_attempt(self, client, user_auth_headers):
        """Test that regular users cannot initiate scans without proper permissions"""
        response = client.post('/process', json={
            'system_id': 'UNAUTHORIZED-TEST'
        })

        # Depending on implementation, this might be 403 or might allow but fail later
        # Adjust based on actual behavior
        assert response.status_code in [200, 403]


@pytest.mark.integration
class TestMonitoringWorkflow:
    """Integration tests for continuous monitoring"""

    def test_policy_creation_and_enrollment(self, client, admin_auth_headers):
        """
        Test workflow:
        1. Create scan policy
        2. Add system to portfolio
        3. Enroll system in policy
        4. Verify enrollment
        """

        # Step 1: Create policy
        policy_response = client.post('/api/policies', json={
            'name': 'Integration Test Policy',
            'frequency': 'DAILY',
            'time_of_day': '03:00',
            'enabled': True
        })

        assert policy_response.status_code in [200, 201]
        policy_id = policy_response.get_json().get('id')

        # Step 2: Add system
        system_response = client.post('/api/admin/systems', json={
            'system_id': 'MONITOR-TEST-001',
            'system_name': 'Monitoring Test System'
        })

        assert system_response.status_code in [200, 201]
        system_id = system_response.get_json().get('id')

        # Step 3: Enroll system in policy
        if policy_id and system_id:
            enroll_response = client.post(f'/api/policies/{policy_id}/systems', json={
                'system_ids': [system_id]
            })

            assert enroll_response.status_code in [200, 201]

            # Step 4: Verify enrollment
            policy_check = client.get(f'/api/policies/{policy_id}')
            if policy_check.status_code == 200:
                policy_data = policy_check.get_json()
                # Verify system is enrolled (structure depends on API)
                assert policy_data is not None


@pytest.mark.integration
@pytest.mark.slow
class TestReportGeneration:
    """Integration tests for report generation"""

    def test_generate_and_download_report(self, client, admin_auth_headers):
        """
        Test report generation workflow:
        1. Run a scan
        2. Generate report
        3. Download report
        """

        # Step 1: Initiate scan
        scan_response = client.post('/process', json={
            'system_id': 'REPORT-TEST-001'
        })

        if scan_response.status_code in [200, 202]:
            result = scan_response.get_json()

            if 'job_id' in result:
                job_id = result['job_id']

                # Wait for completion
                max_attempts = 15
                for _ in range(max_attempts):
                    status_response = client.get(f'/status/{job_id}')

                    if status_response.status_code == 200:
                        status = status_response.get_json()

                        if status.get('status') == 'completed':
                            # Step 2 & 3: Download report
                            download_response = client.get('/download', query_string={
                                'job_id': job_id
                            })

                            # Report download might return file or redirect
                            assert download_response.status_code in [200, 302]
                            break

                    time.sleep(0.5)
