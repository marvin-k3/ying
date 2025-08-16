# Local Testing Guide

This guide shows you how to test GitHub workflows and CI processes locally before pushing to GitHub.

## 🚀 Quick Start

```bash
# Setup (one time)
make setup
make test-local-setup

# Quick development testing
make test-local

# Full local CI simulation
make test-ci-simulation
```

## 🛠️ Available Testing Methods

### 1. Native Testing (Fastest)
Test your code directly on your machine without containers:

```bash
# Individual commands
make lint          # Code linting
make typecheck     # Type checking  
make test-unit     # Unit tests only
make test         # All tests

# Combined pre-commit checks
make pre-commit   # Format + lint + typecheck + unit tests
```

### 2. Act Testing (GitHub Actions Simulation)
Test your workflows exactly as they run on GitHub:

```bash
# Setup act (one time)
make test-local-setup

# Quick workflow testing
make test-local              # Fast: lint + typecheck + unit tests

# Test specific workflows
./.github/scripts/test-workflow.sh ci.yml
./.github/scripts/test-workflow.sh security.yml dependency-scan

# Full workflow testing
make test-local-full         # All workflows
```

### 3. Docker Testing
Test in containerized environment:

```bash
# Test Docker build
make test-docker

# Test using Docker Compose
make test-docker-compose      # Full test suite
make test-security-docker    # Security scans
make test-licenses-docker    # License compliance
```

## 📁 Local Testing Setup

### Prerequisites

1. **Docker** - Required for act and container testing
2. **act** - GitHub Actions runner (installed via `make test-local-setup`)
3. **make** - Build automation (usually pre-installed on Linux/macOS)

### First-Time Setup

```bash
# Install dependencies and setup environment
make setup

# Setup local testing tools
make test-local-setup

# Verify everything works
make test-local
```

### Configuration Files

- **`.actrc`** - act configuration (Docker images, verbose output)
- **`.secrets.example`** - Template for local secrets
- **`.secrets`** - Your local secrets (create from example, never commit)
- **`.github/events/`** - Event payloads for act testing

## 🔧 Act (GitHub Actions Local Runner)

Act allows you to run GitHub Actions workflows locally using Docker.

### Basic Commands

```bash
# List available workflows
act -l

# Run push workflows (like CI)
act

# Run pull request workflows
act pull_request

# Run specific workflow
act -W .github/workflows/ci.yml

# Run specific job
act -j test
```

### Testing Workflows

```bash
# Test main CI pipeline
./.github/scripts/test-local.sh ci

# Test security workflow
./.github/scripts/test-local.sh security

# Test untrusted PR workflow
./.github/scripts/test-local.sh pr

# Test specific workflow + job
./.github/scripts/test-workflow.sh ci.yml test
```

### Using Secrets Locally

1. Copy the example secrets file:
   ```bash
   cp .secrets.example .secrets
   ```

2. Edit `.secrets` with your actual values:
   ```bash
   ACOUSTID_API_KEY=your_real_key
   CODECOV_TOKEN=your_token
   GITHUB_TOKEN=your_github_token
   ```

3. act will automatically use these secrets when running workflows.

## 🐳 Docker Testing

### Building and Testing

```bash
# Build Docker image
make test-docker

# Run full test suite in container
make test-docker-compose

# Interactive shell in test container
make shell
```

### Docker Compose Profiles

- **default** - Just the app service
- **testing** - App + test runner
- **security** - Security scanning tools
- **compliance** - License checking

```bash
# Run specific profiles
docker-compose -f docker-compose.test.yml --profile testing up
docker-compose -f docker-compose.test.yml --profile security run security-scanner
```

## 📊 Testing Scenarios

### Development Workflow
```bash
# While coding (fast feedback)
make fmt lint typecheck test-unit

# Before committing
make pre-commit

# Before pushing (comprehensive)
make test-local-full
```

### PR Testing Simulation
```bash
# Simulate untrusted PR (no secrets)
act pull_request_target -W .github/workflows/pr-untrusted.yml

# Simulate trusted PR (with secrets)
act workflow_dispatch -W .github/workflows/pr-trusted.yml \
  --input pr_number=123 \
  --input pr_sha=abc123
```

### Security Testing
```bash
# Local security scans
make test-security

# Container security
make test-security-docker

# License compliance
make test-licenses-docker
```

### Integration Testing
```bash
# Unit tests only (no network)
make test-unit

# Integration tests (network required)
make test-integration

# Both unit and integration
make test
```

## 🔍 Debugging Failed Tests

### Act Debugging
```bash
# Verbose output
act -v

# Very verbose (includes Docker commands)
act -vv

# Dry run (see what would run)
act --dry-run

# Use different Docker image
act -P ubuntu-latest=nektos/act-environments-ubuntu:18.04
```

### Docker Debugging
```bash
# See container logs
make logs

# Shell into test container
make shell

# Check container health
docker-compose -f docker-compose.test.yml ps
```

### Native Debugging
```bash
# Run tests with verbose output
rye run test -v

# Run tests with debugging
rye run test --pdb

# Run specific test
rye run test tests/unit/test_config.py::test_basic_config -v
```

## ⚡ Performance Tips

### Speed Up Act
- Use `--bind` flag for faster dependency installation
- Cache Docker images locally
- Use specific jobs instead of full workflows during development

### Speed Up Tests
```bash
# Skip slow tests during development
rye run test -m "not slow"

# Run only changed files
rye run test --lf  # last failed
rye run test --ff  # failed first
```

### Docker Performance
- Use multi-stage builds (already configured)
- Share volumes for dependency caching
- Use `.dockerignore` to reduce build context

## 🚨 Troubleshooting

### Common Issues

**Act fails with permission errors:**
```bash
# Fix Docker permissions
sudo usermod -aG docker $USER
# Then logout and login again
```

**Docker build fails:**
```bash
# Clean Docker cache
make clean-docker

# Rebuild without cache
docker build --no-cache -t ying:test .
```

**Tests fail in container but work locally:**
```bash
# Check environment differences
make info

# Compare Python/dependency versions
make shell
# Then inside container: python --version, pip list
```

**Act can't find workflows:**
```bash
# Check workflow syntax
act --dry-run -v

# Validate workflow files
act -l
```

### Getting Help

```bash
# Show available make commands
make help

# Show act help
act --help

# Show environment info
make info
```

## 📚 Best Practices

### 1. Test Early and Often
- Run `make pre-commit` before every commit
- Use `make test-local` during development
- Run full tests before important pushes

### 2. Security
- Never commit `.secrets` file
- Use minimal secrets for local testing
- Regularly update Docker images

### 3. Performance
- Use native testing for fast feedback
- Use act for workflow validation
- Use Docker for environment verification

### 4. Debugging
- Start with native tests, then Docker, then act
- Use verbose flags when debugging
- Check logs and use interactive shells

## 🔗 References

- [act Documentation](https://github.com/nektos/act)
- [Docker Compose Documentation](https://docs.docker.com/compose/)
- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Rye Documentation](https://rye-up.com/)

---

*This testing setup ensures your code works locally before pushing to GitHub, saving time and preventing CI failures.*
