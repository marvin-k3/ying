#!/bin/bash
# Test specific workflow jobs locally
# Usage: ./test-workflow.sh <workflow-file> [job-name]

set -e

WORKFLOW_FILE="$1"
JOB_NAME="${2:-}"

if [[ -z "$WORKFLOW_FILE" ]]; then
    echo "Usage: $0 <workflow-file> [job-name]"
    echo ""
    echo "Examples:"
    echo "  $0 ci.yml                    # Test all jobs in CI workflow"
    echo "  $0 ci.yml test               # Test only the 'test' job"
    echo "  $0 security.yml dependency-scan   # Test dependency scan job"
    echo ""
    echo "Available workflows:"
    ls -1 .github/workflows/*.yml | xargs -I {} basename {} .yml
    exit 1
fi

WORKFLOW_PATH=".github/workflows/$WORKFLOW_FILE"

if [[ ! -f "$WORKFLOW_PATH" ]]; then
    echo "Error: Workflow file $WORKFLOW_PATH not found"
    exit 1
fi

echo "🧪 Testing workflow: $WORKFLOW_FILE"

if [[ -n "$JOB_NAME" ]]; then
    echo "🎯 Running job: $JOB_NAME"
    act -W "$WORKFLOW_PATH" -j "$JOB_NAME"
else
    echo "🎯 Running all jobs"
    act -W "$WORKFLOW_PATH"
fi
