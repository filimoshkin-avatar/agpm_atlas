# V-M-RUNNER: fail-closed publication, safe notifications and bounded compile cache.
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

from atlas import weekly
from atlas.run_errors import RunFailure, command_reason
from atlas.storage import StorageError


@pytest.mark.parametrize(
    "code", ["tmp_space_low", "browser_crashed", "browser_timeout", "tmp_unavailable"]
)
def test_structured_browser_reason(code):
    assert (
        command_reason("a11y", 2, "ATLAS_A11Y_ERROR " + json.dumps({"code": code}))
        == code
    )


def test_unknown_details_never_reach_notification():
    secret = "postgres://user:password@private/database"
    assert (
        command_reason("a11y", 2, "ATLAS_A11Y_ERROR " + json.dumps({"code": secret}))
        == "browser_error"
    )
    assert command_reason("a11y", 2, "ATLAS_A11Y_ERROR []") == "browser_error"
    assert command_reason("a11y", 1, secret) == "a11y_violations"
    assert secret not in RunFailure(secret, secret).message()


def fake_run(monkeypatch, tmp_path, failed_stage=None, failure_rc=2, end_error=False):
    calls, commands = [], []

    class Store:
        config = {}

        def call(self, op, **data):
            calls.append((op, data))
            if op == "begin":
                return "private-token"
            if op == "end" and end_error:
                raise StorageError("private-secret")
            return {}

    class Tunnel:
        def poll(self):
            return None

        def terminate(self):
            pass

        def wait(self, **kw):
            return 0

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, *args):
            pass

    monkeypatch.setenv("ATLAS_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(weekly, "Storage", Store)
    monkeypatch.setattr(weekly.subprocess, "Popen", lambda *a, **kw: Tunnel())
    monkeypatch.setitem(
        sys.modules,
        "psycopg",
        types.SimpleNamespace(
            connect=lambda *a, **kw: Connection(), OperationalError=OSError
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "psycopg.conninfo",
        types.SimpleNamespace(make_conninfo=lambda **kw: "private-dsn"),
    )
    original_read = Path.read_text
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda self, *a, **kw: (
            "private-password"
            if str(self) == "/root/.config/atlas/db.pass"
            else original_read(self, *a, **kw)
        ),
    )

    def command(self, argv, name, timeout=3600):
        commands.append(name)
        self.stage = name
        assert self.env["NODE_DISABLE_COMPILE_CACHE"] == "1"
        self.stderr_tail = 'ATLAS_A11Y_ERROR {"code":"tmp_space_low"}'
        if name == failed_stage:
            return failure_rc, ""
        return 0, json.dumps({"version": "2026-11-09"}) if name == "week" else "{}"

    monkeypatch.setattr(weekly.Runner, "command", command)
    monkeypatch.setattr(weekly.Runner, "notify", lambda *a: None)
    return calls, commands


def test_a11y_failure_never_publishes_and_preserves_cause_when_storage_end_fails(
    monkeypatch, tmp_path
):
    calls, commands = fake_run(monkeypatch, tmp_path, "a11y", end_error=True)
    with pytest.raises(RunFailure) as caught:
        weekly.execute(end="2026-11-09")
    assert commands == ["week", "preview", "a11y"]
    error = caught.value
    assert error.reason == "tmp_space_low"
    assert error.publication == "not_started"
    assert error.version == "2026-11-09"
    report = next(
        json.loads(data["text"])
        for op, data in calls
        if data.get("name") == "error.json"
    )
    assert report["reason"] == "tmp_space_low"
    assert "private-" not in json.dumps(report)
    assert "Публикация не запускалась" in error.message()


@pytest.mark.parametrize(
    "stage,state", [("publish", "attempted"), ("summary", "published")]
)
def test_notification_never_claims_publication_did_not_start_after_attempt(
    monkeypatch, tmp_path, stage, state
):
    fake_run(monkeypatch, tmp_path, stage)
    with pytest.raises(RunFailure) as caught:
        weekly.execute(end="2026-11-09")
    assert caught.value.publication == state
    assert "Публикация не запускалась" not in caught.value.message()


def test_successful_order_and_compile_cache_disabled(monkeypatch, tmp_path):
    calls, commands = fake_run(monkeypatch, tmp_path)
    assert weekly.execute(end="2026-11-09").startswith("2026-11-09-")
    assert commands == ["week", "preview", "a11y", "publish", "summary"]
    assert calls[-1] == ("end", {"token": "private-token", "state": "success"})


def test_notification_failure_cannot_hide_primary_error(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["weekly"])

    def fail(*a, **kw):
        raise StorageError("private-password")

    monkeypatch.setattr(weekly, "execute", fail)
    monkeypatch.setattr(weekly, "Storage", fail)
    assert weekly.main() == 1
    err = capsys.readouterr().err
    assert "private-password" not in err
    assert "хранилище" in err


def test_real_subprocess_stderr_marker_is_classified():
    class Store:
        def call(self, *a, **kw):
            pass

    runner = weekly.Runner(Store(), "token", os.environ.copy())
    rc, _ = runner.command(
        [
            sys.executable,
            "-c",
            'import sys; print(\'ATLAS_A11Y_ERROR {"code":"tmp_space_low"}\', file=sys.stderr); sys.exit(2)',
        ],
        "a11y",
    )
    assert runner.failure(rc).reason == "tmp_space_low"


def test_node_a11y_regressions():
    subprocess.run(
        ["node", "--test", "tests/test_a11y.cjs"],
        cwd=weekly.ROOT,
        check=True,
        capture_output=True,
    )


def test_a11y_records_resource_snapshot_before_spawn():
    writes = []

    class Store:
        def call(self, op, **data):
            writes.append((op, data))

    runner = weekly.Runner(Store(), "token", os.environ.copy())
    rc, _ = runner.command([sys.executable, "-c", 'print("ok")'], "a11y")
    assert rc == 0
    op, data = writes[0]
    assert op == "put" and data["name"] == "a11y.resources.json"
    assert json.loads(data["text"])["tmp_free_bytes"] >= 0
    assert "private-" not in data["text"]
