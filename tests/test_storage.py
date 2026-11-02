# V-M-STORAGE / V-M-RETENTION: isolated files only, no production calls.
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import pytest

from atlas.model import Model
from atlas.storage import StorageError

sys.path.insert(0, str(Path(__file__).parents[1] / "deploy"))
from storage_retention import archive, backup_candidates, maintain
from storage_server import Store


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "state", tmp_path / "backups")
    s.backups.mkdir()
    return s


def begin(store):
    return store.handle({"op": "begin", "run": "2026-11-02-abcdef123456"})


def test_rpc_lease_cache_paths_and_atomic_write(store, tmp_path):
    token = begin(store)
    key = "a" * 64

    def call(op, **d):
        return store.handle({"op": op, "token": token, **d})

    with pytest.raises(ValueError):
        begin(store)
    with pytest.raises(ValueError):
        call("put", name="../escape", text="x")
    with pytest.raises(ValueError):
        call("cache_get", key="../../bad")
    assert call("cache_get", key=key) is None
    call("cache_put", key=key, value={"text": "hello"})
    assert call("cache_get", key=key)["text"] == "hello"
    assert not list(store.root.rglob("*.part-*"))
    outside = tmp_path / "outside"
    outside.mkdir()
    (store.root / "runs" / "2026-11-02-abcdef123456" / "evil").symlink_to(
        outside / "file"
    )
    with pytest.raises(ValueError):
        call("put", name="evil", text="x")
    call("end", state="success")
    with pytest.raises(ValueError):
        call("cache_get", key=key)


def test_model_remote_hit_and_failure_do_not_call_model(tmp_path):
    model = Model(
        "a/b", lambda *_: pytest.fail("model must not be called"), cache_dir=tmp_path
    )

    class Remote:
        def call(self, *a, **kw):
            return {"text": '{"ok":true}'}

    model.remote = Remote()
    assert model._call("v1", "prompt") == '{"ok":true}'

    class Failed:
        def call(self, *a, **kw):
            raise StorageError("offline")

    model.remote = Failed()
    with pytest.raises(StorageError):
        model._call("v1", "prompt")
    assert not list(tmp_path.iterdir())


def test_retention_pins_symlinks_active_and_age(store, tmp_path):
    root = store.root / "model-cache"
    root.mkdir(parents=True)
    old = root / "old"
    old.write_text("x")
    os.utime(old, (0, 0))
    protected = root / "pinned"
    protected.mkdir()
    (protected / ".pin").touch()
    keep = protected / "old"
    keep.write_text("keep")
    os.utime(keep, (0, 0))
    external = tmp_path / "external"
    external.write_text("external")
    os.utime(external, (0, 0))
    (root / "link").symlink_to(external)
    assert maintain(store)["count"] == 1
    assert old.exists()
    token = begin(store)
    assert maintain(store, apply=True)["skipped"] == "active run"
    store.handle({"op": "end", "token": token})
    maintain(store, apply=True)
    assert not old.exists() and keep.exists() and external.exists()


def test_archive_roundtrip_and_preserved_age(tmp_path):
    import gzip

    p = tmp_path / "run.log"
    p.write_bytes(b"hello\n" * 1000)
    os.utime(p, (10, 10))
    archive(p)
    assert not p.exists()
    z = tmp_path / "run.log.gz"
    assert gzip.open(z).read() == b"hello\n" * 1000
    assert z.stat().st_mtime == 10


def test_backups_keep_two_and_fail_closed_on_stale_latest(store):
    now = time.time()
    for i, age in enumerate([0, 200, 201]):
        p = store.backups / f"b{i}.dump"
        p.write_bytes(str(i).encode())
        p.with_suffix(".json").write_text(
            json.dumps(
                {
                    "created": now - age * 86400,
                    "kind": "prepublish",
                    "archive_checked": True,
                    "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                }
            )
        )
    assert {p.name for p in backup_candidates(store.backups, now)} == {
        "b2.dump",
        "b2.json",
    }
    assert backup_candidates(store.backups, now + 3 * 86400) == []


def test_remote_cache_write_failure_is_not_silently_accepted(tmp_path):
    calls = []
    m = Model("a/b", lambda *_: '{"ok":true}', cache_dir=tmp_path)

    class Remote:
        def call(self, op, **data):
            calls.append(op)
            if op == "cache_get":
                return None
            raise StorageError("disk full")

    m.remote = Remote()
    with pytest.raises(StorageError):
        m._call("v1", "prompt")
    assert calls == ["cache_get", "cache_put"]
    assert not list(tmp_path.iterdir())


def test_runner_logs_remotely_and_kills_on_storage_failure():
    from atlas.weekly import Runner

    class Store:
        def call(self, *a, **kw):
            raise StorageError("offline")

    r = Runner(Store(), "test", os.environ.copy())
    started = time.monotonic()
    with pytest.raises(StorageError):
        r.command(
            [
                sys.executable,
                "-c",
                'import time; print("x",flush=True); time.sleep(30)',
            ],
            "test",
            timeout=10,
        )
    assert time.monotonic() - started < 10


def test_runner_timeout_and_complete_output():
    from atlas.weekly import Runner

    logs = []

    class Store:
        def call(self, *a, **kw):
            logs.append(kw)

    r = Runner(Store(), "test", os.environ.copy())
    assert r.command([sys.executable, "-c", 'print("hello")'], "test") == (0, "hello\n")
    assert logs[0]["text"] == "hello\n"
    with pytest.raises(TimeoutError):
        r.command(
            [sys.executable, "-c", "import time; time.sleep(30)"], "test", timeout=0.1
        )


def test_runner_timeout_kills_grandchild_after_parent_exit():
    from atlas.weekly import Runner

    logs = []

    class Remote:
        def call(self, *a, **kw):
            logs.append(kw.get("text", ""))

    code = (
        "import subprocess,sys,os; "
        'p=subprocess.Popen([sys.executable,"-c",'
        '"import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(30)"]); '
        "print(p.pid,flush=True); os._exit(0)"
    )
    runner = Runner(Remote(), "test", os.environ.copy())
    with pytest.raises(TimeoutError):
        runner.command([sys.executable, "-c", code], "tree", timeout=1)
    pid = int("".join(logs).strip())
    for _ in range(20):
        path = Path(f"/proc/{pid}/stat")
        if not path.exists() or path.read_text().split()[2] == "Z":
            break
        time.sleep(0.05)
    else:
        pytest.fail("grandchild survived timeout")
