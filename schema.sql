CREATE TABLE IF NOT EXISTS people (
    name TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS settings (
    owner_name TEXT NOT NULL REFERENCES people(name) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (owner_name, key)
);

CREATE TABLE IF NOT EXISTS subjects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_name TEXT NOT NULL REFERENCES people(name) ON DELETE CASCADE,
    name TEXT NOT NULL,
    UNIQUE(owner_name, name)
);

CREATE TABLE IF NOT EXISTS exams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_name TEXT NOT NULL REFERENCES people(name) ON DELETE CASCADE,
    subject_id INTEGER REFERENCES subjects(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    exam_date TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS exam_subtopic_links (
    exam_id INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    subtopic_id INTEGER NOT NULL REFERENCES subtopics(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (exam_id, subtopic_id)
);

CREATE TABLE IF NOT EXISTS topic_tables (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_name TEXT NOT NULL REFERENCES people(name) ON DELETE CASCADE,
    subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    UNIQUE(subject_id, title)
);

CREATE TABLE IF NOT EXISTS subtopics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_id INTEGER NOT NULL REFERENCES topic_tables(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    confidence INTEGER NOT NULL DEFAULT 0 CHECK (confidence BETWEEN 0 AND 10),
    UNIQUE(table_id, name)
);

CREATE TABLE IF NOT EXISTS timetable_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_name TEXT NOT NULL REFERENCES people(name) ON DELETE CASCADE,
    session_date TEXT NOT NULL,
    session_index INTEGER NOT NULL,
    session_label TEXT NOT NULL,
    session_kind TEXT NOT NULL CHECK (session_kind IN ('revision', 'past_paper')),
    subject_id INTEGER REFERENCES subjects(id) ON DELETE SET NULL,
    subject_name TEXT NOT NULL,
    title TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '',
    subtopic_ids TEXT NOT NULL DEFAULT '[]',
    duration_minutes INTEGER NOT NULL DEFAULT 90,
    completed INTEGER NOT NULL DEFAULT 0 CHECK (completed IN (0, 1)),
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(owner_name, session_date, session_index)
);
