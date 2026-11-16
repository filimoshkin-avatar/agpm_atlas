# GitHub Actions — 2026-11-16

START_CHANGE_SUMMARY: M-CI / V-M-CI adds .github/workflows/ci.yml at Ivan's
request. Source of truth: CLAUDE.md and scripts/verify.sh. No application,
publication, storage, or production configuration changes.
START_MODULE_CONTRACT: push, pull_request and manual dispatch run the existing
project verification gate on Ubuntu 24.04, Python 3.12, Node 22 and ephemeral
PostgreSQL 17. uv 0.11.14 installs the committed lockfile with --locked.
LINKS: ../../CLAUDE.md; ../../scripts/verify.sh; ../../tests/conftest.py.
DEPENDS: GitHub-hosted runner, SHA-pinned checkout/setup actions, PyPI, Docker Hub.

The token has contents:read only; checkout does not persist credentials. No
production secrets, SSH, deployment or model calls are configured. Trust auth is
limited to the disposable CI PostgreSQL service; test database names remain
restricted by the existing atlas_test_ fixture guard. Concurrent runs on the same
ref cancel older runs. Job timeout: 15 minutes.

Coverage: full pytest suite (including Node regression tests), then October
reference/signal verification. Browser/axe end-to-end checks and broad legacy
Ruff/format checks are not part of this initial workflow. No GRACE CLI exists in
this project; this document records the contract. Verification of CI-only changes
is the actual GitHub run rather than a mock workflow test.
