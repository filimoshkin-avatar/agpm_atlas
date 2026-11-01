-- Настройки, которые администратор меняет в кабинете. Конвейер читает их из
-- базы при каждом прогоне; значения по умолчанию — из задания.
CREATE TABLE settings (
    key        text PRIMARY KEY,
    value      jsonb NOT NULL,
    label      text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by text NOT NULL DEFAULT 'задание'
);

INSERT INTO settings (key, value, label) VALUES
    ('sharp_signal_changes', '3', 'Предохранитель: смен сигнала за прогон, не больше'),
    ('sharp_old_links_share', '0.05', 'Предохранитель: доля изменённых старых связей, не больше'),
    ('model_call_limit', '400', 'Предел обращений к модели за прогон'),
    ('schedule', '"понедельник, 09:00 МСК"', 'Расписание недельного прогона (меняется в crontab управляющего сервера)'),
    ('notify', '"Telegram, чат радара"', 'Оповещения (меняются в строке crontab управляющего сервера)');
