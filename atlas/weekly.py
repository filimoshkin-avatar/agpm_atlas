# START_MODULE_CONTRACT M-RUNNER: unchanged week/preview/a11y/publish ordering.
# LINKS: docs/operations/storage.md; tests/test_weekly_errors.py
# DEPENDS: M-STORAGE; existing atlas_tunnel/atlas_publish; projectmanager model.
# START_CHANGE_SUMMARY: disable accumulating compile cache in bounded tmpfs; typed safe failures and resource evidence; no disk spool.
import argparse
import datetime as dt
import fcntl
import json
import os
import selectors
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from zoneinfo import ZoneInfo

from atlas import ROOT
from atlas.run_errors import RunFailure, command_reason, resource_snapshot
from atlas.storage import Storage, StorageError


class Runner:
    def __init__(self, storage, token, env):
        self.storage, self.token, self.env = storage, token, env
        self.stage = "setup"
        self.stderr_tail = ""

    def call(self, op, **data):
        return self.storage.call(op, token=self.token, **data)

    def failure(self, rc):
        return RunFailure(
            self.stage, command_reason(self.stage, rc, self.stderr_tail), rc
        )

    def command(self, argv, name, timeout=3600):
        self.stage = name
        self.stderr_tail = ""
        if name in {"week", "preview", "a11y", "publish"}:
            self.call(
                "put",
                name=f"{name}.resources.json",
                text=json.dumps(resource_snapshot()),
            )
        p = subprocess.Popen(
            argv,
            cwd=ROOT,
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        captured = bytearray()
        selector = selectors.DefaultSelector()
        selector.register(p.stdout, selectors.EVENT_READ, "out")
        selector.register(p.stderr, selectors.EVENT_READ, "err")
        deadline = time.monotonic() + timeout
        try:
            while selector.get_map():
                if time.monotonic() >= deadline:
                    raise TimeoutError(name)
                for key, _ in selector.select(1):
                    raw = os.read(key.fileobj.fileno(), 32768)
                    if not raw:
                        selector.unregister(key.fileobj)
                        continue
                    # Backpressure: acknowledged remote write before reading more.
                    self.call(
                        "append",
                        name=f"{name}.{key.data}.log",
                        text=raw.decode("utf-8", errors="replace"),
                    )
                    if key.data == "err":
                        self.stderr_tail = (
                            self.stderr_tail + raw.decode("utf-8", errors="replace")
                        )[-32768:]
                    if key.data == "out":
                        captured.extend(raw)
                        if len(captured) > 4 * 1024**2:
                            raise ValueError("output exceeds 4MiB")
            return p.wait(timeout=5), captured.decode("utf-8")
        finally:
            selector.close()
            # Parent may already have exited while a grandchild holds the pipes.
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            p.wait()
            p.stdout.close()
            p.stderr.close()

    def notify(self, text):
        c = self.storage.config
        args = [
            "openclaw",
            "message",
            "send",
            "--channel",
            "telegram",
            "--target",
            c["notify_target"],
            "--message",
            text,
        ]
        rc, _ = self.command(args, "notification", timeout=90)
        if rc:
            raise self.failure(rc)


def execute(check=False, end=None):
    runtime = Path(os.environ.get("ATLAS_RUNTIME_DIR", "/run/atlas-weekly"))
    runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = (runtime / "runner.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    storage = Storage()
    storage.call("health")
    end = end or dt.datetime.now(ZoneInfo("Europe/Moscow")).date().isoformat()
    dt.date.fromisoformat(end)
    rid = end + "-" + uuid.uuid4().hex[:12]
    token = storage.call("begin", run=rid)
    env = os.environ.copy()
    env.setdefault(
        "CHROMIUM",
        "/root/.cache/ms-playwright/chromium_headless_shell-1187/chrome-linux/headless_shell",
    )
    env.update(
        ATLAS_STORAGE_TOKEN=token,
        PYTHONDONTWRITEBYTECODE="1",
        NODE_DISABLE_COMPILE_CACHE="1",
    )
    runner = Runner(storage, token, env)
    tunnel = None
    status = "failed"
    version = None
    publication = "not_started"
    failure = None
    try:
        # Dedicated foreground tunnel dies with the runner/service, no socket files.
        port = 55432
        tunnel = subprocess.Popen(
            [
                "ssh",
                "-N",
                "-i",
                "/root/.ssh/atlas_tunnel",
                "-o",
                "IdentitiesOnly=yes",
                "-o",
                "BatchMode=yes",
                "-o",
                "ExitOnForwardFailure=yes",
                "-o",
                "StrictHostKeyChecking=yes",
                "-o",
                "ServerAliveInterval=15",
                "-o",
                "ServerAliveCountMax=2",
                "-L",
                f"127.0.0.1:{port}:127.0.0.1:5432",
                "atlas-tunnel@194.87.143.141",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        import psycopg
        from psycopg.conninfo import make_conninfo

        env["ATLAS_DSN"] = make_conninfo(
            host="127.0.0.1",
            port=port,
            dbname="atlas",
            user="atlas",
            password=Path("/root/.config/atlas/db.pass").read_text().strip(),
        )
        for _ in range(20):
            if tunnel.poll() is not None:
                raise RunFailure("setup", "tunnel_failed")
            try:
                with psycopg.connect(env["ATLAS_DSN"], connect_timeout=2) as conn:
                    conn.execute("SELECT 1")
                break
            except psycopg.OperationalError:
                time.sleep(0.5)
        else:
            raise RunFailure("setup", "database_unavailable")
        runner.stage = "backup"
        backup = runner.call("backup")
        runner.call("put", name="backup.json", text=json.dumps(backup))
        py = str(ROOT / ".venv/bin/python")
        ssh = [
            "ssh",
            "-i",
            "/root/.ssh/atlas_publish",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "atlas@194.87.143.141",
        ]
        if check:
            rc, _ = runner.command(
                ["node", "tools/a11y_check.cjs", "https://atlas.agpm.space/"],
                "a11y",
                300,
            )
            if rc:
                raise runner.failure(rc)
            status = "checked"
            return rid
        while True:
            rc, output = runner.command(
                [py, "-m", "atlas.cli", "week", "--end", end, "--require-issue"],
                "week",
                7200,
            )
            if rc == 0:
                break
            if rc == 75 and dt.datetime.now(ZoneInfo("Europe/Moscow")).hour < 18:
                # Keep lease fresh, wait at most one hour as before.
                for _ in range(60):
                    runner.call(
                        "put", name="waiting.json", text=json.dumps({"at": time.time()})
                    )
                    time.sleep(60)
                continue
            raise runner.failure(rc)
        runner.call("put", name="week.json", text=output)
        candidate = json.loads(output).get("version")
        if candidate is not None and (
            not isinstance(candidate, str)
            or dt.date.fromisoformat(candidate).isoformat() != candidate
        ):
            raise RunFailure("week", "unexpected")
        version = candidate
        if not version:
            runner.notify(
                "Атлас AgPM: за неделю новых материалов нет, версия не создана."
            )
            status = "success"
            return rid
        for args, name, timeout in [
            (ssh + ["preview"], "preview", 300),
            (
                [
                    "node",
                    "tools/a11y_check.cjs",
                    f"https://atlas.agpm.space/v/{version}/",
                ],
                "a11y",
                300,
            ),
            (ssh + ["publish"], "publish", 300),
        ]:
            if name == "publish":
                publication = "attempted"
            rc, _ = runner.command(args, name, timeout)
            if rc:
                raise runner.failure(rc)
            if name == "publish":
                publication = "published"
        rc, summary = runner.command(
            [py, "-m", "atlas.cli", "summary", "--version", version], "summary", 60
        )
        if rc:
            raise runner.failure(rc)
        runner.notify(
            f"Атлас AgPM: опубликована версия {version}. {summary.strip()} https://atlas.agpm.space/versions/{version}/"
        )
        status = "success"
        return rid
    except Exception as exc:
        if isinstance(exc, RunFailure):
            failure = exc
        else:
            reason = (
                "storage_failed"
                if isinstance(exc, StorageError)
                else "timeout"
                if isinstance(exc, TimeoutError)
                else "unexpected"
            )
            failure = RunFailure(runner.stage, reason)
        failure.run_id, failure.version, failure.publication = rid, version, publication
        try:
            runner.call(
                "put",
                name="error.json",
                text=json.dumps({**failure.report(), "resources": resource_snapshot()}),
            )
        except Exception:
            pass  # Preserve the original failure when storage itself is unavailable.
        if failure is exc:
            raise
        raise failure from exc
    finally:
        if tunnel is not None:
            tunnel.terminate()
            try:
                tunnel.wait(timeout=10)
            except subprocess.TimeoutExpired:
                tunnel.kill()
                tunnel.wait()
        try:
            runner.call("end", state=status)
        except Exception as exc:
            if failure is None:
                end_failure = RunFailure("finalize", "storage_failed")
                end_failure.run_id, end_failure.version, end_failure.publication = (
                    rid,
                    version,
                    publication,
                )
                raise end_failure from exc
        finally:
            lock.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--check", action="store_true")
    p.add_argument("--end")
    a = p.parse_args()
    try:
        rid = execute(a.check, a.end)
        print(json.dumps({"run": rid, "ok": True}))
    except Exception as exc:
        # No traceback/DSN/payload in the local system journal.
        failure = (
            exc
            if isinstance(exc, RunFailure)
            else RunFailure(
                "setup",
                "storage_failed" if isinstance(exc, StorageError) else "unexpected",
            )
        )
        text = failure.message()
        print(text, file=sys.stderr)
        if not a.check:
            try:
                c = Storage().config
                subprocess.run(
                    [
                        "openclaw",
                        "message",
                        "send",
                        "--channel",
                        "telegram",
                        "--target",
                        c["notify_target"],
                        "--message",
                        text,
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=90,
                    check=True,
                    env={**os.environ, "NODE_DISABLE_COMPILE_CACHE": "1"},
                )
            except Exception:
                print("Atlas: failure notification could not be sent", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
