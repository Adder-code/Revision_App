from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "revision_app.db"
SCHEMA_PATH = BASE_DIR / "schema.sql"
DEFAULT_PERSON = "Gus"

_current_person = DEFAULT_PERSON


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _rows(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
    return [dict(row) for row in cursor.fetchall()]


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {row["name"] for row in _rows(conn.execute(f"PRAGMA table_info({table_name})"))}


def _ensure_default_person(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO people(name) VALUES (?)",
        (DEFAULT_PERSON,),
    )


def _rebuild_legacy_table(
    conn: sqlite3.Connection,
    table_name: str,
    create_sql: str,
    copy_sql: str,
) -> None:
    conn.execute(f"DROP TABLE IF EXISTS {table_name}_new")
    conn.execute(create_sql)
    conn.execute(copy_sql)
    conn.execute(f"DROP TABLE {table_name}")
    conn.execute(f"ALTER TABLE {table_name}_new RENAME TO {table_name}")


def _migrate_schema(conn: sqlite3.Connection) -> None:
    _ensure_default_person(conn)

    if "owner_name" not in _table_columns(conn, "settings"):
        _rebuild_legacy_table(
            conn,
            "settings",
            """
            CREATE TABLE settings_new (
                owner_name TEXT NOT NULL REFERENCES people(name) ON DELETE CASCADE,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                PRIMARY KEY (owner_name, key)
            )
            """,
            """
            INSERT INTO settings_new(owner_name, key, value)
            SELECT 'Gus', key, value FROM settings
            """,
        )

    if "owner_name" not in _table_columns(conn, "subjects"):
        _rebuild_legacy_table(
            conn,
            "subjects",
            """
            CREATE TABLE subjects_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_name TEXT NOT NULL REFERENCES people(name) ON DELETE CASCADE,
                name TEXT NOT NULL,
                UNIQUE(owner_name, name)
            )
            """,
            """
            INSERT INTO subjects_new(id, owner_name, name)
            SELECT id, 'Gus', name FROM subjects
            """,
        )

    if "owner_name" not in _table_columns(conn, "exams"):
        _rebuild_legacy_table(
            conn,
            "exams",
            """
            CREATE TABLE exams_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_name TEXT NOT NULL REFERENCES people(name) ON DELETE CASCADE,
                subject_id INTEGER REFERENCES subjects(id) ON DELETE SET NULL,
                name TEXT NOT NULL,
                exam_date TEXT NOT NULL,
                notes TEXT NOT NULL DEFAULT ''
            )
            """,
            """
            INSERT INTO exams_new(id, owner_name, subject_id, name, exam_date, notes)
            SELECT id, 'Gus', subject_id, name, exam_date, notes FROM exams
            """,
        )

    if "owner_name" not in _table_columns(conn, "topic_tables"):
        _rebuild_legacy_table(
            conn,
            "topic_tables",
            """
            CREATE TABLE topic_tables_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_name TEXT NOT NULL REFERENCES people(name) ON DELETE CASCADE,
                subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                UNIQUE(subject_id, title)
            )
            """,
            """
            INSERT INTO topic_tables_new(id, owner_name, subject_id, title)
            SELECT id, 'Gus', subject_id, title FROM topic_tables
            """,
        )

    if "owner_name" not in _table_columns(conn, "timetable_items"):
        _rebuild_legacy_table(
            conn,
            "timetable_items",
            """
            CREATE TABLE timetable_items_new (
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
            )
            """,
            """
            INSERT INTO timetable_items_new(
                id, owner_name, session_date, session_index, session_label, session_kind,
                subject_id, subject_name, title, details, subtopic_ids, duration_minutes,
                completed, completed_at, created_at
            )
            SELECT
                id, 'Gus', session_date, session_index, session_label, session_kind,
                subject_id, subject_name, title, details, subtopic_ids, duration_minutes,
                completed, completed_at, created_at
            FROM timetable_items
            """,
        )


def init_db() -> None:
    with connect() as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.executescript(SCHEMA_PATH.read_text())
        _migrate_schema(conn)
        _ensure_default_person(conn)
        conn.execute("PRAGMA foreign_keys = ON")


def get_current_person() -> str:
    return _current_person


def set_current_person(name: str) -> None:
    global _current_person
    clean_name = str(name).strip()
    _current_person = clean_name or DEFAULT_PERSON


def get_people() -> list[str]:
    with connect() as conn:
        rows = conn.execute("SELECT name FROM people ORDER BY name COLLATE NOCASE, name").fetchall()
    return [str(row["name"]) for row in rows]


def create_person(name: str) -> str:
    clean_name = str(name).strip()
    if not clean_name:
        return get_current_person()
    with connect() as conn:
        conn.execute("INSERT OR IGNORE INTO people(name) VALUES (?)", (clean_name,))
    return clean_name


def get_setting(key: str, default: str) -> str:
    with connect() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE owner_name = ? AND key = ?",
            (get_current_person(), key),
        ).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO settings(owner_name, key, value)
            VALUES (?, ?, ?)
            ON CONFLICT(owner_name, key) DO UPDATE SET value = excluded.value
            """,
            (get_current_person(), key, value),
        )


def get_planner_range() -> dict[str, str]:
    today = date.today().isoformat()
    return {
        "start_date": get_setting("start_date", today),
        "end_date": get_setting("end_date", today),
    }


def save_planner_range(start_date: str, end_date: str) -> None:
    set_setting("start_date", start_date)
    set_setting("end_date", end_date)


def get_subjects() -> list[dict[str, Any]]:
    with connect() as conn:
        return _rows(
            conn.execute(
                "SELECT id, name FROM subjects WHERE owner_name = ? ORDER BY name",
                (get_current_person(),),
            )
        )


def save_subjects(rows: list[dict[str, Any]]) -> None:
    clean_rows = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name", "")).strip()
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        clean_rows.append({"id": row.get("id"), "name": name})

    with connect() as conn:
        existing = {
            row["id"]
            for row in _rows(
                conn.execute(
                    "SELECT id FROM subjects WHERE owner_name = ?",
                    (get_current_person(),),
                )
            )
        }
        kept_ids: set[int] = set()
        for row in clean_rows:
            row_id = row.get("id")
            if isinstance(row_id, int) and row_id in existing:
                conn.execute(
                    "UPDATE subjects SET name = ? WHERE id = ? AND owner_name = ?",
                    (row["name"], row_id, get_current_person()),
                )
                kept_ids.add(row_id)
            else:
                cursor = conn.execute(
                    "INSERT INTO subjects(owner_name, name) VALUES (?, ?)",
                    (get_current_person(), row["name"]),
                )
                kept_ids.add(cursor.lastrowid)
        delete_ids = existing - kept_ids
        if delete_ids:
            conn.executemany(
                "DELETE FROM subjects WHERE id = ? AND owner_name = ?",
                [(row_id, get_current_person()) for row_id in delete_ids],
            )


def get_exams() -> list[dict[str, Any]]:
    with connect() as conn:
        exams = _rows(
            conn.execute(
                """
                SELECT exams.id, exams.name, exams.subject_id, subjects.name AS subject_name,
                       exams.exam_date, exams.notes
                FROM exams
                LEFT JOIN subjects ON subjects.id = exams.subject_id
                WHERE exams.owner_name = ?
                ORDER BY exams.exam_date, exams.name
                """,
                (get_current_person(),),
            )
        )
        link_rows = _rows(
            conn.execute(
                """
                SELECT exam_subtopic_links.exam_id, subtopics.id AS subtopic_id, subtopics.name AS subtopic_name,
                       topic_tables.title AS table_title
                FROM exam_subtopic_links
                JOIN exams ON exams.id = exam_subtopic_links.exam_id
                JOIN subtopics ON subtopics.id = exam_subtopic_links.subtopic_id
                JOIN topic_tables ON topic_tables.id = subtopics.table_id
                WHERE exams.owner_name = ?
                """,
                (get_current_person(),),
            )
        )
    link_map: dict[int, list[dict[str, Any]]] = {}
    for row in link_rows:
        link_map.setdefault(row["exam_id"], []).append(row)
    for exam in exams:
        links = link_map.get(exam["id"], [])
        exam["linked_subtopic_ids"] = [row["subtopic_id"] for row in links]
        exam["linked_topics"] = ", ".join(
            f"{row['table_title']}: {row['subtopic_name']}" for row in links[:4]
        )
        if len(links) > 4:
            exam["linked_topics"] += f" +{len(links) - 4} more"
    return exams


def save_exams(rows: list[dict[str, Any]]) -> None:
    subject_lookup = {row["name"]: row["id"] for row in get_subjects()}
    clean_rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name", "")).strip()
        raw_date = str(row.get("exam_date", "")).strip()
        if not name or not raw_date:
            continue
        subject_name = str(row.get("subject_name", "")).strip()
        subject_id = subject_lookup.get(subject_name)
        clean_rows.append(
            {
                "id": row.get("id"),
                "name": name,
                "subject_id": subject_id,
                "exam_date": raw_date,
                "notes": str(row.get("notes", "")).strip(),
            }
        )

    with connect() as conn:
        existing = {
            row["id"]
            for row in _rows(
                conn.execute(
                    "SELECT id FROM exams WHERE owner_name = ?",
                    (get_current_person(),),
                )
            )
        }
        kept_ids: set[int] = set()
        for row in clean_rows:
            row_id = row.get("id")
            if isinstance(row_id, int) and row_id in existing:
                conn.execute(
                    """
                    UPDATE exams
                    SET name = ?, subject_id = ?, exam_date = ?, notes = ?
                    WHERE id = ? AND owner_name = ?
                    """,
                    (
                        row["name"],
                        row["subject_id"],
                        row["exam_date"],
                        row["notes"],
                        row_id,
                        get_current_person(),
                    ),
                )
                kept_ids.add(row_id)
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO exams(owner_name, name, subject_id, exam_date, notes)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        get_current_person(),
                        row["name"],
                        row["subject_id"],
                        row["exam_date"],
                        row["notes"],
                    ),
                )
                kept_ids.add(cursor.lastrowid)
        delete_ids = existing - kept_ids
        if delete_ids:
            conn.executemany(
                "DELETE FROM exams WHERE id = ? AND owner_name = ?",
                [(row_id, get_current_person()) for row_id in delete_ids],
            )


def get_topic_tables() -> list[dict[str, Any]]:
    with connect() as conn:
        return _rows(
            conn.execute(
                """
                SELECT topic_tables.id, topic_tables.subject_id, topic_tables.title, subjects.name AS subject_name
                FROM topic_tables
                JOIN subjects ON subjects.id = topic_tables.subject_id
                WHERE topic_tables.owner_name = ?
                ORDER BY subjects.name, topic_tables.title
                """,
                (get_current_person(),),
            )
        )


def create_topic_table(subject_id: int, title: str) -> None:
    clean_title = title.strip()
    if not clean_title:
        return
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO topic_tables(owner_name, subject_id, title) VALUES (?, ?, ?)",
            (get_current_person(), subject_id, clean_title),
        )


def rename_topic_table(table_id: int, title: str) -> None:
    clean_title = title.strip()
    if not clean_title:
        return
    with connect() as conn:
        conn.execute(
            "UPDATE topic_tables SET title = ? WHERE id = ? AND owner_name = ?",
            (clean_title, table_id, get_current_person()),
        )


def delete_topic_table(table_id: int) -> None:
    with connect() as conn:
        conn.execute(
            "DELETE FROM topic_tables WHERE id = ? AND owner_name = ?",
            (table_id, get_current_person()),
        )


def get_subtopics_for_table(table_id: int) -> list[dict[str, Any]]:
    with connect() as conn:
        return _rows(
            conn.execute(
                """
                SELECT subtopics.id, subtopics.table_id, subtopics.name AS subtopic, subtopics.confidence
                FROM subtopics
                JOIN topic_tables ON topic_tables.id = subtopics.table_id
                WHERE subtopics.table_id = ? AND topic_tables.owner_name = ?
                ORDER BY subtopics.name
                """,
                (table_id, get_current_person()),
            )
        )


def get_subtopic_options(subject_id: int | None = None) -> list[dict[str, Any]]:
    query = """
        SELECT subtopics.id, subtopics.name AS subtopic_name, topic_tables.title AS table_title,
               subjects.id AS subject_id, subjects.name AS subject_name
        FROM subtopics
        JOIN topic_tables ON topic_tables.id = subtopics.table_id
        JOIN subjects ON subjects.id = topic_tables.subject_id
        WHERE topic_tables.owner_name = ?
    """
    params: tuple[Any, ...] = (get_current_person(),)
    if subject_id is not None:
        query += " AND subjects.id = ?"
        params += (subject_id,)
    query += " ORDER BY subjects.name, topic_tables.title, subtopics.name"
    with connect() as conn:
        return _rows(conn.execute(query, params))


def save_exam_links(exam_id: int, subtopic_ids: list[int]) -> None:
    clean_ids = sorted({int(value) for value in subtopic_ids})
    with connect() as conn:
        exam = conn.execute(
            "SELECT id FROM exams WHERE id = ? AND owner_name = ?",
            (exam_id, get_current_person()),
        ).fetchone()
        if exam is None:
            return
        conn.execute("DELETE FROM exam_subtopic_links WHERE exam_id = ?", (exam_id,))
        conn.executemany(
            "INSERT INTO exam_subtopic_links(exam_id, subtopic_id) VALUES (?, ?)",
            [(exam_id, subtopic_id) for subtopic_id in clean_ids],
        )


def get_all_subtopics() -> list[dict[str, Any]]:
    with connect() as conn:
        return _rows(
            conn.execute(
                """
                SELECT subtopics.id, subtopics.confidence, subtopics.name AS subtopic,
                       topic_tables.id AS table_id, topic_tables.title AS table_title,
                       subjects.id AS subject_id, subjects.name AS subject_name
                FROM subtopics
                JOIN topic_tables ON topic_tables.id = subtopics.table_id
                JOIN subjects ON subjects.id = topic_tables.subject_id
                WHERE topic_tables.owner_name = ?
                ORDER BY subjects.name, topic_tables.title, subtopics.name
                """,
                (get_current_person(),),
            )
        )


def save_subtopics(table_id: int, rows: list[dict[str, Any]]) -> None:
    clean_rows = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        subtopic = str(row.get("subtopic", "")).strip()
        if not subtopic:
            continue
        key = subtopic.casefold()
        if key in seen:
            continue
        seen.add(key)
        try:
            confidence = int(row.get("confidence", 0))
        except (TypeError, ValueError):
            confidence = 0
        clean_rows.append(
            {
                "id": row.get("id"),
                "subtopic": subtopic,
                "confidence": max(0, min(10, confidence)),
            }
        )

    with connect() as conn:
        owner_row = conn.execute(
            "SELECT id FROM topic_tables WHERE id = ? AND owner_name = ?",
            (table_id, get_current_person()),
        ).fetchone()
        if owner_row is None:
            return

        existing = {
            row["id"]
            for row in _rows(
                conn.execute(
                    """
                    SELECT subtopics.id
                    FROM subtopics
                    JOIN topic_tables ON topic_tables.id = subtopics.table_id
                    WHERE subtopics.table_id = ? AND topic_tables.owner_name = ?
                    """,
                    (table_id, get_current_person()),
                )
            )
        }
        kept_ids: set[int] = set()
        for row in clean_rows:
            row_id = row.get("id")
            if isinstance(row_id, int) and row_id in existing:
                conn.execute(
                    "UPDATE subtopics SET name = ?, confidence = ? WHERE id = ?",
                    (row["subtopic"], row["confidence"], row_id),
                )
                kept_ids.add(row_id)
            else:
                cursor = conn.execute(
                    "INSERT INTO subtopics(table_id, name, confidence) VALUES (?, ?, ?)",
                    (table_id, row["subtopic"], row["confidence"]),
                )
                kept_ids.add(cursor.lastrowid)
        delete_ids = existing - kept_ids
        if delete_ids:
            conn.executemany("DELETE FROM subtopics WHERE id = ?", [(row_id,) for row_id in delete_ids])


def replace_timetable(items: list[dict[str, Any]]) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM timetable_items WHERE owner_name = ?", (get_current_person(),))
        conn.executemany(
            """
            INSERT INTO timetable_items(
                owner_name, session_date, session_index, session_label, session_kind, subject_id,
                subject_name, title, details, subtopic_ids, duration_minutes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    get_current_person(),
                    item["session_date"],
                    item["session_index"],
                    item["session_label"],
                    item["session_kind"],
                    item["subject_id"],
                    item["subject_name"],
                    item["title"],
                    item["details"],
                    json.dumps(item["subtopic_ids"]),
                    item["duration_minutes"],
                )
                for item in items
            ],
        )


def get_timetable(active_only: bool = False) -> list[dict[str, Any]]:
    query = """
        SELECT id, session_date, session_index, session_label, session_kind, subject_id,
               subject_name, title, details, subtopic_ids, duration_minutes, completed, completed_at
        FROM timetable_items
        WHERE owner_name = ?
    """
    params: tuple[Any, ...] = (get_current_person(),)
    if active_only:
        query += " AND completed = 0"
    query += " ORDER BY session_date, session_index, id"
    with connect() as conn:
        rows = _rows(conn.execute(query, params))
    for row in rows:
        row["subtopic_ids"] = json.loads(row["subtopic_ids"] or "[]")
        row["completed"] = bool(row["completed"])
    return rows


def clear_timetable() -> None:
    with connect() as conn:
        conn.execute("DELETE FROM timetable_items WHERE owner_name = ?", (get_current_person(),))


def complete_timetable_item(item_id: int) -> None:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT id, session_kind, subtopic_ids, completed
            FROM timetable_items
            WHERE id = ? AND owner_name = ?
            """,
            (item_id, get_current_person()),
        ).fetchone()
        if row is None or row["completed"]:
            return

        conn.execute(
            """
            UPDATE timetable_items
            SET completed = 1, completed_at = CURRENT_TIMESTAMP
            WHERE id = ? AND owner_name = ?
            """,
            (item_id, get_current_person()),
        )

        if row["session_kind"] != "revision":
            return

        subtopic_ids = json.loads(row["subtopic_ids"] or "[]")
        for subtopic_id in subtopic_ids:
            conn.execute(
                """
                UPDATE subtopics
                SET confidence = MIN(10, confidence + 1)
                WHERE id = ?
                """,
                (subtopic_id,),
            )


def progress_summary() -> dict[str, Any]:
    with connect() as conn:
        remaining_points = conn.execute(
            """
            SELECT COALESCE(SUM(10 - subtopics.confidence), 0) AS value
            FROM subtopics
            JOIN topic_tables ON topic_tables.id = subtopics.table_id
            WHERE topic_tables.owner_name = ?
            """,
            (get_current_person(),),
        ).fetchone()["value"]
        active_tasks = conn.execute(
            """
            SELECT COUNT(*) AS value
            FROM timetable_items
            WHERE owner_name = ? AND completed = 0
            """,
            (get_current_person(),),
        ).fetchone()["value"]
        completed_tasks = conn.execute(
            """
            SELECT COUNT(*) AS value
            FROM timetable_items
            WHERE owner_name = ? AND completed = 1
            """,
            (get_current_person(),),
        ).fetchone()["value"]
        subtopic_count = conn.execute(
            """
            SELECT COUNT(*) AS value
            FROM subtopics
            JOIN topic_tables ON topic_tables.id = subtopics.table_id
            WHERE topic_tables.owner_name = ?
            """,
            (get_current_person(),),
        ).fetchone()["value"]
    return {
        "remaining_points": remaining_points,
        "active_tasks": active_tasks,
        "completed_tasks": completed_tasks,
        "subtopic_count": subtopic_count,
    }
