-- Недельный конвейер: записи выгрузки радара, тексты источников, решения
-- модели, кандидаты в сценарии и очередь редактора.

-- Каждая карточка выгрузки V2 как пришла. Связь с материалом атласа — по
-- нормализованному адресу; у склеенного материала записей несколько.
CREATE TABLE radar_records (
    radar_id    text PRIMARY KEY,
    issue_date  date NOT NULL,
    position    int  NOT NULL,
    url_norm    text NOT NULL,
    payload     jsonb NOT NULL,
    state       text NOT NULL CHECK (state IN ('new', 'linked', 'classified', 'excluded', 'deferred')),
    material_id text REFERENCES materials (id),
    detail      text NOT NULL DEFAULT '',
    run_id      bigint REFERENCES runs (id),
    fetched_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX radar_records_url ON radar_records (url_norm);

-- Извлечённый текст первоисточника. Закрытое хранилище: на сайт не попадает.
CREATE TABLE source_texts (
    url_norm     text PRIMARY KEY,
    origin       text NOT NULL CHECK (origin IN ('radar-cache', 'fetch', 'none')),
    status       text NOT NULL CHECK (status IN ('ok', 'blocked', 'failed', 'short')),
    text         text NOT NULL DEFAULT '',
    sha256       text NOT NULL,
    detail       text NOT NULL DEFAULT '',
    attempts     int  NOT NULL DEFAULT 1,
    next_attempt date,
    fetched_at   timestamptz NOT NULL DEFAULT now()
);

-- Каждое решение модели с идентификатором модели и версией инструкции.
CREATE TABLE decisions (
    id             bigserial PRIMARY KEY,
    radar_id       text REFERENCES radar_records (radar_id),
    material_id    text REFERENCES materials (id),
    kind           text NOT NULL,
    model          text NOT NULL,
    prompt_version text NOT NULL,
    data           jsonb NOT NULL,
    run_id         bigint REFERENCES runs (id),
    created_at     timestamptz NOT NULL DEFAULT now()
);

-- Предложения модели о новых сценариях. В сценарий кандидата превращает
-- редактор: склейка «по смыслу» и перенос — шаги методики.
CREATE TABLE candidates (
    id          bigserial PRIMARY KEY,
    material_id text NOT NULL REFERENCES materials (id),
    proposal    jsonb NOT NULL,
    run_id      bigint REFERENCES runs (id),
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- Очередь редактора: конфликты, смены сигналов, нарушения языка, ненайденные
-- цифры, неоткрывшиеся источники, кандидаты, вероятные дубли.
CREATE TABLE queue (
    id          bigserial PRIMARY KEY,
    kind        text NOT NULL,
    object_id   text NOT NULL,
    text        text NOT NULL,
    version     text,
    run_id      bigint REFERENCES runs (id),
    created_at  timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz
);
