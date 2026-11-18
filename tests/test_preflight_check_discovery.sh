#!/usr/bin/env bash

# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

# Structural assertions for CI check name discovery in reusable_release_preflight.yml.
#
# The GitHub Checks API reports the job's own name for direct jobs, and
# "<calling job name> / <called job name>" for reusable workflow calls. It never
# includes the calling workflow's top-level name, so discovery must not prepend it.

WORKFLOW=".github/workflows/reusable_release_preflight.yml"
FAILURES=0
TESTS=0

pass() {
	TESTS=$((TESTS + 1))
	echo "PASS: $1"
}

fail() {
	TESTS=$((TESTS + 1))
	FAILURES=$((FAILURES + 1))
	echo "FAIL: $1"
}

# Resolve path relative to repo root (support running from any directory)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKFLOW_PATH="$REPO_ROOT/$WORKFLOW"

if [[ ! -f "$WORKFLOW_PATH" ]]; then
	echo "ERROR: Workflow file not found: $WORKFLOW_PATH"
	exit 1
fi

# ---------------------------------------------------------------------------
# 5.1 ci_checks.yml discovery uses the calling job name only
# ---------------------------------------------------------------------------

if grep -Fq 'REQUIRED_CHECKS+=("Standardized CI / Run linters")' "$WORKFLOW_PATH"; then
	pass "5.1a ci_checks.yml discovery adds 'Standardized CI / Run linters'"
else
	fail "5.1a ci_checks.yml discovery does not add 'Standardized CI / Run linters'"
fi

if grep -Fq 'CI / Standardized CI / Run linters' "$WORKFLOW_PATH"; then
	fail "5.1b workflow still prepends the calling workflow name to the ci_checks.yml check"
else
	pass "5.1b ci_checks.yml check name has no calling workflow prefix"
fi

# ---------------------------------------------------------------------------
# 5.2 ci_local.yml discovery uses the job name only
# ---------------------------------------------------------------------------

if grep -Fq 'REQUIRED_CHECKS+=("${JOB_NAME}")' "$WORKFLOW_PATH"; then
	pass "5.2a ci_local.yml discovery adds the bare job name"
else
	fail "5.2a ci_local.yml discovery does not add the bare job name"
fi

if grep -Fq 'REQUIRED_CHECKS+=("${WORKFLOW_NAME} / ${JOB_NAME}")' "$WORKFLOW_PATH"; then
	fail "5.2b workflow still prepends the calling workflow name to ci_local jobs"
else
	pass "5.2b ci_local.yml check names have no calling workflow prefix"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "========================================="
echo "Results: $((TESTS - FAILURES))/$TESTS passed"
if [[ "$FAILURES" -gt 0 ]]; then
	echo "$FAILURES FAILED"
	exit 1
else
	echo "All assertions passed"
	exit 0
fi
