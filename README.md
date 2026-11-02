# Атлас AgPM

Еженедельный «Атлас агентного управления проектами» по материалам AgPM Radar,
сайт — https://atlas.agpm.space/ (адрес ещё не заведён).

Сайт: https://atlas.agpm.space/ · кабинет: https://atlas.agpm.space/editor/

Этапы 0–4 выполнены: `docs/Записка_разведки_v1.md`, `docs/Отчёт_переноса_v1.md`,
`docs/Отчёт_этапа_2_v1.md`, `docs/План_этапа_3_v1.md`, `docs/Отчёт_этапа_4_v1.md`.
Проверка этапа 3 — четыре недельных прогона подряд — идёт с 02.11.2026.
Дежурному — `docs/Инструкция_дежурного_v1.md`.

## Запуск

```
uv sync                                    # зависимости в .venv
psql -c "CREATE DATABASE atlas"            # база; адрес — ATLAS_DSN
.venv/bin/python -m atlas.cli import --radar-dump var/radar-dump
.venv/bin/python -m atlas.cli first-version   # версия 2026-10-09 со сверкой
.venv/bin/python -m atlas.cli build-site      # сайт в var/site/2026-10-09/
bash scripts/verify.sh                     # гейт
```

Работа на проде (база и кабинет на Local Ru, конвейер с моделью — здесь):

```
bash scripts/weekly.sh [ГГГГ-ММ-ДД]        # недельный прогон: туннель, копия базы, забор, модель,
                                           # предпросмотр, доступность, публикация, картинка, Telegram
bash scripts/deploy_code.sh                # выкладка кода на Local Ru (из чистого дерева)
# после выкладки кода сайта — пересобрать папки версий на Local Ru:
#   atlas.cli rebuild-site --version <id>  (для каждой версии)
node tools/usability_check.cjs https://atlas.agpm.space/   # 16 сценариев юзабилити
node tools/a11y_check.cjs https://atlas.agpm.space/        # axe-core, обе темы, 390 и 1440
```

| Путь | Что это |
| --- | --- |
| `atlas/` | код: нормализация адресов, правила, импорт, снимок, сверка, сборка сайта |
| `migrations/` | схема PostgreSQL |
| `site/` | шаблон страницы и ассеты сайта (основа — прототип v3) |
| `tests/`, `scripts/verify.sh` | проверки и гейт |
| `tools/` | сверка эталона; проверки сайта в браузере, юзабилити и доступности; загрузка страниц браузером |
| `deploy/` | блок Caddy, юнит кабинета, разовая подготовка Local Ru, принудительная команда ключа |
| `Правила_атласа.md` | правила атласа — единственное место, где они записаны |

| Путь | Что это |
| --- | --- |
| `docs/spec/` | задание на разработку v2 (`.md` — рабочая копия, `.docx`), схемы, описание комплекта |
| `prototype/` | фронтенд-прототип v3 (`atlas-site/`), он же одним файлом, лист логотипов |
| `reference/` | октябрьский атлас 2026-10-09: исходный HTML и извлечённые из него базовые данные — эталон переноса и оценки |

Живая версия задания: https://claude.ai/artifact/RHhwnCeUPjyuJFtD4aAdyV.
При расхождении правила и приёмка — по заданию, вид — по прототипу, числа и
тексты эталона — по `reference/`.

## Operational storage (2026-11-02)

Collection/model stay on srv2. Cache, run logs and dumps now use Local Ru; see
`docs/operations/storage.md` for paths, retention, verification and rollback.
The older path examples above describe initial setup, not live operational storage.
