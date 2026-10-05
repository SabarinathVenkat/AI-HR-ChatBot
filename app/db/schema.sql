PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS employees (
    id                INTEGER PRIMARY KEY,
    email             TEXT NOT NULL UNIQUE,
    password_hash     TEXT NOT NULL,
    name              TEXT NOT NULL,
    role              TEXT NOT NULL CHECK (role IN ('employee', 'manager', 'hr_admin')),
    manager_id        INTEGER REFERENCES employees(id),
    department        TEXT NOT NULL,
    join_date         TEXT NOT NULL,
    employment_status TEXT NOT NULL CHECK (employment_status IN ('probation', 'confirmed')),
    confirmation_date TEXT,
    gender            TEXT,
    location          TEXT NOT NULL DEFAULT 'Chennai'
);

CREATE TABLE IF NOT EXISTS leave_types (
    code               TEXT PRIMARY KEY,
    name               TEXT NOT NULL,
    annual_entitlement REAL,
    accrual_type       TEXT NOT NULL CHECK (accrual_type IN ('monthly', 'upfront', 'event')),
    carry_forward_cap  REAL NOT NULL DEFAULT 0,
    requires_confirmed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS leave_balances (
    employee_id     INTEGER NOT NULL REFERENCES employees(id),
    leave_year      INTEGER NOT NULL,
    leave_type      TEXT NOT NULL REFERENCES leave_types(code),
    accrued         REAL NOT NULL DEFAULT 0,
    used            REAL NOT NULL DEFAULT 0,
    carried_forward REAL NOT NULL DEFAULT 0,
    adjustment      REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (employee_id, leave_year, leave_type)
);

CREATE TABLE IF NOT EXISTS leave_requests (
    id              INTEGER PRIMARY KEY,
    employee_id     INTEGER NOT NULL REFERENCES employees(id),
    leave_type      TEXT NOT NULL REFERENCES leave_types(code),
    start_date      TEXT NOT NULL,
    end_date        TEXT NOT NULL,
    start_half      TEXT NOT NULL DEFAULT 'full' CHECK (start_half IN ('full', 'second')),
    end_half        TEXT NOT NULL DEFAULT 'full' CHECK (end_half IN ('full', 'first')),
    days_counted    REAL NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled')),
    reason          TEXT,
    created_at      TEXT NOT NULL,
    decided_by      INTEGER REFERENCES employees(id),
    decided_at      TEXT,
    decision_note   TEXT,
    idempotency_key TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_leave_requests_employee ON leave_requests(employee_id, status);

-- A prepared request waiting for the employee to confirm. Only the confirm endpoint, which never
-- involves the model, turns a draft into a leave request.
CREATE TABLE IF NOT EXISTS leave_drafts (
    id           TEXT PRIMARY KEY,
    employee_id  INTEGER NOT NULL REFERENCES employees(id),
    leave_type   TEXT NOT NULL REFERENCES leave_types(code),
    start_date   TEXT NOT NULL,
    end_date     TEXT NOT NULL,
    start_half   TEXT NOT NULL DEFAULT 'full' CHECK (start_half IN ('full', 'second')),
    end_half     TEXT NOT NULL DEFAULT 'full' CHECK (end_half IN ('full', 'first')),
    days_counted REAL NOT NULL,
    lop_days     REAL NOT NULL DEFAULT 0,
    reason       TEXT,
    status       TEXT NOT NULL CHECK (status IN ('awaiting_confirmation', 'confirmed', 'cancelled', 'expired')),
    created_at   TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    request_id   INTEGER REFERENCES leave_requests(id)
);
CREATE INDEX IF NOT EXISTS idx_leave_drafts_employee ON leave_drafts(employee_id, status);

CREATE TABLE IF NOT EXISTS holidays (
    date     TEXT NOT NULL,
    name     TEXT NOT NULL,
    kind     TEXT NOT NULL CHECK (kind IN ('public', 'floating_option')),
    location TEXT NOT NULL DEFAULT 'Chennai',
    PRIMARY KEY (date, location)
);

CREATE TABLE IF NOT EXISTS floating_holiday_choices (
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    year        INTEGER NOT NULL,
    date        TEXT NOT NULL,
    PRIMARY KEY (employee_id, year, date)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY,
    ts          TEXT NOT NULL,
    actor_id    INTEGER NOT NULL,
    action      TEXT NOT NULL,
    tool        TEXT,
    inputs_json TEXT,
    outputs_json TEXT,
    trace_id    TEXT
);

CREATE TABLE IF NOT EXISTS policy_chunks (
    chunk_id       INTEGER PRIMARY KEY,
    policy_id      TEXT NOT NULL,
    policy_title   TEXT NOT NULL,
    section_id     TEXT NOT NULL UNIQUE,
    clause_ids     TEXT NOT NULL DEFAULT '[]',
    title          TEXT NOT NULL,
    text           TEXT NOT NULL,
    version        TEXT NOT NULL,
    effective_date TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS policy_fts USING fts5(title, text);
CREATE VIRTUAL TABLE IF NOT EXISTS policy_vec USING vec0(
    embedding float[384] distance_metric=cosine
);
