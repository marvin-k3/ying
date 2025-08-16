#!/bin/bash
# Local testing script for GitHub workflows
# This script provides easy commands to test workflows locally using act

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$REPO_ROOT"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if act is installed
check_act() {
    if ! command -v act &> /dev/null; then
        print_error "act is not installed. Please install it first:"
        echo "  curl -s https://raw.githubusercontent.com/nektos/act/master/install.sh | sudo bash"
        exit 1
    fi
    
    if ! command -v docker &> /dev/null; then
        print_error "Docker is not installed. Please install Docker first."
        exit 1
    fi
    
    if ! docker info &> /dev/null; then
        print_error "Docker is not running. Please start Docker."
        exit 1
    fi
}

# List available workflows
list_workflows() {
    print_status "Available workflows:"
    act -l
}

# Test the main CI workflow
test_ci() {
    print_status "Testing CI workflow (push event)..."
    act push -W .github/workflows/ci-local.yml -j test
}

# Test CI workflow completely 
test_ci_full() {
    print_status "Testing complete CI workflow..."
    act push -W .github/workflows/ci-local.yml
}

# Test untrusted PR workflow
test_pr_untrusted() {
    print_status "Testing untrusted PR workflow..."
    act pull_request_target -W .github/workflows/pr-untrusted.yml
}

# Test security workflow
test_security() {
    print_status "Testing security workflow..."
    act push -W .github/workflows/security.yml -j dependency-scan -j secret-scan
}

# Test just the linting and type checking (fast)
test_quick() {
    print_status "Running quick tests (linting + type checking)..."
    
    # Create a temporary workflow for quick testing
    cat > .github/workflows/quick-test.yml << 'EOF'
name: Quick Test
on: push
jobs:
  quick-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - uses: eifinger/setup-rye@v4
      - run: rye sync
      - run: rye run lint
      - run: rye run typecheck
      - run: rye run test tests/unit/ --tb=short
EOF

    act push -W .github/workflows/quick-test.yml
    
    # Clean up temporary workflow
    rm .github/workflows/quick-test.yml
}

# Test Docker build locally
test_docker() {
    print_status "Testing Docker build locally..."
    
    if [[ -f Dockerfile ]]; then
        docker build -t ying:local-test .
        print_success "Docker build completed successfully"
        
        # Test that the container starts
        print_status "Testing container startup..."
        if timeout 10s docker run --rm ying:local-test --help &> /dev/null; then
            print_success "Container starts successfully"
        else
            print_warning "Container startup test timed out or failed"
        fi
    else
        print_error "Dockerfile not found"
        exit 1
    fi
}

# Run native tests (without Docker/act)
test_native() {
    print_status "Running native tests..."
    
    print_status "Type checking..."
    rye run typecheck
    
    print_status "Unit tests..."
    rye run test
    
    print_success "All native tests passed!"
}

# Setup local environment for testing
setup() {
    print_status "Setting up local testing environment..."
    
    # Create .secrets file if it doesn't exist
    if [[ ! -f .secrets ]]; then
        print_status "Creating .secrets file from example..."
        cp .secrets.example .secrets
        print_warning "Please edit .secrets file with your actual secrets for full testing"
    fi
    
    # Pull Docker images for faster testing
    print_status "Pulling Docker images for act..."
    docker pull catthehacker/ubuntu:act-latest
    
    print_success "Local testing environment setup complete!"
}

# Show usage
usage() {
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  setup          - Set up local testing environment"
    echo "  list           - List available workflows"
    echo "  ci             - Test main CI workflow (selected jobs)"
    echo "  ci-full        - Test complete CI workflow"
    echo "  pr             - Test untrusted PR workflow"
    echo "  security       - Test security workflow (selected jobs)"
    echo "  quick          - Quick test (lint + typecheck + unit tests)"
    echo "  docker         - Test Docker build"
    echo "  native         - Run tests natively (no act/Docker)"
    echo "  all            - Run all tests (native + Docker + workflows)"
    echo ""
    echo "Examples:"
    echo "  $0 setup       # First time setup"
    echo "  $0 quick       # Fast feedback during development"
    echo "  $0 ci          # Test main CI pipeline"
    echo "  $0 all         # Full test suite"
}

# Run all tests
test_all() {
    print_status "Running comprehensive test suite..."
    
    test_native
    test_docker
    test_quick
    test_ci
    
    print_success "All tests completed!"
}

# Main script logic
main() {
    check_act
    
    case "${1:-}" in
        setup)
            setup
            ;;
        list)
            list_workflows
            ;;
        ci)
            test_ci
            ;;
        ci-full)
            test_ci_full
            ;;
        pr)
            test_pr_untrusted
            ;;
        security)
            test_security
            ;;
        quick)
            test_quick
            ;;
        docker)
            test_docker
            ;;
        native)
            test_native
            ;;
        all)
            test_all
            ;;
        "")
            usage
            ;;
        *)
            print_error "Unknown command: $1"
            usage
            exit 1
            ;;
    esac
}

main "$@"
