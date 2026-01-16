# Tectix Testing Workflow

Visual guide for using the test automation framework.

---

## 🎯 Daily Workflow

```
┌─────────────────────────────────────────────────────┐
│         DEVELOPMENT WORKFLOW WITH TESTS             │
└─────────────────────────────────────────────────────┘

    ┌──────────────┐
    │  Write Code  │
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │ Run Quick    │◄────── ./run_tests.sh quick
    │ Tests (2min) │        (smoke test)
    └──────┬───────┘
           │
           ▼
      ┌────────┐
      │ Pass?  │
      └───┬────┘
          │
    ┌─────┴─────┐
    │           │
   YES         NO
    │           │
    │           ▼
    │    ┌──────────────┐
    │    │  Fix Issues  │
    │    └──────┬───────┘
    │           │
    │           └────────┐
    │                    │
    ▼                    ▼
┌──────────┐      ┌──────────────┐
│  Commit  │      │  Debug Tests │
│   Code   │      └──────────────┘
└────┬─────┘
     │
     ▼
┌──────────────┐
│  Push Code   │
└──────┬───────┘
       │
       ▼
┌──────────────────┐
│  CI/CD Runs      │◄────── Automatic
│  All Tests       │        (GitHub Actions)
└──────┬───────────┘
       │
       ▼
  ┌────────┐
  │ Pass?  │
  └───┬────┘
      │
  ┌───┴────┐
  │        │
 YES      NO
  │        │
  │        ▼
  │   ┌────────────┐
  │   │ Review CI  │
  │   │   Logs     │
  │   └────────────┘
  │
  ▼
┌──────────────┐
│  Create PR   │
└──────────────┘
```

---

## 🔄 Test Frequency by Role

### Person 1: Backend/API Testing Lead

```
Daily (20 min total):
├─ Morning (10 min)
│  └─ Review CI results from overnight
│
├─ Before Each Commit (5 min)
│  ├─ ./run_tests.sh quick
│  └─ ./run_tests.sh api  (if API changes)
│
└─ End of Day (5 min)
   └─ Review coverage gaps

Weekly (1 hour):
└─ Friday afternoon
   ├─ Add tests for new features
   ├─ Review test maintenance
   └─ Update fixtures if needed
```

### Person 2: Frontend/UX Testing Lead

```
Daily (15 min total):
├─ Morning (5 min)
│  └─ Review frontend test results
│
├─ Before Each Commit (5 min)
│  └─ cd react_src && npm test
│
└─ End of Day (5 min)
   └─ Manual UI spot-check

Weekly (1.5 hours):
└─ Thursday afternoon
   ├─ Cross-browser testing (30 min)
   ├─ Add component tests (30 min)
   └─ Accessibility checks (30 min)
```

### Person 3: Integration/E2E Testing Lead

```
Daily (15 min):
└─ Morning
   ├─ Check integration test results
   └─ Investigate any flaky tests

Before Release (2 hours):
├─ Run full integration suite
├─ Manual E2E testing
└─ Performance spot-checks

Weekly (1 hour):
└─ Wednesday afternoon
   ├─ Update integration tests
   ├─ Optimize slow tests
   └─ Database maintenance
```

---

## 📊 Test Execution Decision Tree

```
Need to test something?
        │
        ▼
┌───────────────────┐
│ What changed?     │
└───────┬───────────┘
        │
    ┌───┴────────────────────┬─────────────────┬──────────────┐
    │                        │                 │              │
    ▼                        ▼                 ▼              ▼
┌────────┐            ┌──────────┐      ┌──────────┐   ┌──────────┐
│Backend │            │Frontend  │      │Database  │   │Everything│
│  Code  │            │   Code   │      │  Models  │   │          │
└───┬────┘            └─────┬────┘      └─────┬────┘   └─────┬────┘
    │                       │                  │              │
    ▼                       ▼                  ▼              ▼
./run_tests.sh api   cd react_src       ./run_tests.sh   ./run_tests.sh
                     npm test            unit             all

Time: 4 min          Time: 3 min        Time: 2 min      Time: 15 min
```

---

## 🎬 Step-by-Step: First Time Usage

### Step 1: Setup (5 minutes, one time)

```bash
cd /path/to/TECTIXTest

# Run setup script
./setup_tests.sh

# Wait for installation...
# ✓ Virtual environment created
# ✓ Python dependencies installed
# ✓ Frontend dependencies installed
```

### Step 2: Verify Installation

```bash
# Quick smoke test
./run_tests.sh quick

# Expected output:
# ========================================
# Running Quick Smoke Tests
# ========================================
# tests/unit/test_models.py::TestUserModel::test_create_user PASSED
# tests/api/test_auth.py::TestAuthentication::test_login_success PASSED
# ✓ Smoke tests completed
```

### Step 3: Run Full Test Suite

```bash
# Run all tests to see everything works
./run_tests.sh all

# This will run:
# - Backend unit tests (2 min)
# - Backend API tests (4 min)
# - Backend integration tests (8 min)
# - Frontend tests (3 min)
# Total: ~15-20 minutes
```

### Step 4: Check Coverage

```bash
# Generate coverage reports
./run_tests.sh coverage

# Opens HTML reports showing:
# - Which lines are tested (green)
# - Which lines need tests (red)
# - Overall coverage percentage
```

---

## 🔍 Test Execution Examples

### Example 1: Quick Pre-Commit Check

```bash
$ ./run_tests.sh quick

========================================
Running Quick Smoke Tests
========================================
tests/unit/test_models.py::TestUserModel::test_create_user PASSED [ 20%]
tests/unit/test_models.py::TestUserModel::test_password_hashing PASSED [ 40%]
tests/api/test_auth.py::TestAuthentication::test_login_success PASSED [ 60%]
tests/api/test_auth.py::TestAuthentication::test_session_check_authenticated PASSED [ 80%]
tests/api/test_auth.py::TestAuthentication::test_logout PASSED [100%]

============ 5 passed in 1.23s ============
✓ Smoke tests completed
```

### Example 2: Running API Tests

```bash
$ ./run_tests.sh api

========================================
Running API Tests
========================================
tests/api/test_auth.py::TestAuthentication::test_login_success PASSED
tests/api/test_auth.py::TestAuthentication::test_login_invalid_username PASSED
tests/api/test_auth.py::TestAuthentication::test_login_invalid_password PASSED
tests/api/test_auth.py::TestAuthentication::test_login_missing_credentials PASSED
tests/api/test_auth.py::TestAuthentication::test_session_check_authenticated PASSED
tests/api/test_auth.py::TestAuthentication::test_session_check_unauthenticated PASSED
tests/api/test_auth.py::TestAuthentication::test_logout PASSED
tests/api/test_auth.py::TestTwoFactorAuth::test_2fa_status_not_enrolled PASSED
tests/api/test_auth.py::TestTwoFactorAuth::test_2fa_enrollment_start PASSED
tests/api/test_auth.py::TestTwoFactorAuth::test_unauthorized_access_to_2fa_endpoints PASSED
tests/api/test_auth.py::TestRoleBasedAccess::test_admin_can_access_admin_endpoints PASSED
tests/api/test_auth.py::TestRoleBasedAccess::test_user_cannot_access_admin_endpoints PASSED
tests/api/test_auth.py::TestRoleBasedAccess::test_unauthenticated_cannot_access_protected_endpoints PASSED
tests/api/test_admin.py::TestUserManagement::test_list_users PASSED
tests/api/test_admin.py::TestUserManagement::test_create_user PASSED
...

============ 28 passed in 4.56s ============
✓ API tests completed
```

### Example 3: Failed Test Example

```bash
$ ./run_tests.sh api

========================================
Running API Tests
========================================
tests/api/test_auth.py::TestAuthentication::test_login_success FAILED

________________________ FAILURES _________________________
________ TestAuthentication.test_login_success _________

client = <FlaskClient>

    def test_login_success(client):
        response = client.post('/api/login', json={
            'username': 'testadmin',
            'password': 'TestPass123!'
        })

>       assert response.status_code == 200
E       AssertionError: assert 401 == 200
E        +  where 401 = <Response 21 bytes [401 UNAUTHORIZED]>.status_code

tests/api/test_auth.py:18: AssertionError
============ 1 failed in 0.89s ============

✗ API tests failed
```

**What to do:**
1. Check if test user exists in database
2. Verify password is correct
3. Check authentication logic in `flaskapp.py`
4. Run test with more verbosity: `pytest tests/api/test_auth.py::test_login_success -vv`

---

## 🎨 Coverage Report Example

After running `./run_tests.sh coverage`, open `htmlcov/index.html`:

```
Coverage Report
===============

Module                  Stmts    Miss   Cover
---------------------------------------------
flaskapp.py              450      90     80%
db.py                    120      15     87%
helpers.py                45       5     89%
engine/tests.py         1200     600     50%
---------------------------------------------
TOTAL                   1815     710     61%
```

**What to focus on:**
- ✅ Green = Well tested (>80%)
- ⚠️ Yellow = Needs more tests (60-80%)
- ❌ Red = Poorly tested (<60%)

Click on files to see line-by-line coverage.

---

## 📋 Checklist for Team Adoption

### Week 1: Setup & Training
- [ ] Run `./setup_tests.sh` on all dev machines
- [ ] Each team member runs `./run_tests.sh quick` successfully
- [ ] Review `QUICKSTART.md` together
- [ ] Each person runs tests for their area (backend/frontend/integration)

### Week 2: Integration
- [ ] Add tests to PR review checklist
- [ ] Verify CI pipeline runs on all PRs
- [ ] Fix any failing tests
- [ ] Establish "no PR without tests" policy

### Week 3: Expansion
- [ ] Add 5-10 new tests for recent features
- [ ] Reach 70% coverage target
- [ ] Set up coverage badges
- [ ] Document custom test scenarios

### Week 4: Optimization
- [ ] Identify and fix flaky tests
- [ ] Optimize slow tests
- [ ] Add parallel test execution
- [ ] Review and improve test data

---

## 🚨 Common Scenarios & Solutions

### Scenario 1: "Tests are failing in CI but pass locally"

**Diagnose:**
```bash
# Check CI logs on GitHub Actions tab
# Compare Python/Node versions with CI

# Local versions:
python3 --version
node --version

# CI versions: Check .github/workflows/tests.yml
```

**Fix:**
- Update local environment to match CI
- Or update CI to match local (update workflow file)

### Scenario 2: "Tests are too slow"

**Quick fixes:**
```bash
# Skip slow tests
pytest tests/ -m "not slow" -v

# Run in parallel
pip install pytest-xdist
pytest tests/ -n auto
```

### Scenario 3: "Need to test a specific feature"

```bash
# Run tests matching keyword
pytest tests/ -k "login" -v

# Or run specific test file
pytest tests/api/test_auth.py -v

# Or specific test function
pytest tests/api/test_auth.py::TestAuthentication::test_login_success -v
```

### Scenario 4: "Coverage report shows gaps"

```bash
# Generate coverage with missing lines
pytest tests/ --cov=. --cov-report=term-missing

# Output shows:
# flaskapp.py    80%    50-55, 120-125
#                       ^^^^^ These lines need tests

# Add tests for those specific lines
```

---

## 📞 Getting Help

### Quick Reference
```bash
# Show all commands
./run_tests.sh help

# Show test markers
pytest --markers

# Show available fixtures
pytest --fixtures

# Verbose test output
pytest tests/ -vv

# Show print statements
pytest tests/ -s
```

### Documentation
1. **QUICKSTART.md** ← You are here (quick reference)
2. **AUTOMATION_GUIDE.md** (comprehensive 50-page guide)
3. **tests/README.md** (test writing examples)
4. **pytest.ini** (configuration)

### Example Tests
- `tests/api/test_auth.py` - API test examples
- `tests/unit/test_models.py` - Unit test examples
- `tests/integration/test_scan_workflow.py` - Integration test examples
- `react_src/src/components/__tests__/Login.test.tsx` - Frontend test examples

---

## ✅ Success Checklist

You're successfully using the framework when:

- [ ] Can run `./run_tests.sh quick` in under 3 minutes
- [ ] Understand test output (pass/fail)
- [ ] Know which command to run for your changes
- [ ] Can add a simple new test
- [ ] See CI results on GitHub PRs
- [ ] Check coverage reports occasionally
- [ ] Tests catch bugs before production

**Congratulations! You're automating QA for Tectix! 🎉**
