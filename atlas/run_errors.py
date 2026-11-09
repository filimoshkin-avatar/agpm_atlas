# START_MODULE_CONTRACT M-RUNNER-ERRORS: allowlisted diagnostics, no raw secrets.
# LINKS: docs/operations/storage.md; tests/test_weekly_errors.py
# START_CHANGE_SUMMARY: stage/reason/publication state instead of generic RuntimeError.
import json
import os
from pathlib import Path

REASONS = {
    "tmp_space_low": "во временном диске /tmp осталось менее 64 МиБ для Chromium",
    "tmp_unavailable": "не удалось проверить свободное место в /tmp",
    "browser_crashed": "упала вкладка Chromium; причина требует проверки ресурсного журнала",
    "browser_timeout": "браузерная проверка превысила время ожидания",
    "browser_error": "не удалось выполнить браузерную проверку",
    "a11y_violations": "обнаружены нарушения доступности serious/critical",
    "storage_failed": "не удалось прочитать или записать удалённое хранилище",
    "timeout": "превышен лимит времени этапа",
    "command_failed": "команда этапа завершилась с ошибкой",
    "tunnel_failed": "не удалось открыть SSH-туннель к базе",
    "database_unavailable": "база не ответила через SSH-туннель",
    "unexpected": "непредвиденная ошибка; проверьте журнал этапа",
}
STAGES = {
    "setup": "подготовка",
    "backup": "резервная копия",
    "week": "сбор и классификация",
    "preview": "предпросмотр",
    "a11y": "браузерная проверка доступности",
    "publish": "публикация",
    "summary": "итоговый отчёт",
    "notification": "оповещение",
    "finalize": "завершение журнала",
}


def command_reason(stage, rc, stderr):
    if stage != "a11y":
        return "command_failed"
    if rc == 1:
        return "a11y_violations"
    for line in reversed(stderr.splitlines()):
        if line.startswith("ATLAS_A11Y_ERROR "):
            try:
                code = json.loads(line[len("ATLAS_A11Y_ERROR ") :]).get("code")
                if code in {
                    "tmp_space_low",
                    "tmp_unavailable",
                    "browser_crashed",
                    "browser_timeout",
                    "browser_error",
                }:
                    return code
            except (ValueError, AttributeError, TypeError):
                pass
    return "browser_error"


class RunFailure(RuntimeError):
    def __init__(self, stage, reason, rc=None):
        self.stage = stage if stage in STAGES else "setup"
        self.reason = reason if reason in REASONS else "unexpected"
        self.rc = rc if isinstance(rc, int) else None
        self.run_id = None
        self.version = None
        self.publication = "not_started"
        super().__init__(self.reason)

    def report(self):
        return {
            "stage": self.stage,
            "reason": self.reason,
            "exit_code": self.rc,
            "run": self.run_id,
            "version": self.version,
            "publication": self.publication,
        }

    def message(self):
        lines = [
            f"Атлас: сбой на этапе «{STAGES[self.stage]}».",
            REASONS[self.reason] + ".",
        ]
        if self.rc is not None:
            lines.append(f"Код выхода: {self.rc}.")
        if self.publication == "published":
            lines.append(
                "Версия уже опубликована; повторять сбор и публикацию не нужно."
            )
        elif self.publication == "attempted":
            lines.append(
                "Публикация запускалась; её результат необходимо проверить перед повтором."
            )
        else:
            lines.append("Публикация не запускалась.")
        if self.version:
            lines.append(f"Подготовленная версия: {self.version}.")
        if self.run_id:
            lines.append(
                f"Журнал: Local Ru /var/lib/atlas/storage/runs/{self.run_id}/ ({self.stage}.err.log, error.json)."
            )
        return "\n".join(lines)


def resource_snapshot():
    """Numeric cgroup/tmpfs evidence only; no environment, command lines or DSNs."""
    snapshot = {}
    try:
        stat = os.statvfs(os.environ.get("TMPDIR", "/tmp"))
        snapshot["tmp_free_bytes"] = stat.f_bavail * stat.f_frsize
    except OSError:
        pass
    try:
        row = next(
            line
            for line in Path("/proc/self/cgroup").read_text().splitlines()
            if line.startswith("0::")
        )
        base = Path("/sys/fs/cgroup") / row[3:].lstrip("/")
        for name in (
            "memory.current",
            "memory.max",
            "memory.peak",
            "memory.events",
            "pids.current",
            "pids.max",
            "pids.events",
        ):
            try:
                snapshot[name] = (base / name).read_text().strip()
            except OSError:
                pass
    except (OSError, StopIteration):
        pass
    return snapshot
