#!/bin/bash

# Quick Setup Script for Tectix Testing
# Run this first to get everything installed

echo "=========================================="
echo "Tectix Test Framework Setup"
echo "=========================================="
echo ""

# Check Python version
echo "Checking Python version..."
python3 --version
echo ""

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    echo "✓ Virtual environment created"
else
    echo "✓ Virtual environment already exists"
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Install Python dependencies
echo ""
echo "Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-dev.txt
echo "✓ Python dependencies installed"

# Install frontend dependencies
echo ""
echo "Installing frontend dependencies..."
cd react_src
npm install
cd ..
echo "✓ Frontend dependencies installed"

echo ""
echo "=========================================="
echo "✓ Setup Complete!"
echo "=========================================="
echo ""
echo "Quick Commands:"
echo "  ./run_tests.sh quick      # Run smoke tests (2 min)"
echo "  ./run_tests.sh backend    # Run backend tests"
echo "  ./run_tests.sh frontend   # Run frontend tests"
echo "  ./run_tests.sh all        # Run all tests"
echo ""
echo "For more options: ./run_tests.sh help"
echo ""
