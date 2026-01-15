#!/bin/bash

# Tectix Test Runner Script
# Quick commands to run different test suites

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_header() {
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

# Check if virtual environment exists
check_venv() {
    if [ ! -d "venv" ]; then
        print_warning "Virtual environment not found. Creating one..."
        python3 -m venv venv
        source venv/bin/activate
        pip install -r requirements.txt
        pip install -r requirements-dev.txt
        print_success "Virtual environment created"
    else
        source venv/bin/activate
    fi
}

# Display usage
usage() {
    echo "Tectix Test Runner"
    echo ""
    echo "Usage: ./run_tests.sh [OPTION]"
    echo ""
    echo "Options:"
    echo "  all           Run all tests (backend + frontend)"
    echo "  backend       Run all backend tests"
    echo "  frontend      Run all frontend tests"
    echo "  unit          Run unit tests only"
    echo "  api           Run API tests only"
    echo "  integration   Run integration tests only"
    echo "  auth          Run authentication tests only"
    echo "  coverage      Run tests with coverage report"
    echo "  quick         Run quick smoke tests"
    echo "  security      Run security scans"
    echo "  install       Install test dependencies"
    echo "  clean         Clean test artifacts"
    echo "  help          Show this help message"
    echo ""
    echo "Examples:"
    echo "  ./run_tests.sh quick         # Fast smoke tests (~2 min)"
    echo "  ./run_tests.sh api           # API tests only (~4 min)"
    echo "  ./run_tests.sh coverage      # Full coverage report (~15 min)"
}

# Install dependencies
install_deps() {
    print_header "Installing Dependencies"

    check_venv

    print_warning "Installing Python dependencies..."
    pip install -r requirements.txt
    pip install -r requirements-dev.txt
    print_success "Python dependencies installed"

    print_warning "Installing Node dependencies..."
    cd react_src
    npm install
    cd ..
    print_success "Node dependencies installed"

    print_success "All dependencies installed successfully!"
}

# Run all tests
run_all() {
    print_header "Running All Tests"
    run_backend
    run_frontend
    print_success "All tests completed!"
}

# Run backend tests
run_backend() {
    print_header "Running Backend Tests"
    check_venv
    pytest tests/unit tests/api tests/integration -v
    print_success "Backend tests completed"
}

# Run frontend tests
run_frontend() {
    print_header "Running Frontend Tests"
    cd react_src
    npm test -- --watchAll=false
    cd ..
    print_success "Frontend tests completed"
}

# Run unit tests only
run_unit() {
    print_header "Running Unit Tests"
    check_venv
    pytest tests/unit -v -m unit
}

# Run API tests only
run_api() {
    print_header "Running API Tests"
    check_venv
    pytest tests/api -v -m api
}

# Run integration tests
run_integration() {
    print_header "Running Integration Tests"
    check_venv
    pytest tests/integration -v -m integration
}

# Run auth tests only
run_auth() {
    print_header "Running Authentication Tests"
    check_venv
    pytest tests/api/test_auth.py -v -m auth
}

# Run with coverage
run_coverage() {
    print_header "Running Tests with Coverage"
    check_venv

    print_warning "Running backend tests with coverage..."
    pytest tests/ -v --cov=. --cov-report=html --cov-report=term-missing

    print_warning "Running frontend tests with coverage..."
    cd react_src
    npm test -- --coverage --watchAll=false
    cd ..

    print_success "Coverage reports generated!"
    echo ""
    echo "Backend coverage: file://$(pwd)/htmlcov/index.html"
    echo "Frontend coverage: file://$(pwd)/react_src/coverage/lcov-report/index.html"
}

# Run quick smoke tests
run_quick() {
    print_header "Running Quick Smoke Tests"
    check_venv

    # Run only fast unit tests
    pytest tests/unit -v -m "unit and not slow" --tb=short

    # Run critical API tests
    pytest tests/api/test_auth.py::TestAuthentication::test_login_success -v
    pytest tests/api/test_auth.py::TestAuthentication::test_session_check_authenticated -v

    print_success "Smoke tests completed"
}

# Run security scans
run_security() {
    print_header "Running Security Scans"
    check_venv

    print_warning "Running Bandit security scan..."
    bandit -r . -ll -x ./venv,./react_src,./react_build,./tests || true

    print_warning "Checking for known vulnerabilities..."
    safety check || true

    print_success "Security scans completed"
}

# Clean test artifacts
clean() {
    print_header "Cleaning Test Artifacts"

    rm -rf .pytest_cache
    rm -rf htmlcov
    rm -rf .coverage
    rm -rf *.egg-info
    rm -rf react_src/coverage
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

    print_success "Test artifacts cleaned"
}

# Main script
case "$1" in
    all)
        run_all
        ;;
    backend)
        run_backend
        ;;
    frontend)
        run_frontend
        ;;
    unit)
        run_unit
        ;;
    api)
        run_api
        ;;
    integration)
        run_integration
        ;;
    auth)
        run_auth
        ;;
    coverage)
        run_coverage
        ;;
    quick)
        run_quick
        ;;
    security)
        run_security
        ;;
    install)
        install_deps
        ;;
    clean)
        clean
        ;;
    help|--help|-h)
        usage
        ;;
    "")
        print_error "No option specified"
        echo ""
        usage
        exit 1
        ;;
    *)
        print_error "Unknown option: $1"
        echo ""
        usage
        exit 1
        ;;
esac
