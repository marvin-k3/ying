#!/bin/bash
# Script to help maintainers test untrusted PRs safely
# Usage: ./test-pr.sh <PR_NUMBER>

set -e

if [ $# -ne 1 ]; then
    echo "Usage: $0 <PR_NUMBER>"
    echo "Example: $0 123"
    exit 1
fi

PR_NUMBER=$1

# Get PR information
echo "🔍 Fetching PR information..."
PR_INFO=$(gh pr view $PR_NUMBER --json number,headRefOid,headRepository,author,title)

PR_SHA=$(echo "$PR_INFO" | jq -r '.headRefOid')
PR_REPO=$(echo "$PR_INFO" | jq -r '.headRepository.nameWithOwner')
PR_AUTHOR=$(echo "$PR_INFO" | jq -r '.author.login')
PR_TITLE=$(echo "$PR_INFO" | jq -r '.title')
CURRENT_REPO=$(gh repo view --json nameWithOwner | jq -r '.nameWithOwner')

echo "📋 PR Details:"
echo "  Number: #$PR_NUMBER"
echo "  Title: $PR_TITLE"
echo "  Author: $PR_AUTHOR"
echo "  SHA: $PR_SHA"
echo "  From: $PR_REPO"
echo "  To: $CURRENT_REPO"

# Check if this is a fork
if [ "$PR_REPO" != "$CURRENT_REPO" ]; then
    echo "⚠️  WARNING: This is a PR from a FORK ($PR_REPO)"
    echo "   Please review the code changes carefully before proceeding."
    echo ""
    
    # Show the files changed
    echo "📝 Files changed in this PR:"
    gh pr diff $PR_NUMBER --name-only | sed 's/^/  /'
    echo ""
    
    read -p "Have you reviewed the code changes? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "❌ Aborted. Please review the PR first."
        exit 1
    fi
    
    read -p "Do you trust this PR to run with full permissions? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "❌ Aborted. Use manual code review instead."
        exit 1
    fi
else
    echo "✅ This is a PR from the same repository - safe to test."
fi

echo ""
echo "🚀 Triggering trusted PR workflow..."

# Trigger the workflow
gh workflow run pr-trusted.yml \
    -f pr_number="$PR_NUMBER" \
    -f pr_sha="$PR_SHA"

echo "✅ Workflow triggered successfully!"
echo ""
echo "📊 You can monitor the workflow at:"
echo "   https://github.com/$CURRENT_REPO/actions/workflows/pr-trusted.yml"
echo ""
echo "💬 Results will be posted as a comment on PR #$PR_NUMBER when complete."
