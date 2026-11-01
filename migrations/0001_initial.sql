-- Атлас AgPM: модель данных задания v2, раздел «Модель данных».
-- Источник правды — эта база; сайт собирается из неизменяемого снимка версии.
-- У полей, которые может заполнить модель, происхождение и закрепление лежат
-- в field_meta: {"поле": {"origin": "...", "pinned": true}}.

CREATE TABLE ref_sections (
    key        text PRIMARY KEY,
    name       text NOT NULL,
    short      text NOT NULL,
    definition text NOT NULL,
    position   int  NOT NULL UNIQUE
);

CREATE TABLE ref_practices (
    key        text PRIMARY KEY,
    name       text NOT NULL UNIQUE,
    definition text NOT NULL DEFAULT '',
    position   int  NOT NULL UNIQUE
);

CREATE TABLE ref_corridors (
    key      text PRIMARY KEY CHECK (key IN ('I', 'II', 'III', 'IV')),
    name     text NOT NULL,
    sub      text NOT NULL,
    areas    text[] NOT NULL,
    position int  NOT NULL UNIQUE
);

CREATE TABLE ref_levels (
    n    int PRIMARY KEY CHECK (n BETWEEN 1 AND 4),
    name text NOT NULL,
    sub  text NOT NULL
);

CREATE TABLE ref_roles (
    name          text PRIMARY KEY,
    default_grade text NOT NULL CHECK (default_grade IN ('confirms', 'claims', 'warns', 'refutes', 'background')),
    may_count     boolean NOT NULL,
    basis         text NOT NULL,
    position      int  NOT NULL UNIQUE
);

CREATE TABLE ref_types (
    name     text PRIMARY KEY,
    position int  NOT NULL UNIQUE
);

CREATE TABLE ref_months (
    key  text PRIMARY KEY CHECK (key ~ '^\d{4}-\d{2}$'),
    name text NOT NULL
);

-- Тексты, которые справочники показывают читателю: названия сигналов, пометки
-- происхождения описания и т. п. Ключ — пара (группа, ключ).
CREATE TABLE ref_labels (
    grp  text NOT NULL,
    key  text NOT NULL,
    text text NOT NULL,
    PRIMARY KEY (grp, key)
);

-- Каждый когда-либо выданный или занятый номер. Строки не удаляются: номер не
-- переиспользуется, даже если материал исключён или склеен.
CREATE TABLE number_ledger (
    num         int PRIMARY KEY CHECK (num > 0),
    material_id text,
    issued_at   timestamptz NOT NULL DEFAULT now(),
    note        text NOT NULL DEFAULT ''
);

-- Следующий номер. Перенос эталона сдвигает его за последний занятый (№ 798).
CREATE SEQUENCE material_num_seq START 798 MINVALUE 1;

CREATE TABLE materials (
    id              text PRIMARY KEY CHECK (id ~ '^m\d{6}$'),
    num             int UNIQUE REFERENCES number_ledger (num),
    radar_ids       text[] NOT NULL DEFAULT '{}',
    url             text NOT NULL,
    url_norm        text NOT NULL UNIQUE,
    outlet          text NOT NULL,
    title           text NOT NULL,
    title_orig      text NOT NULL DEFAULT '',
    summary         text NOT NULL DEFAULT '',
    numbers         jsonb NOT NULL DEFAULT '[]',
    takeaway        text NOT NULL DEFAULT '',
    type            text REFERENCES ref_types (name),
    evidence        text CHECK (evidence IN ('сильная', 'средняя', 'слабая')),
    flags           text[] NOT NULL DEFAULT '{}',
    desc_origin     text NOT NULL CHECK (desc_origin IN ('verified', 'radar', 'title', 'none')),
    section         text REFERENCES ref_sections (key),
    practice        text REFERENCES ref_practices (key),
    perimeter       text NOT NULL DEFAULT '' CHECK (perimeter IN ('', 'near', 'mid', 'far')),
    pub_date        date,
    pub_date_origin text NOT NULL DEFAULT 'none',
    radar_dates     date[] NOT NULL DEFAULT '{}',
    first_seen      date,
    month           text REFERENCES ref_months (key),
    status          text NOT NULL CHECK (status IN ('in_atlas', 'excluded', 'duplicate')),
    status_reason   text NOT NULL DEFAULT '',
    duplicate_of    text REFERENCES materials (id),
    origin          text NOT NULL,
    field_meta      jsonb NOT NULL DEFAULT '{}',
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    -- Номер есть только у материала в атласе; у исключённого — причина, у дубля — основной.
    CHECK ((status = 'in_atlas') = (num IS NOT NULL)),
    CHECK (status <> 'excluded' OR status_reason <> ''),
    CHECK ((status = 'duplicate') = (duplicate_of IS NOT NULL)),
    CHECK (status <> 'in_atlas' OR section IS NOT NULL),
    CHECK (practice IS NULL OR section = 'practice')
);

CREATE TABLE items (
    key           text PRIMARY KEY,
    kind          text NOT NULL CHECK (kind IN ('scenario', 'neighbor', 'loss')),
    corridor      text REFERENCES ref_corridors (key),
    sub_area      text NOT NULL DEFAULT '',
    level         int  REFERENCES ref_levels (n),
    title         text NOT NULL,
    short         text NOT NULL,
    card_title    text NOT NULL DEFAULT '',
    card_line     text NOT NULL DEFAULT '',
    what          text NOT NULL DEFAULT '',
    why           text NOT NULL DEFAULT '',
    signal        text CHECK (signal IN ('confirmed', 'claimed', 'refuted')),
    signal_origin text CHECK (signal_origin IN ('rule', 'editor')),
    signal_reason text NOT NULL DEFAULT '',
    status        text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'new', 'merged', 'retired')),
    status_until  date,
    successor     text REFERENCES items (key),
    origin        text NOT NULL,
    field_meta    jsonb NOT NULL DEFAULT '{}',
    position      int  NOT NULL UNIQUE,
    CHECK ((kind = 'loss') = (signal IS NULL)),
    CHECK (kind <> 'scenario' OR corridor IS NOT NULL),
    CHECK (signal_origin <> 'editor' OR signal_reason <> '')
);

-- Зона потерь одна.
CREATE UNIQUE INDEX items_single_loss ON items ((kind)) WHERE kind = 'loss';

CREATE TABLE item_history (
    item_key text NOT NULL REFERENCES items (key),
    version  text NOT NULL,
    signal   text,
    note     text NOT NULL DEFAULT '',
    PRIMARY KEY (item_key, version)
);

-- Единственное место хранения связи «материал — пункт».
CREATE TABLE links (
    material_id text NOT NULL REFERENCES materials (id),
    item_key    text NOT NULL REFERENCES items (key),
    role        text NOT NULL REFERENCES ref_roles (name),
    grade       text NOT NULL CHECK (grade IN ('confirms', 'claims', 'warns', 'refutes', 'background')),
    counts      boolean NOT NULL,
    basis       text NOT NULL DEFAULT '',
    quote       text NOT NULL DEFAULT '',
    origin      text NOT NULL,
    pinned      boolean NOT NULL DEFAULT false,
    position    int  NOT NULL,
    PRIMARY KEY (material_id, item_key)
);

CREATE TABLE sheet_texts (
    key       text PRIMARY KEY,
    place     text NOT NULL,
    text      text NOT NULL,
    condition text NOT NULL,
    state     text NOT NULL DEFAULT 'shown' CHECK (state IN ('shown', 'withdrawn')),
    position  int  NOT NULL UNIQUE
);

-- Опубликованная или задержанная версия. Снимок неизменяем: сайт версии
-- собирается только из него, sha256 — от его канонического JSON.
CREATE TABLE versions (
    id              text PRIMARY KEY CHECK (id ~ '^\d{4}-\d{2}-\d{2}(-\d+)?$'),
    slice           date NOT NULL,
    title           text NOT NULL,
    prev            text REFERENCES versions (id),
    note            text NOT NULL DEFAULT '',
    counters        jsonb NOT NULL,
    changes         jsonb NOT NULL DEFAULT '[]',
    checks          jsonb NOT NULL DEFAULT '[]',
    state           text NOT NULL CHECK (state IN ('current', 'published', 'held', 'rolled_back')),
    snapshot        jsonb NOT NULL,
    snapshot_sha256 text NOT NULL CHECK (snapshot_sha256 ~ '^[0-9a-f]{64}$'),
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX versions_single_current ON versions ((state)) WHERE state = 'current';

CREATE TABLE edits (
    id        bigserial PRIMARY KEY,
    at        timestamptz NOT NULL DEFAULT now(),
    actor     text NOT NULL,
    object    text NOT NULL,
    object_id text NOT NULL,
    field     text NOT NULL,
    before    jsonb,
    after     jsonb,
    reason    text NOT NULL DEFAULT '',
    version   text
);

CREATE TABLE runs (
    id           bigserial PRIMARY KEY,
    kind         text NOT NULL,
    started_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz,
    cursor_from  date,
    cursor_to    date,
    counters     jsonb NOT NULL DEFAULT '{}',
    model_calls  int NOT NULL DEFAULT 0,
    model_tokens bigint NOT NULL DEFAULT 0,
    checks       jsonb NOT NULL DEFAULT '[]',
    error        text NOT NULL DEFAULT ''
);
