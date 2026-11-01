-- Кабинет редактора: учётные записи, сеансы, попытки входа.
-- Пароли — только хеши argon2; в сеансах хранится sha256 токена, не токен.

CREATE TABLE editors (
    id            serial PRIMARY KEY,
    email         text NOT NULL UNIQUE,
    name          text NOT NULL,
    role          text NOT NULL CHECK (role IN ('editor', 'admin')),
    password_hash text NOT NULL,
    disabled      boolean NOT NULL DEFAULT false,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sessions (
    token_sha256 text PRIMARY KEY,
    editor_id    int NOT NULL REFERENCES editors (id),
    csrf         text NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    expires_at   timestamptz NOT NULL
);

CREATE TABLE login_attempts (
    id    bigserial PRIMARY KEY,
    email text NOT NULL,
    ok    boolean NOT NULL,
    at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX login_attempts_recent ON login_attempts (email, at);
