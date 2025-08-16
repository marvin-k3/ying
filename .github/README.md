# GitHub Workflows Security Guide

This repository implements a comprehensive, security-focused CI/CD pipeline designed to handle contributions from untrusted sources while maintaining high security standards.

## 🔒 Security Model

### Threat Model
We assume that:
- **Pull requests from forks may contain malicious code**
- **Contributors may attempt to exfiltrate secrets**
- **Attackers may try to compromise the build environment**
- **Dependencies may contain vulnerabilities**

### Security Controls
1. **Minimal Permissions**: Each workflow uses the least required permissions
2. **Secrets Isolation**: No secrets in untrusted PR workflows
3. **Sandboxed Execution**: Untrusted code runs in restricted environments
4. **Manual Approval**: Full testing requires maintainer approval
5. **Comprehensive Scanning**: Multi-layer security scanning

## 🚀 Workflow Overview

### 1. CI Pipeline (`ci.yml`)
**Triggers**: Push to `main`/`develop`, pull requests, merge queue

**Security Features**:
- ✅ Separate security scanning job (no checkout of untrusted code)
- ✅ Trivy vulnerability scanning with SARIF upload
- ✅ Matrix testing with Python 3.12
- ✅ System dependencies hardening
- ✅ Dependency caching with security validation
- ✅ Coverage reporting with conditional tokens
- ✅ Integration tests with controlled API access
- ✅ Docker security scanning
- ✅ Fail-fast on security issues

**Jobs**:
- `security-checks`: Vulnerability scanning (SARIF → GitHub Security)
- `test`: Linting, type checking, unit tests
- `integration-test`: Network-dependent tests (optional API keys)
- `docker-build`: Container security validation
- `ci-success`: Consolidated status check

### 2. Untrusted PR Pipeline (`pr-untrusted.yml`)
**Triggers**: `pull_request_target` from forks

**Security Features**:
- 🔒 **ZERO secrets access** - No `secrets.*` available
- 🔒 **Read-only permissions** - Cannot write to repository
- 🔒 **No network access** - Integration tests disabled
- 🔒 **Static analysis only** - Trivy, linting, type checking
- 🔒 **Unit tests only** - No live API calls
- 🔒 **Automatic PR commenting** - Instructions for maintainers

**Safety Measures**:
```yaml
permissions:
  contents: read          # Cannot modify code
  pull-requests: read     # Cannot write comments (except instructions)
```

### 3. Trusted PR Pipeline (`pr-trusted.yml`)
**Triggers**: Manual workflow dispatch by maintainers

**Security Features**:
- 👥 **Maintainer validation** - Checks GitHub org/collaborator status
- 🔑 **Full secrets access** - Integration tests with API keys
- 🔍 **Complete testing** - All security scans + integration tests
- 📊 **Detailed reporting** - Comments results on PR
- 🐳 **Docker validation** - Full container security testing

**Usage**:
1. Maintainer reviews PR code
2. If safe, manually triggers workflow with PR number and SHA
3. Full test suite runs with secrets
4. Results posted to PR

### 4. Security Pipeline (`security.yml`)
**Triggers**: Daily schedule, pushes to main, pull requests, manual dispatch

**Security Features**:
- 🛡️ **Dependency scanning** - Trivy + Safety for Python packages
- 🔍 **CodeQL analysis** - GitHub's semantic code analysis
- 🕵️ **Secret scanning** - GitLeaks for committed secrets
- ⚖️ **License compliance** - Automated license checking
- 🐳 **Container scanning** - Docker image vulnerability analysis
- 📊 **SARIF integration** - Results in GitHub Security tab

## 🛠️ Setup Requirements

### Repository Secrets (Optional)
```bash
# Optional: For enhanced integration testing
ACOUSTID_API_KEY=your_acoustid_key

# Optional: For private repositories
CODECOV_TOKEN=your_codecov_token

# Optional: For GitLeaks Pro features
GITLEAKS_LICENSE=your_gitleaks_license
```

### Branch Protection Rules
Recommended settings for `main` branch:
- ✅ Require status checks: `CI Success`
- ✅ Require up-to-date branches
- ✅ Restrict pushes to maintainers
- ✅ Require signed commits
- ✅ Delete head branches after merge

## 🔧 Development Workflow

### For Repository Maintainers
1. **Regular PRs** (same repo): Full CI runs automatically
2. **Fork PRs**: Review → Manual approval → `pr-trusted.yml`
3. **Security monitoring**: Check GitHub Security tab daily

### For External Contributors
1. Fork repository
2. Create feature branch
3. Submit PR
4. **Automatic checks run** (limited scope)
5. Wait for maintainer review and full testing

## 📊 Security Monitoring

### GitHub Security Tab
All security findings are centralized:
- Dependency vulnerabilities (Trivy)
- Code security issues (CodeQL)
- Container vulnerabilities
- License compliance issues

### Workflow Artifacts
- `safety-report.json`: Python dependency vulnerabilities
- `license-report.json`: License compliance report
- Coverage reports: Uploaded to Codecov

## 🚨 Incident Response

### Suspected Malicious PR
1. **DO NOT** run `pr-trusted.yml`
2. Review code changes carefully
3. Check for:
   - Suspicious network requests
   - File system modifications
   - Credential harvesting attempts
   - Cryptocurrency mining
4. Close PR if malicious

### Security Alert
1. Check GitHub Security tab
2. Assess severity and impact
3. Update dependencies if needed
4. Re-run security scans

### Failed Security Checks
1. Review security scan results
2. Fix vulnerabilities in order of severity
3. Update dependencies
4. Re-run workflows

## 🔄 Maintenance

### Regular Tasks
- **Weekly**: Review security scan results
- **Monthly**: Update workflow actions to latest versions
- **Quarterly**: Review and update security policies

### Updating Dependencies
```bash
# Update Python dependencies
rye sync
rye run test

# Update GitHub Actions
# Review .github/workflows/*.yml for version updates
```

## 📚 References

- [GitHub Actions Security Best Practices](https://docs.github.com/en/actions/security-guides/security-hardening-for-github-actions)
- [Securing CI/CD Pipelines](https://owasp.org/www-project-devsecops-guideline/)
- [NIST Secure Software Development Framework](https://csrc.nist.gov/Projects/ssdf)

## 🤝 Contributing to Security

Found a security issue? Please:
1. **DO NOT** open a public issue
2. Email security concerns privately
3. Follow responsible disclosure practices
4. Allow time for patches before public disclosure

---

*This security documentation is maintained alongside the codebase and should be updated when workflows change.*
