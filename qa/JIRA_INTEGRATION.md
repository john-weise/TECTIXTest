# JIRA Integration Guide for Tectix QA Test Cases

**Team Size:** 3 | **Test Cases:** 112 | **Updated:** 2026

---

## Overview: Which Option to Use?

| Option | Cost | Setup Time | Best For |
|--------|------|------------|---------|
| Option A: Built-in CSV Import | Free | 15 min | Quick one-time import; no plugins |
| Option B: Python API Script | Free | 30 min | Automation, bulk re-imports, CI/CD |
| Option C: Xray Plugin | Paid | 1-2 hours | Full test lifecycle management |
| Option D: Zephyr Scale | Paid (free tier) | 1-2 hours | Folder org, execution tracking |

**Recommendation for a 3-person team:**
- **Starting out** → Option A (CSV import, free, 15 minutes)
- **Want automation** → Option B (Python script)
- **Want full test management** → Option D (Zephyr Scale has a free cloud tier)

---

## Option A: Jira Built-in CSV Import (Free, No Plugins)

**File to use:** `qa/test_cases_jira_import.csv`

### Steps

1. **In Jira**, go to:
   `Settings (gear icon) → System → Import Issues from CSV`

   Or for Jira Cloud:
   `Settings → System → External System Import → CSV`

2. **Upload the file:**
   - Choose `qa/test_cases_jira_import.csv`
   - Delimiter: Comma
   - Click **Next**

3. **Map columns** (most will auto-map, manually set the rest):

   | CSV Column | Jira Field |
   |-----------|-----------|
   | `Summary` | Summary ✅ auto |
   | `Issue Type` | Issue Type ✅ auto |
   | `Priority` | Priority ✅ auto |
   | `Labels` | Labels ✅ auto |
   | `Description` | Description ✅ auto |
   | `Environment` | Environment (or custom field) |
   | `Comment` | Comment |

4. Click **Begin Import** → wait for completion

5. **Find your tests in Jira:**
   ```
   JQL: labels = tectix-qa ORDER BY created DESC
   ```

### What Gets Created

- 112 **Task** issues
- Each tagged with labels like `tectix-qa`, `category-authentication`, `priority-p0`
- Full test steps in the Description field
- Preconditions in the Environment field

### Filtering by Category or Priority

```
JQL: labels = tectix-qa AND labels = category-authentication
JQL: labels = tectix-qa AND priority = Highest
JQL: labels = tectix-qa AND labels = automatable
JQL: labels = tectix-qa AND labels = manual-only
```

### Limitations

- No test step structure (steps are in the description as text)
- No execution tracking (pass/fail per run)
- No folder/hierarchy organization
- Manual re-import needed when test cases are updated

---

## Option B: Python API Script (Free, Automated)

**File to use:** `qa/jira_import.py`

### Setup

```bash
# 1. Install the jira library
pip install jira

# 2. Get your Jira API token
# Jira Cloud: https://id.atlassian.com/manage-profile/security/api-tokens
# Jira Server: Profile > Personal Access Tokens

# 3. Set environment variables
export JIRA_URL="https://yourcompany.atlassian.net"
export JIRA_EMAIL="you@company.com"           # Cloud only
export JIRA_TOKEN="your-api-token-here"
export JIRA_PROJECT="TECTIX"                  # Your project key
```

### Usage

```bash
# Preview what would be imported (creates nothing)
python qa/jira_import.py --dry-run

# Import all 112 test cases
python qa/jira_import.py

# Import only P0 critical tests
python qa/jira_import.py --priority P0

# Import only authentication tests
python qa/jira_import.py --category Authentication

# Import and create an Epic per category
python qa/jira_import.py --create-epics

# Import with custom issue type (requires Xray plugin)
python qa/jira_import.py --issue-type Test
```

### Expected Output

```
Connected to Jira as: John Weise (john@company.com)
Project 'TECTIX' found.

Importing 112 test cases...
------------------------------------------------------------
  [  1/112] AUTH-001     → TECTIX-101  Login with valid credentials (no 2FA)
  [  2/112] AUTH-002     → TECTIX-102  Login with wrong password
  [  3/112] AUTH-003     → TECTIX-103  Login with non-existent username
  ...

============================================================
Import Complete
============================================================
  Created:  112
  Failed:   0

Test ID → Jira Key mapping saved to: qa/jira_mapping.csv
```

### Output Files

After import, `qa/jira_mapping.csv` is created:

```
Test ID,Jira Key,Jira URL
AUTH-001,TECTIX-101,https://yourcompany.atlassian.net/browse/TECTIX-101
AUTH-002,TECTIX-102,https://yourcompany.atlassian.net/browse/TECTIX-102
...
```

### CI/CD Integration

Add to `.github/workflows/tests.yml` to auto-sync test cases when the CSV changes:

```yaml
- name: Sync test cases to Jira
  if: github.ref == 'refs/heads/main'
  env:
    JIRA_URL: ${{ secrets.JIRA_URL }}
    JIRA_EMAIL: ${{ secrets.JIRA_EMAIL }}
    JIRA_TOKEN: ${{ secrets.JIRA_TOKEN }}
    JIRA_PROJECT: ${{ secrets.JIRA_PROJECT }}
  run: |
    pip install jira
    python qa/jira_import.py
```

Add secrets in: `GitHub repo → Settings → Secrets → Actions`

---

## Option C: Xray Plugin Import

**File to use:** `qa/test_cases_xray.csv`

### Prerequisites

- Xray app installed in your Jira instance
  - Cloud: [Xray on Atlassian Marketplace](https://marketplace.atlassian.com/apps/1211769)
  - Server: Install via `Jira > Settings > Apps > Find new apps`

### Steps

1. In Jira, go to: **Tests** (top navigation, added by Xray)
2. Click **Import Tests** → **CSV**
3. Upload `qa/test_cases_xray.csv`
4. Configure:
   - Delimiter: Comma
   - Encoding: UTF-8
5. Map columns:

   | CSV Column | Xray Field |
   |-----------|-----------|
   | `Issue Id` | Issue Id ✅ required |
   | `Test Type` | Test Type |
   | `Summary` | Summary |
   | `Precondition` | Precondition |
   | `Action` | Action (Step) |
   | `Data` | Data |
   | `Result` | Expected Result |
   | `Labels` | Labels |
   | `Priority` | Priority |

6. Click **Import**

### CSV Format Explanation

Xray uses **one row per test step**, with the test ID repeated:

```
Issue Id,  Test Type, Summary,         Precondition,      Action,                   Data,    Result
AUTH-001,  Manual,    [AUTH-001] Login, App running...,    POST /api/login,          {...},
AUTH-001,  ,          ,                ,                  Send JSON body,            ,
AUTH-001,  ,          ,                ,                  Check response code,       ,        HTTP 200
```

### What Gets Created

- `Test` issue type per test case
- Structured test steps (Action / Data / Expected Result)
- Linked preconditions
- Visible in Xray Test Repository with category grouping

### Advantages Over Option A

- Full test step management (add/edit/reorder steps)
- Test execution tracking (run tests, record pass/fail)
- Link tests to Jira stories/requirements
- Test plan and sprint integration
- Coverage reports

---

## Option D: Zephyr Scale Import

**File to use:** `qa/test_cases_zephyr.csv`

### Prerequisites

- Zephyr Scale app installed:
  - Cloud: [Zephyr Scale on Marketplace](https://marketplace.atlassian.com/apps/1213259)
  - Free tier available for Cloud (limited features)

### Steps

1. In Jira, navigate to your project
2. Click **Tests** (Zephyr Scale) in the left sidebar
3. Go to **Test Cases** tab
4. Click **Import** → **From CSV**
5. Upload `qa/test_cases_zephyr.csv`
6. Configure:
   - Delimiter: Comma
   - Encoding: UTF-8
7. Map columns:

   | CSV Column | Zephyr Field |
   |-----------|-------------|
   | `Name` | Name ✅ required |
   | `Objective` | Objective |
   | `Precondition` | Precondition |
   | `Folder` | Folder |
   | `Status` | Status |
   | `Priority` | Priority |
   | `Labels` | Labels |
   | `Step` | Step |
   | `Expected Result` | Expected Result |
   | `Test Data` | Test Data |

8. Click **Import**

### What Gets Created

Test cases organized in a **folder hierarchy**:

```
Tectix QA/
├── Authentication/
│   ├── Login/        (14 tests)
│   └── Session/      (4 tests)
├── Two-Factor Auth/
│   ├── Enrollment/   (3 tests)
│   └── Login/        (3 tests)
├── Scan Processing/
│   ├── Submit/       (5 tests)
│   └── Results/      (3 tests)
├── Admin Panel/
│   ├── User Management/ (8 tests)
│   ├── Systems/      (7 tests)
│   └── Logs/         (5 tests)
... etc
```

### Advantages

- Clean folder/hierarchy organization
- Test execution tracking and history
- Dashboard and reporting built-in
- Free cloud tier available

---

## Keeping Test Cases in Sync

When `qa/test_cases.csv` is updated, you need to re-sync with Jira.

### Manual Sync

```bash
# Regenerate JIRA CSV files
python qa/generate_jira_csvs.py

# Then re-import via your chosen method
```

### Automated Sync (Option B only)

The Python API script can be run on every merge to main:

```yaml
# .github/workflows/sync_jira.yml
name: Sync Test Cases to Jira
on:
  push:
    branches: [main]
    paths:
      - 'qa/test_cases.csv'   # Only runs when test cases change

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install jira
      - run: python qa/jira_import.py
        env:
          JIRA_URL:     ${{ secrets.JIRA_URL }}
          JIRA_EMAIL:   ${{ secrets.JIRA_EMAIL }}
          JIRA_TOKEN:   ${{ secrets.JIRA_TOKEN }}
          JIRA_PROJECT: ${{ secrets.JIRA_PROJECT }}
```

---

## Common Jira JQL Queries After Import

```
# All Tectix test cases
labels = tectix-qa

# Critical tests only
labels = tectix-qa AND priority = Highest

# Tests for a specific category
labels = tectix-qa AND labels = category-authentication

# Tests that can be automated
labels = tectix-qa AND labels = automatable

# Tests that require manual execution
labels = tectix-qa AND labels = manual-only

# Tests not yet assigned
labels = tectix-qa AND assignee is EMPTY

# Tests created today
labels = tectix-qa AND created >= startOfDay()
```

---

## Troubleshooting

### "Project not found" error (Option B)
- Verify `JIRA_PROJECT` matches your project key exactly (case-sensitive)
- Find your project key in the Jira URL: `/jira/software/projects/TECTIX/boards`

### "Issue type 'Test' not found" error (Option B)
- Default projects only have Task, Story, Bug, Epic, Subtask
- Use `--issue-type Task` or install Xray/Zephyr for Test type

### "Authentication failed" error (Option B)
- Cloud: use email + API token (not your password)
- Server: use Personal Access Token (not API token)
- Verify token at: `jira.yourcompany.com/rest/api/2/myself`

### CSV import shows blank fields
- Ensure CSV is UTF-8 encoded (not UTF-16 or Windows-1252)
- Check for unescaped commas inside quoted fields

### Xray import: steps not parsed correctly
- Each step must be on its own row with the same `Issue Id`
- Regenerate with: `python qa/generate_jira_csvs.py`

---

## File Reference

| File | Description |
|------|-------------|
| `qa/test_cases.csv` | Master test case spreadsheet (source of truth) |
| `qa/test_cases_jira_import.csv` | For Jira built-in CSV importer |
| `qa/test_cases_xray.csv` | For Xray plugin importer |
| `qa/test_cases_zephyr.csv` | For Zephyr Scale importer |
| `qa/jira_import.py` | Python API import script |
| `qa/generate_jira_csvs.py` | Regenerates the 3 JIRA CSV formats from master |
| `qa/jira_mapping.csv` | Created after API import: Test ID → Jira Key |

> **Always edit `qa/test_cases.csv` first**, then regenerate the JIRA files.
> Never edit the generated files directly — they will be overwritten.
