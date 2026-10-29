-- ERP Atlas store.  provenance is one of: git | live | worktree.
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS index_state (
    source     TEXT PRIMARY KEY,           -- git:erp, worktree:erp, live:TEST
    ref        TEXT,
    last_sha   TEXT,
    synced_at  TEXT,
    note       TEXT
);

-- content-addressed text, shared by every snapshot with the same bytes
CREATE TABLE IF NOT EXISTS blob (
    hash  TEXT PRIMARY KEY,
    text  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_file (
    provenance  TEXT NOT NULL,
    kind        TEXT NOT NULL,             -- BP MENU DICT
    name        TEXT NOT NULL,             -- original Pick name
    path        TEXT,                      -- repo path (git/worktree) or TABLE (live)
    hash        TEXT NOT NULL REFERENCES blob(hash),
    line_count  INTEGER,
    sha         TEXT,                      -- git commit it was read at
    fetched_at  TEXT,
    PRIMARY KEY (provenance, kind, name)
);

CREATE TABLE IF NOT EXISTS program (
    provenance  TEXT NOT NULL,
    name        TEXT NOT NULL,
    kind        TEXT,                      -- SUBROUTINE FUNCTION PROGRAM NONE
    params      TEXT,                      -- json list
    line_count  INTEGER,
    hash        TEXT,
    PRIMARY KEY (provenance, name)
);

CREATE TABLE IF NOT EXISTS label (
    provenance TEXT, program TEXT, name TEXT, line INTEGER
);
CREATE INDEX IF NOT EXISTS ix_label ON label(provenance, program);

CREATE TABLE IF NOT EXISTS call_edge (
    provenance TEXT, program TEXT, kind TEXT, target TEXT, line INTEGER, nargs INTEGER
);
CREATE INDEX IF NOT EXISTS ix_edge_prog ON call_edge(provenance, program);
CREATE INDEX IF NOT EXISTS ix_edge_target ON call_edge(provenance, target);

CREATE TABLE IF NOT EXISTS file_handle (
    provenance TEXT, program TEXT, var TEXT, pick_file TEXT, line INTEGER, via TEXT
);
CREATE INDEX IF NOT EXISTS ix_fh ON file_handle(provenance, program);
CREATE INDEX IF NOT EXISTS ix_fh_file ON file_handle(provenance, pick_file);

CREATE TABLE IF NOT EXISTS io_op (
    provenance TEXT, program TEXT, line INTEGER, op TEXT, file_var TEXT, pick_file TEXT,
    record_var TEXT, key_expr TEXT, attr INTEGER, via TEXT
);
CREATE INDEX IF NOT EXISTS ix_io ON io_op(provenance, program);
CREATE INDEX IF NOT EXISTS ix_io_file ON io_op(provenance, pick_file);

CREATE TABLE IF NOT EXISTS attr_ref (
    provenance TEXT, program TEXT, line INTEGER, var TEXT, pick_file TEXT,
    attr INTEGER, value_pos TEXT, access TEXT
);
CREATE INDEX IF NOT EXISTS ix_attr ON attr_ref(provenance, pick_file, attr);
CREATE INDEX IF NOT EXISTS ix_attr_prog ON attr_ref(provenance, program);

CREATE TABLE IF NOT EXISTS menu (
    code TEXT PRIMARY KEY, exec TEXT, program TEXT, used INTEGER, last_used TEXT
);
CREATE INDEX IF NOT EXISTS ix_menu_prog ON menu(program);

CREATE TABLE IF NOT EXISTS dict_attr (
    pick_file TEXT, name TEXT, type TEXT, attr INTEGER, conv TEXT, heading TEXT,
    definition TEXT, format TEXT, depth TEXT, assoc TEXT      -- depth: S single | M multivalued
);
CREATE INDEX IF NOT EXISTS ix_dict ON dict_attr(pick_file, attr);

CREATE TABLE IF NOT EXISTS drift (
    program TEXT, hunk INTEGER, class TEXT,
    git_start INTEGER, git_end INTEGER, live_start INTEGER, live_end INTEGER,
    git_text TEXT, live_text TEXT, git_commits TEXT,     -- json [{sha,author,date,summary}]
    git_hash TEXT, live_hash TEXT, computed_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_drift ON drift(program);

-- which recent git version of the file live TEST matches best ("TEST is running 1218ab83a")
CREATE TABLE IF NOT EXISTS drift_version (
    program TEXT PRIMARY KEY, sha TEXT, date TEXT, author TEXT, summary TEXT,
    real_hunks INTEGER,          -- remaining real hunks vs that commit (0 = exact match)
    behind INTEGER               -- how many commits of this file git is ahead of it
);

-- ---------------------------------------------------------------- memory

-- Knowledge memory: facts with a parity-registry style lifecycle.
CREATE TABLE IF NOT EXISTS fact (
    id           TEXT PRIMARY KEY,         -- F-0001
    text         TEXT NOT NULL,
    kind         TEXT NOT NULL,            -- rule meaning trap glossary mapping
    scope        TEXT,                     -- e.g. TRANSFER<88>, LG.XFER.MAINT, M4401
    status       TEXT NOT NULL,            -- proposed accepted stale retired
    rationale    TEXT,
    proposed_by  TEXT NOT NULL,
    accepted_by  TEXT,
    accepted_at  TEXT,
    stale_reason TEXT,
    supersedes   TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fact_cite (
    fact_id    TEXT NOT NULL REFERENCES fact(id),
    src        TEXT NOT NULL,              -- git live worktree doc parity
    ref        TEXT NOT NULL,              -- program name, doc path, or parity run id
    line       INTEGER,
    line_text  TEXT,                       -- the cited line as it was when cited
    line_hash  TEXT,
    note       TEXT
);
CREATE INDEX IF NOT EXISTS ix_cite ON fact_cite(src, ref);

CREATE TABLE IF NOT EXISTS fact_event (      -- append-only history of every transition
    fact_id TEXT, at TEXT, actor TEXT, action TEXT, detail TEXT
);

-- Episodic memory: answers given, and what people said about them.
CREATE TABLE IF NOT EXISTS answer (
    id TEXT PRIMARY KEY, user TEXT, question TEXT, answer TEXT,
    cites TEXT, facts_used TEXT, provenance TEXT, model TEXT, prompt_version TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS feedback (
    id TEXT PRIMARY KEY, answer_id TEXT REFERENCES answer(id), user TEXT,
    verdict TEXT, correction TEXT, created_at TEXT
);

-- Skill memory: append-only eval receipts (millwright rubric.jsonl style).
CREATE TABLE IF NOT EXISTS receipt (
    id TEXT PRIMARY KEY, kind TEXT, subject TEXT, score REAL, detail TEXT, sha TEXT, created_at TEXT
);

-- What people look at and search for (local, for "most looked up" and ideas).
CREATE TABLE IF NOT EXISTS activity (
    kind TEXT NOT NULL,          -- program field file menu flow search
    key  TEXT NOT NULL,          -- LG.XFER.MAINT | TRANSFER<10> | TRANSFER | M4401 | the search text
    at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_activity ON activity(kind, key);
CREATE INDEX IF NOT EXISTS ix_activity_at ON activity(at);

-- ---------------------------------------------------------------- compare (old vs new records per flow step)
CREATE TABLE IF NOT EXISTS cmp_flow (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT, created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS cmp_step (
    id TEXT PRIMARY KEY, flow_id TEXT NOT NULL, seq INTEGER, name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cmp_file (
    id TEXT PRIMARY KEY, flow_id TEXT NOT NULL, seq INTEGER, pick_file TEXT NOT NULL,
    key_template TEXT NOT NULL DEFAULT '{key}', note TEXT
);
CREATE TABLE IF NOT EXISTS cmp_run (
    id TEXT PRIMARY KEY, flow_id TEXT NOT NULL, name TEXT, legacy_key TEXT, new_key TEXT,
    created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS cmp_run_key (          -- per-run key override for one file and side
    run_id TEXT, file_id TEXT, side TEXT, key TEXT, PRIMARY KEY (run_id, file_id, side)
);
CREATE TABLE IF NOT EXISTS cmp_snapshot (
    run_id TEXT, step_id TEXT, side TEXT, file_id TEXT, record_key TEXT, found INTEGER,
    lines TEXT, hash TEXT, error TEXT, fetched_at TEXT,
    PRIMARY KEY (run_id, step_id, side, file_id)
);
CREATE TABLE IF NOT EXISTS cmp_note (             -- run_id NULL = remembered for every run of the flow
    id TEXT PRIMARY KEY, flow_id TEXT, run_id TEXT, pick_file TEXT, attr INTEGER,
    verdict TEXT, text TEXT, author TEXT, created_at TEXT, updated_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_cmp_note ON cmp_note(flow_id, pick_file, attr);

CREATE TABLE IF NOT EXISTS report (                -- PDF exports of any page, kept so they can be shared
    id TEXT PRIMARY KEY, title TEXT NOT NULL, page TEXT NOT NULL, file TEXT NOT NULL,
    bytes INTEGER, pages INTEGER, git_sha TEXT, environment TEXT, created_at TEXT
);

CREATE TABLE IF NOT EXISTS dict_model (             -- target model names per attribute, for export
    pick_file TEXT, pos INTEGER, model TEXT, format TEXT, sm TEXT, source TEXT, updated_at TEXT,
    PRIMARY KEY (pick_file, pos)
);
CREATE TABLE IF NOT EXISTS dict_model_file (
    pick_file TEXT PRIMARY KEY, description TEXT, source TEXT, updated_at TEXT
);

CREATE TABLE IF NOT EXISTS profile_run (           -- data profile of one Pick file sampled from TEST
    id TEXT PRIMARY KEY, pick_file TEXT NOT NULL, sample INTEGER, records INTEGER,
    started_at TEXT, finished_at TEXT, source_url TEXT, environment TEXT, git_sha TEXT,
    errors INTEGER, warnings INTEGER, result TEXT        -- json: aggregates only, never whole records
);
CREATE INDEX IF NOT EXISTS ix_profile_file ON profile_run(pick_file, finished_at);

CREATE TABLE IF NOT EXISTS screen (                -- one W4 GUI template (src/TEMPLATES) = one project
    project TEXT PRIMARY KEY, program TEXT, saved_at TEXT, forms INTEGER, controls INTEGER, form_list TEXT
);
CREATE TABLE IF NOT EXISTS screen_control (        -- for search: which screen has a control/caption
    project TEXT, form TEXT, control TEXT, kind TEXT, caption TEXT
);
CREATE INDEX IF NOT EXISTS ix_screen_ctl ON screen_control(project);

CREATE TABLE IF NOT EXISTS finder_scenario (      -- saved "find me test data" searches, optionally per compare flow
    id TEXT PRIMARY KEY, flow_id TEXT, pick_file TEXT NOT NULL, name TEXT NOT NULL, description TEXT,
    criteria TEXT NOT NULL, created_at TEXT, updated_at TEXT, last_run TEXT, last_count INTEGER
);

CREATE TABLE IF NOT EXISTS proc (                  -- PROC scripts / PROC menus in src/PROK
    name TEXT PRIMARY KEY, kind TEXT, title TEXT, description TEXT, schedule TEXT, lines INTEGER, data TEXT
);
CREATE TABLE IF NOT EXISTS parity (                -- migration status of a legacy job or report
    kind TEXT, name TEXT, status TEXT, target TEXT, note TEXT, updated_by TEXT, updated_at TEXT,
    PRIMARY KEY (kind, name)
);

-- ---------------------------------------------------------------- people

-- Atlas accounts. role: admin | member. A password is a scrypt hash ("scrypt$n$r$p$salt$hash").
CREATE TABLE IF NOT EXISTS app_user (
    id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, name TEXT NOT NULL, role TEXT NOT NULL,
    password TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, must_change INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL, last_login TEXT
);
-- Signed-in browsers: only a hash of the cookie token is stored.
CREATE TABLE IF NOT EXISTS app_session (
    token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES app_user(id), created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL, last_seen TEXT
);
-- Each person's own Claude: a `claude setup-token` subscription token or an API key, encrypted at rest.
CREATE TABLE IF NOT EXISTS user_claude (
    user_id TEXT PRIMARY KEY REFERENCES app_user(id), kind TEXT NOT NULL, secret TEXT NOT NULL,
    hint TEXT, added_at TEXT NOT NULL, last_used TEXT
);
-- Who did what, for admins: sign-ins, user changes, fact reviews, settings.
CREATE TABLE IF NOT EXISTS audit (
    at TEXT NOT NULL, user_id TEXT, action TEXT NOT NULL, detail TEXT
);
CREATE TABLE IF NOT EXISTS user_pref (user_id TEXT NOT NULL REFERENCES app_user(id), key TEXT NOT NULL, value TEXT,
    PRIMARY KEY (user_id, key));
-- Plain-English summaries Claude writes from the git code: one per program, plus one per section of a long
-- program. source_hash is the program's hash when written, so a changed program shows as stale.
CREATE TABLE IF NOT EXISTS summary (kind TEXT NOT NULL, program TEXT NOT NULL, start_line INTEGER NOT NULL DEFAULT 0,
    end_line INTEGER NOT NULL DEFAULT 0, source_hash TEXT NOT NULL, title TEXT NOT NULL, summary TEXT NOT NULL,
    terms TEXT NOT NULL, highlights TEXT NOT NULL, model TEXT, cost_usd REAL, by TEXT, created_at TEXT NOT NULL,
    PRIMARY KEY (kind, program, start_line));
-- Search vectors (a local embedding model) for summaries and facts; text_hash says when to re-embed.
CREATE TABLE IF NOT EXISTS embedding (kind TEXT NOT NULL, key TEXT NOT NULL, text_hash TEXT NOT NULL,
    model TEXT NOT NULL, vec BLOB NOT NULL, PRIMARY KEY (kind, key));
