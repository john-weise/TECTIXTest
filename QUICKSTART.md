# Tectix Testing - Quick Start Guide

**Time to get started: 5 minutes**

---

## 1. First Time Setup (One Time)

Run the setup script to install everything:

```bash
cd /path/to/TECTIXTest
./setup_tests.sh
```

This will:
- Create a Python virtual environment
- Install pytest and testing tools
- Install frontend testing dependencies
- Take ~5 minutes on first run

---

## 2. Run Your First Tests (30 seconds)

### Quick Smoke Test (Fastest - 2 min)
```bash
./run_tests.sh quick
```

This runs the most critical tests to verify everything works.

**Expected Output:**
```
========================================
Running Quick Smoke Tests
========================================
tests/unit/test_models.py::TestUserModel::test_create_user ✓ PASSED
tests/api/test_auth.py::TestAuthentication::test_login_success ✓ PASSED
...
✓ Smoke tests completed
```

---

## 3. Understanding Test Commands

### Run Specific Test Categories

```bash
# Backend API tests only (~4 min)
./run_tests.sh api

# Frontend React tests only (~3 min)
./run_tests.sh frontend

# Unit tests only (~2 min)
./run_tests.sh unit

# Integration tests only (~8 min)
./run_tests.sh integration

# Authentication tests only (~1 min)
./run_tests.sh auth
```

### Run Everything

```bash
# All tests with coverage report (~15-20 min)
./run_tests.sh all
```

### Security & Quality

```bash
# Run security scans (~3 min)
./run_tests.sh security

# Generate coverage report (~15 min)
./run_tests.sh coverage
```

---

## 4. Reading Test Results

### ✅ Successful Test Output

```bash
tests/api/test_auth.py::TestAuthentication::test_login_success PASSED [100%]

===================== 1 passed in 0.23s =====================
```

**What this means:**
- ✅ Test passed
- File: `tests/api/test_auth.py`
- Test: `test_login_success`
- Time: 0.23 seconds

### ❌ Failed Test Output

```bash
tests/api/test_auth.py::TestAuthentication::test_login_success FAILED [100%]

________________________ FAILURES _________________________
def test_login_success(client):
    response = client.post('/api/login', json={
        'username': 'testadmin',
        'password': 'TestPass123!'
    })
>   assert response.status_code == 200
E   assert 401 == 200

===================== 1 failed in 0.45s =====================
```

**What this means:**
- ❌ Test failed
- Expected: status code 200
- Got: status code 401 (unauthorized)
- Need to investigate why login failed

---

## 5. Common Workflows

### A. Before Committing Code

```bash
# 1. Run affected tests quickly
./run_tests.sh quick

# 2. If you changed backend code
./run_tests.sh api

# 3. If you changed frontend code
./run_tests.sh frontend
```

### B. Before Creating a Pull Request

```bash
# Run all tests to ensure nothing broke
./run_tests.sh all
```

### C. Investigating a Bug

```bash
# Run specific test file
source venv/bin/activate
pytest tests/api/test_auth.py -v

# Run single test function
pytest tests/api/test_auth.py::TestAuthentication::test_login_success -v

# Run with detailed output
pytest tests/api/test_auth.py -vv --tb=long
```

### D. Checking Code Coverage

```bash
# Generate coverage report
./run_tests.sh coverage

# View results
# Backend: open htmlcov/index.html
# Frontend: open react_src/coverage/lcov-report/index.html
```

---

## 6. Advanced Usage

### Run Tests with Pytest Directly

First, activate the virtual environment:

```bash
source venv/bin/activate
```

Then use pytest commands:

```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/api/test_auth.py -v

# Run tests matching a pattern
pytest tests/ -k "login" -v

# Run tests with markers
pytest tests/ -m "unit" -v
pytest tests/ -m "api and auth" -v

# Skip slow tests
pytest tests/ -m "not slow" -v

# Run with coverage
pytest tests/ --cov=. --cov-report=html

# Run tests in parallel (faster)
pytest tests/ -n auto
```

### Run Frontend Tests with NPM

```bash
cd react_src

# Run all tests
npm test

# Run specific test file
npm test -- Login.test.tsx

# Run with coverage
npm test -- --coverage --watchAll=false

# Update snapshots
npm test -- -u

# Run in watch mode (auto-rerun on changes)
npm test
```

---

## 7. Viewing Test Coverage

### Backend Coverage (Python)

```bash
# Generate HTML coverage report
pytest tests/ --cov=. --cov-report=html

# Open in browser (Linux)
xdg-open htmlcov/index.html

# Or manually navigate to:
# file:///path/to/TECTIXTest/htmlcov/index.html
```

**What to look for:**
- Green lines = tested
- Red lines = not tested
- Target: 80%+ coverage

### Frontend Coverage (React)

```bash
cd react_src
npm test -- --coverage --watchAll=false

# Open in browser (Linux)
xdg-open coverage/lcov-report/index.html

# Or manually navigate to:
# file:///path/to/TECTIXTest/react_src/coverage/lcov-report/index.html
```

---

## 8. CI/CD Automation (Already Setup!)

Tests run automatically on GitHub when you:
- Push code to any branch
- Create a pull request
- Daily at 2 AM UTC

### Viewing CI Results

1. Go to your GitHub repo
2. Click **"Actions"** tab
3. Click on latest workflow run
4. View test results for:
   - Backend tests
   - Frontend tests
   - Security scans

**Green checkmark** ✅ = All tests passed
**Red X** ❌ = Some tests failed (click to see details)

---

## 9. Troubleshooting

### Problem: "pytest: command not found"

**Solution:** Activate virtual environment first
```bash
source venv/bin/activate
```

### Problem: "ModuleNotFoundError: No module named 'flask'"

**Solution:** Install dependencies
```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### Problem: Tests fail with database errors

**Solution:** Reset test database
```bash
rm -f test.db *.db
pytest tests/
```

### Problem: Frontend tests fail with import errors

**Solution:** Install npm dependencies
```bash
cd react_src
npm install
```

### Problem: Tests are too slow

**Solution 1:** Skip slow tests
```bash
pytest tests/ -m "not slow"
```

**Solution 2:** Run in parallel
```bash
pip install pytest-xdist
pytest tests/ -n auto
```

### Problem: Tests pass locally but fail in CI

**Possible causes:**
- Different Python/Node versions
- Missing dependencies in requirements.txt
- Environment-specific configuration

**Check:** Compare versions in `.github/workflows/tests.yml` with local

---

## 10. Next Steps

### For Your Team

1. **Person 1 (Backend Lead):**
   ```bash
   # Daily routine
   ./run_tests.sh quick          # 2 min
   ./run_tests.sh api            # When changing APIs
   ```

2. **Person 2 (Frontend Lead):**
   ```bash
   # Daily routine
   ./run_tests.sh frontend       # 3 min
   cd react_src && npm test      # When changing components
   ```

3. **Person 3 (Integration Lead):**
   ```bash
   # Before releases
   ./run_tests.sh integration    # 8 min
   ./run_tests.sh all           # Full test suite
   ```

### Adding New Tests

See detailed examples in:
- `tests/README.md` - How to write tests
- `AUTOMATION_GUIDE.md` - Full documentation

**Quick example:**

```python
# tests/api/test_new_feature.py
import pytest

@pytest.mark.api
def test_my_new_endpoint(client, admin_auth_headers):
    """Test description"""
    response = client.get('/api/my-endpoint')

    assert response.status_code == 200
    assert response.get_json()['success'] is True
```

---

## 11. Cheat Sheet

### Most Common Commands

```bash
# Setup (first time only)
./setup_tests.sh

# Quick test before commit (2 min)
./run_tests.sh quick

# Backend tests (4 min)
./run_tests.sh api

# Frontend tests (3 min)
./run_tests.sh frontend

# Everything (15-20 min)
./run_tests.sh all

# With coverage report
./run_tests.sh coverage

# Security scans
./run_tests.sh security

# Clean up test files
./run_tests.sh clean

# Help
./run_tests.sh help
```

### Direct Pytest Commands

```bash
# Activate environment first!
source venv/bin/activate

# Run all tests
pytest tests/ -v

# Run specific file
pytest tests/api/test_auth.py -v

# Run single test
pytest tests/api/test_auth.py::test_login_success -v

# Run by keyword
pytest tests/ -k "login" -v

# Run by marker
pytest tests/ -m "api" -v

# Skip slow tests
pytest tests/ -m "not slow" -v

# With coverage
pytest tests/ --cov=. --cov-report=html
```

---

## 12. Getting Help

### Documentation

- **This file** - Quick start guide
- **AUTOMATION_GUIDE.md** - Comprehensive guide (50 pages)
- **tests/README.md** - Test writing examples
- **pytest.ini** - Test configuration

### Run Help Command

```bash
./run_tests.sh help
```

### View Available Test Markers

```bash
source venv/bin/activate
pytest --markers
```

### View Available Fixtures

```bash
pytest --fixtures
```

---

## Summary: Your Daily Workflow

```bash
# 1. First time setup (5 min, once)
./setup_tests.sh

# 2. Before committing (2 min)
./run_tests.sh quick

# 3. Before PR (15 min)
./run_tests.sh all

# 4. Weekly coverage check
./run_tests.sh coverage
```

**That's it!** You're now ready to use the test automation framework.

---

## Questions?

Check these resources:
1. Run `./run_tests.sh help`
2. Read `AUTOMATION_GUIDE.md`
3. Check `tests/README.md`
4. Look at example tests in `tests/api/test_auth.py`
