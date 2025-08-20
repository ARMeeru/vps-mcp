#!/bin/bash
# Test runner script for MCP VPS Manager

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${2}${1}${NC}"
}

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    print_status "Virtual environment not found. Creating one..." $YELLOW
    python -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies
print_status "Installing dependencies..." $YELLOW
pip install -r requirements.txt
pip install pytest pytest-asyncio pytest-mock pytest-cov

# Run different test suites based on argument
case "${1:-all}" in
    "unit")
        print_status "Running unit tests..." $YELLOW
        pytest tests/unit/ -v
        ;;
    "integration") 
        print_status "Running integration tests..." $YELLOW
        pytest tests/integration/ -v
        ;;
    "coverage")
        print_status "Running tests with coverage..." $YELLOW
        pytest --cov=src/vps_manager --cov-report=term-missing --cov-report=html:htmlcov
        print_status "Coverage report generated in htmlcov/" $GREEN
        ;;
    "fast")
        print_status "Running fast tests only..." $YELLOW
        pytest -m "not slow" -v
        ;;
    "lint")
        print_status "Running linting..." $YELLOW
        pip install flake8 black isort mypy
        
        print_status "Running flake8..." $YELLOW
        flake8 src/ tests/ || true
        
        print_status "Running black (check only)..." $YELLOW
        black --check src/ tests/ || true
        
        print_status "Running isort (check only)..." $YELLOW
        isort --check-only src/ tests/ || true
        
        print_status "Running mypy..." $YELLOW
        mypy src/ || true
        ;;
    "format")
        print_status "Formatting code..." $YELLOW
        pip install black isort
        black src/ tests/
        isort src/ tests/
        print_status "Code formatted successfully!" $GREEN
        ;;
    "all"|*)
        print_status "Running all tests..." $YELLOW
        pytest tests/ -v
        ;;
esac

# Check test results
if [ $? -eq 0 ]; then
    print_status "✅ All tests passed!" $GREEN
else
    print_status "❌ Some tests failed!" $RED
    exit 1
fi