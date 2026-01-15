/**
 * Dashboard Component Tests
 * Tests for main dashboard functionality
 */
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import Dashboard from '../../pages/Dashboard';

jest.mock('axios');
import axios from 'axios';
const mockedAxios = axios as jest.Mocked<typeof axios>;

const renderDashboard = () => {
  return render(
    <BrowserRouter>
      <Dashboard />
    </BrowserRouter>
  );
};

describe('Dashboard Component', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    // Mock authenticated session
    mockedAxios.get.mockResolvedValue({
      data: { authenticated: true, username: 'testuser', role: 'admin' }
    });
  });

  test('renders dashboard elements', () => {
    renderDashboard();

    expect(screen.getByText(/dashboard/i)).toBeInTheDocument();
  });

  test('allows file upload', async () => {
    renderDashboard();

    const file = new File(['test content'], 'test.csv', { type: 'text/csv' });
    const fileInput = screen.getByLabelText(/upload/i) as HTMLInputElement;

    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => {
      expect(fileInput.files?.[0]).toBe(file);
      expect(fileInput.files).toHaveLength(1);
    });
  });

  test('submits system ID for processing', async () => {
    mockedAxios.post.mockResolvedValueOnce({
      data: { job_id: 'test-job-123', status: 'processing' }
    });

    renderDashboard();

    const systemIdInput = screen.getByPlaceholderText(/system id/i);
    const submitButton = screen.getByRole('button', { name: /process|scan|submit/i });

    fireEvent.change(systemIdInput, { target: { value: 'TEST-001' } });
    fireEvent.click(submitButton);

    await waitFor(() => {
      expect(mockedAxios.post).toHaveBeenCalledWith(
        expect.stringContaining('/process'),
        expect.objectContaining({ system_id: 'TEST-001' })
      );
    });
  });

  test('displays processing spinner during scan', async () => {
    mockedAxios.post.mockImplementation(() => new Promise(() => {}));

    renderDashboard();

    const submitButton = screen.getByRole('button', { name: /process|scan|submit/i });
    fireEvent.click(submitButton);

    await waitFor(() => {
      expect(screen.getByTestId('loading-spinner')).toBeInTheDocument();
    });
  });

  test('displays scan results after completion', async () => {
    const mockResults = {
      job_id: 'test-job-123',
      status: 'completed',
      test_results: [
        { test_number: 1, result: 'PASS', message: 'Test passed' },
        { test_number: 2, result: 'FAIL', message: 'Test failed' }
      ],
      readiness_score: 75
    };

    mockedAxios.post.mockResolvedValueOnce({ data: { job_id: 'test-job-123' } });
    mockedAxios.get.mockResolvedValueOnce({ data: mockResults });

    renderDashboard();

    const submitButton = screen.getByRole('button', { name: /process|scan|submit/i });
    fireEvent.click(submitButton);

    await waitFor(() => {
      expect(screen.getByText(/75/)).toBeInTheDocument(); // Readiness score
    });
  });
});

describe('Dashboard - Error Handling', () => {
  test('displays error when scan fails', async () => {
    mockedAxios.post.mockRejectedValueOnce({
      response: { data: { error: 'System not found' } }
    });

    renderDashboard();

    const submitButton = screen.getByRole('button', { name: /process|scan|submit/i });
    fireEvent.click(submitButton);

    await waitFor(() => {
      expect(screen.getByText(/system not found/i)).toBeInTheDocument();
    });
  });

  test('handles network errors gracefully', async () => {
    mockedAxios.post.mockRejectedValueOnce(new Error('Network error'));

    renderDashboard();

    const submitButton = screen.getByRole('button', { name: /process|scan|submit/i });
    fireEvent.click(submitButton);

    await waitFor(() => {
      expect(screen.getByText(/error|failed/i)).toBeInTheDocument();
    });
  });
});
