# Makefile for Ying RTSP Music Tagger
# Provides convenient commands for development and testing

.PHONY: help test test-unit test-integration test-local test-docker test-security lint typecheck fmt clean setup install dev

# Default target
help: ## Show this help message
	@echo "Ying RTSP Music Tagger - Development Commands"
	@echo ""
	@echo "Setup Commands:"
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## .*setup/ {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""
	@echo "Development Commands:"
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## .*dev/ {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""
	@echo "Testing Commands:"
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## .*test/ {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""
	@echo "Other Commands:"
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / && !/setup|dev|test/ {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# Setup commands
setup: ## Initial setup of development environment
	@echo "🔧 Setting up development environment..."
	rye sync
	@if [ ! -f .secrets ]; then cp .secrets.example .secrets; echo "📝 Created .secrets file - please edit with your values"; fi
	@echo "✅ Setup complete!"

install: ## Install dependencies
	rye sync

# Development commands  
dev: ## Start development server
	rye run dev

fmt: ## Format code
	rye run fmt

lint: ## Run linting
	rye run lint

typecheck: ## Run type checking
	rye run typecheck

# Testing commands
test: ## Run all tests (unit + integration)
	rye run test

test-unit: ## Run unit tests only
	rye run test tests/unit/

test-integration: ## Run integration tests
	rye run test-integration

test-coverage: ## Run tests with detailed coverage report
	rye run test --cov-report=html
	@echo "📊 Coverage report generated in htmlcov/"

# Local workflow testing
test-local: ## Test workflows locally using act
	./.github/scripts/test-local.sh quick

test-local-full: ## Run full local workflow tests
	./.github/scripts/test-local.sh all

test-local-setup: ## Setup local testing environment
	./.github/scripts/test-local.sh setup

test-workflow: ## Test specific workflow (usage: make test-workflow WORKFLOW=ci.yml JOB=test)
	./.github/scripts/test-workflow.sh $(WORKFLOW) $(JOB)

# Docker testing
test-docker: ## Test Docker build and functionality
	docker build -t ying:test .
	@echo "✅ Docker build successful"

test-docker-compose: ## Run tests using Docker Compose
	docker-compose -f docker-compose.test.yml --profile testing run --rm test-runner

test-security-docker: ## Run security scans using Docker
	docker-compose -f docker-compose.test.yml --profile security run --rm security-scanner

test-licenses-docker: ## Check licenses using Docker
	docker-compose -f docker-compose.test.yml --profile compliance run --rm license-checker

# CI simulation
test-ci-simulation: ## Simulate CI pipeline locally
	@echo "🔄 Simulating CI pipeline..."
	make lint
	make typecheck  
	make test-unit
	make test-docker
	@echo "✅ CI simulation complete!"

# Security testing
test-security: ## Run security scans locally
	@echo "🔒 Running security scans..."
	@if command -v trivy >/dev/null 2>&1; then \
		trivy fs --severity HIGH,CRITICAL .; \
	else \
		echo "⚠️ Trivy not installed - using Docker version"; \
		make test-security-docker; \
	fi

# Database operations
migrate: ## Run database migrations
	rye run migrate

db-reset: ## Reset database (WARNING: destroys data)
	@read -p "Are you sure you want to reset the database? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		rm -f data/plays.db*; \
		echo "🗑️ Database reset"; \
	fi

# Cleanup commands
clean: ## Clean up generated files
	@echo "🧹 Cleaning up..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name ".coverage" -delete 2>/dev/null || true
	docker system prune -f --volumes 2>/dev/null || true
	@echo "✅ Cleanup complete!"

clean-docker: ## Clean up Docker resources
	@echo "🐳 Cleaning Docker resources..."
	docker-compose -f docker-compose.test.yml down --volumes --remove-orphans 2>/dev/null || true
	docker rmi ying:test 2>/dev/null || true
	docker system prune -f --volumes 2>/dev/null || true
	@echo "✅ Docker cleanup complete!"

# Utility commands  
logs: ## Show application logs (if running in Docker)
	docker-compose -f docker-compose.test.yml logs -f ying-test

shell: ## Open shell in test container
	docker-compose -f docker-compose.test.yml run --rm test-runner bash

check-deps: ## Check for outdated dependencies
	rye show --table

# Pre-commit checks
pre-commit: ## Run all pre-commit checks
	@echo "🔍 Running pre-commit checks..."
	make fmt
	make lint
	make typecheck
	make test-unit
	@echo "✅ Pre-commit checks passed!"

# Release preparation
prepare-release: ## Prepare for release (run all checks)
	@echo "🚀 Preparing for release..."
	make clean
	make setup
	make pre-commit
	make test-integration
	make test-docker
	make test-security
	@echo "✅ Release preparation complete!"

# Environment info
info: ## Show environment information
	@echo "Environment Information:"
	@echo "📍 Working directory: $(PWD)"
	@echo "🐍 Python version: $$(python --version 2>&1)"
	@echo "📦 Rye version: $$(rye --version 2>&1)"
	@echo "🐳 Docker version: $$(docker --version 2>&1 || echo 'Docker not available')"
	@echo "⚡ Act version: $$(act --version 2>&1 || echo 'Act not available')"
	@echo "📊 Test coverage: $$(rye run test --quiet --tb=no | grep -o '[0-9]*%' | tail -1 || echo 'Unknown')"
