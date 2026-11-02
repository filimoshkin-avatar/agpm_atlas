# Atlas operational storage — accepted 2026-11-02

## GRACE contract and sources of truth

M-STORAGE (`atlas/storage.py`, `deploy/storage_server.py`): cache keys retain SHA256(model + prompt version + prompt). Forced SSH command accepts only bounded JSON RPC (4MiB) over stdin. No arbitrary shell, paths or deletion operation. File writes fsync + atomic rename; cache errors stop execution, never fall back to srv2 disk. Existing model/profile/prompts unchanged. Same-server filesystem operations are serialized by flock; cross-RPC run lease expires after18h, runner capped12h. Cleanup skips active leases and pinned subtrees; operator may resolve a stale lease only after proving runner dead.

M-RUNNER (`atlas/weekly.py`, `scripts/weekly.sh`): collection/model/browser execute on srv2, Python/database business logic unchanged. Keep week → preview → axe-core → publish → summary/notification order. Source text cache shared with Radar is unchanged/read-only. Notifications use existing OpenClaw, not a cloned profile. On persistent storage failure stop child process group and fail; no local operational spool. Logs capped32MiB per stream, stdout capture4MiB. Runtime tmpfs192MiB, cgroup768MiB RAM/256MiB swap, max12h, one run. Runtime service directory contains only locks; subprocess output and secrets are not logged locally. Generic OpenClaw/system journals remain their owners' responsibility.

M-BACKUP: pg_dump runs on Local Ru as atlas, reads existing protected DSN into PG environment, never argv. New dumps must pass pg_restore --list and SHA256 before retirement eligibility. A failed backup aborts daily maintenance. Archive validation is NOT the same as restore validation: deployment also performed a real isolated restoration (27 tables, row counts and content hashes equal). Keep latest two checksum-valid dumps regardless of age; require fresh valid dump≤36h before deleting old backups. No automatic deletion of unverified dumps.

M-RETENTION: dry-run default. Explicit --apply only within dedicated roots, no directory symlink following; `.pin` protects a subtree. Atomic storage files have mode0600, directories0700. Retained data is not web-served. Production snapshots/history and shared Radar storage are excluded.

## Paths

- srv2 source: `/data/atlas`; GitHub `filimoshkin-avatar/agpm_atlas`.
- srv2 private storage client config `/etc/atlas-storage/client.json`, key `/root/.ssh/atlas_storage`; restricted forced command on atlas@194.87.143.141. Existing tunnel/publish keys unchanged.
- Local Ru data `/var/lib/atlas/storage/{model-cache,runs,imported,artifacts,tmp}`; backups `/var/backups/atlas`.
- Helpers deployed root-owned under `/opt/atlas-storage`; production website/runtime pointers and Caddy are NOT changed by this migration.
- Imported legacy logs are `runs/imported-20261102`; diagnostic/site copies `imported`. Git reference/prototype/test fixtures remain source assets.
- Historical `.dump` files preserve original mtime and receive checksum metadata. Imported non-backup diagnostics expire after30days; required source reference remains in Git.

## Schedule

- srv2 root cron Monday06:00UTC (09:00MSK) starts `atlas-weekly.service`; does not invoke another concurrent pipeline.
- Local Ru `atlas-storage-maintenance.timer` daily04:30UTC runs backup then retention.
- srv2 daily06:15UTC checks remote maintenance success/freshness/threshold and alerts Ivan through existing OpenClaw. Missing/failed/stale maintenance >36h alerts. Daily local Atlas development-cache cleanup after this check is independent.
- Weekly compatibility command `scripts/weekly.sh [date]` uses new runner, but preferred systemd service supplies resource limits and private browser temp filesystem.

## Retention

- Daily dumps: every day14d, latest per ISO week56d, latest per calendar month within183d. Selection reuses dump files instead of creating three copies. Prepublication/imported dumps30d. Latest two valid always retained. Partially written backup files7d.
- Model cache90d after latest successful read/write (mtime explicitly touched).
- Run logs raw30d then gzip with decompression/hash verification; expire180d. `status.json` and short summary remain365d. `.pin` prevents archive/deletion.
- Diagnostics: artifacts/success14d; artifacts/failed or unclassified/imported30d. Imported historical artifacts lack reliable outcome labels and conservatively retain30d.
- Remote tmp7d; srv2 browser tmpfs disappears with service. Atlas `.pytest_cache`, `.ruff_cache`, `__pycache__` files >7d only when no other process has cwd inside Atlas. No .venv/Git/source cleanup.
- Total remote operational state+backups >10GiB or disk free<2GiB triggers maintenance failure/alert. New run/backup refused below1GiB free. Thresholds alert rather than delete protected data.
- Published site cleanup remains existing90d policy and1d replaced-build policy. It runs on publish, not this maintenance job. Database version snapshots never purged.

## Verification / rollback

V-M-STORAGE/V-M-RETENTION in tests/test_storage.py: traversal, symlinks, active leases, pins, age boundary, cache hit, failure before inference, cache-write failure, remote log failure kills child, timeout, archive roundtrip and latest-two backups. Existing project gate checks business invariants and reference. Ruff lint/import + formatting apply to new modules; pnpm gates inapplicable (Python project). No UI or application migration.

Rollback evidence on Local Ru: `/root/atlas-storage-cutover-20261102/`. Original cron and weekly.sh, source-data parity manifest, original authorized_keys/Caddy retained. Full original var copy remains `/var/lib/atlas/storage/imported/rollback-20261102/var` for30days (migration guard). Do not overwrite live DB or site on rollback. Disable new weekly invocation, restore old cron/runner and var from guard if required; temporarily bypass new remote cache config only as deliberate rollback. Keep collected new remote logs/cache. The guard has a fresh retention timestamp and expires under the imported30d policy; its original mtimes are recorded in the protected evidence directory.

## Scope boundaries

No migration of model execution, no full weekly run repeated on production during acceptance. Read-only runner `--check` proves DB tunnel, remote backup/logs and live axe-core without week/publish. Code and runtime copies on Local Ru are deployment artifacts; immutable site snapshots unchanged. No S3/offhost backup destination was authorized in this change; Local Ru-only backups cannot protect against total host loss.
