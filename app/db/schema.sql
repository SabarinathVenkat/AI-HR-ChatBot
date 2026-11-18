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

-- A cancellation waiting for the employee's "yes". Nothing changes on the request until it is confirmed.
CREATE TABLE IF NOT EXISTS cancel_drafts (
    id          TEXT PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    request_id  INTEGER NOT NULL REFERENCES leave_requests(id),
    status      TEXT NOT NULL CHECK (status IN ('awaiting_confirmation', 'confirmed', 'cancelled', 'expired')),
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cancel_drafts_employee ON cancel_drafts(employee_id, status);

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

-- ---------------------------------------------------------------------------------------------------------
-- Resume builder (RMG). An employee can hold RMG roles on top of their HR role.
-- ---------------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rmg_roles (
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    role        TEXT NOT NULL CHECK (role IN ('rmg_staff', 'rmg_head', 'competency_lead')),
    PRIMARY KEY (employee_id, role)
);

-- Which Competency Lead approves which associate's resume. One lead per associate.
CREATE TABLE IF NOT EXISTS lead_assignments (
    associate_id INTEGER PRIMARY KEY REFERENCES employees(id),
    lead_id      INTEGER NOT NULL REFERENCES employees(id)
);

-- The resume template (a .docx). The file lives in the file store; the row says which one is active.
CREATE TABLE IF NOT EXISTS resume_templates (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    filename    TEXT NOT NULL,
    file_key    TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('active', 'archived')),
    uploaded_by INTEGER NOT NULL REFERENCES employees(id),
    created_at  TEXT NOT NULL
);

-- A job description is stored once (already read into requirements); many associates can be tagged to it.
CREATE TABLE IF NOT EXISTS job_descriptions (
    id         INTEGER PRIMARY KEY,
    title      TEXT NOT NULL,
    filename   TEXT NOT NULL,
    jd_json    TEXT NOT NULL,
    file_key   TEXT,
    created_by INTEGER NOT NULL REFERENCES employees(id),
    created_at TEXT NOT NULL
);

-- One request per tagged associate. lead_id is the Competency Lead at the time of tagging.
CREATE TABLE IF NOT EXISTS resume_requests (
    id            INTEGER PRIMARY KEY,
    jd_id         INTEGER NOT NULL REFERENCES job_descriptions(id),
    associate_id  INTEGER NOT NULL REFERENCES employees(id),
    lead_id       INTEGER REFERENCES employees(id),  -- NULL: the associate has no Competency Lead, so RMG reviews
    role_index    INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL CHECK (status IN
                    ('requested', 'in_progress', 'submitted', 'changes_requested', 'approved', 'cancelled')),
    created_by    INTEGER NOT NULL REFERENCES employees(id),
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    decided_by    INTEGER REFERENCES employees(id),
    decided_at    TEXT,
    decision_note TEXT,
    base_filename TEXT,
    base_file_key TEXT,
    UNIQUE (jd_id, associate_id)
);
CREATE INDEX IF NOT EXISTS idx_resume_requests_associate ON resume_requests(associate_id, status);
CREATE INDEX IF NOT EXISTS idx_resume_requests_lead ON resume_requests(lead_id, status);

-- The working state of a request: the resume as read, the resume being tailored, and the undo stack.
CREATE TABLE IF NOT EXISTS resume_drafts (
    request_id   INTEGER PRIMARY KEY REFERENCES resume_requests(id),
    base_json    TEXT NOT NULL,
    working_json TEXT NOT NULL,
    undo_json    TEXT NOT NULL DEFAULT '[]',
    warnings_json TEXT NOT NULL DEFAULT '[]',
    years_text   TEXT NOT NULL DEFAULT '',
    read_coverage REAL,
    template_id  INTEGER REFERENCES resume_templates(id),
    updated_at   TEXT NOT NULL
);

-- Every save, submission and approval is a version, so nothing is lost and a Lead sees what was approved.
CREATE TABLE IF NOT EXISTS resume_versions (
    id          INTEGER PRIMARY KEY,
    request_id  INTEGER NOT NULL REFERENCES resume_requests(id),
    version     INTEGER NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('saved', 'submitted', 'approved')),
    resume_json TEXT NOT NULL,
    years_text  TEXT NOT NULL DEFAULT '',
    template_id INTEGER REFERENCES resume_templates(id),
    created_by  INTEGER NOT NULL REFERENCES employees(id),
    created_at  TEXT NOT NULL,
    UNIQUE (request_id, version)
);

CREATE TABLE IF NOT EXISTS notifications (
    id          INTEGER PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    message     TEXT NOT NULL,
    request_id  INTEGER REFERENCES resume_requests(id),
    created_at  TEXT NOT NULL,
    read_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_notifications_employee ON notifications(employee_id, read_at);

-- Platform administration. An admin is an ordinary account that is also listed here; the admin chooses which modules (HR,
-- RMG) the platform offers, and everyone who signs in afterwards sees only those. A module with no row counts as on.
CREATE TABLE IF NOT EXISTS platform_admins (
    employee_id INTEGER PRIMARY KEY REFERENCES employees(id)
);

CREATE TABLE IF NOT EXISTS platform_modules (
    module     TEXT PRIMARY KEY CHECK (module IN ('hr', 'rmg')),
    enabled    INTEGER NOT NULL CHECK (enabled IN (0, 1)),
    changed_by INTEGER REFERENCES employees(id),
    changed_at TEXT
);
