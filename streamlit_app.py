from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import db
from scheduler import generate_timetable


st.set_page_config(page_title="Revision App", page_icon=":books:", layout="wide")


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        .block-container {max-width: 1200px; padding-top: 1rem; padding-bottom: 2rem;}
        .hero {
            padding: 1.3rem 1.5rem;
            border-radius: 24px;
            background: linear-gradient(135deg, rgba(8,17,31,0.96), rgba(17,29,49,0.92));
            border: 1px solid rgba(255,255,255,0.08);
            margin-bottom: 1rem;
        }
        .hero h1 {margin: 0 0 0.35rem; font-size: 2.4rem;}
        .hero p {margin: 0; color: #b6cae2; max-width: 70ch;}
        .card {
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 22px;
            background: rgba(17,29,49,0.75);
            padding: 1rem 1.1rem;
            margin-bottom: 1rem;
        }
        .metric-card {
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 18px;
            background: rgba(17,29,49,0.75);
            padding: 0.9rem 1rem;
        }
        .metric-label {color: #9fb3cc; font-size: 0.82rem; text-transform: uppercase; letter-spacing: 0.08em;}
        .metric-value {font-size: 1.8rem; font-weight: 700;}
        </style>
        """,
        unsafe_allow_html=True,
    )


def fmt_date(value: str) -> str:
    return datetime.fromisoformat(value).strftime("%d %B %Y")


def next_exam_summary() -> tuple[str, str]:
    exams = db.get_exams()
    today = date.today()
    upcoming = []
    for exam in exams:
        try:
            exam_day = datetime.fromisoformat(exam["exam_date"]).date()
        except ValueError:
            continue
        if exam_day >= today:
            upcoming.append((exam_day, exam["name"], exam.get("subject_name") or "No subject"))
    if not upcoming:
        return "No upcoming exam", "Add an exam timetable entry"
    exam_day, exam_name, subject_name = sorted(upcoming, key=lambda row: row[0])[0]
    days = (exam_day - today).days
    return f"{days} days", f"{subject_name} · {exam_name} · {fmt_date(exam_day.isoformat())}"


def subject_progress_rows() -> list[dict[str, object]]:
    rows = db.get_all_subtopics()
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        grouped.setdefault(row["subject_name"], []).append(row)
    payload = []
    for subject_name, subject_rows in grouped.items():
        confidences = [int(row["confidence"]) for row in subject_rows]
        avg_conf = round(sum(confidences) / len(confidences), 2)
        payload.append(
            {
                "subject": subject_name,
                "subtopics": len(subject_rows),
                "avg_confidence": avg_conf,
                "distance_from_10": round(10 - avg_conf, 2),
                "points_remaining": sum(10 - value for value in confidences),
            }
        )
    return sorted(payload, key=lambda row: row["subject"])


def confidence_progress_frame() -> pd.DataFrame:
    subtopics = db.get_all_subtopics()
    if not subtopics:
        return pd.DataFrame()
    timetable = db.get_timetable(active_only=False)
    current_confidence = {row["id"]: int(row["confidence"]) for row in subtopics}
    subject_map = {row["id"]: row["subject_name"] for row in subtopics}
    subtopic_counts = Counter(row["subject_name"] for row in subtopics)

    completed_revision = sorted(
        [
            row for row in timetable
            if row["completed"] and row["session_kind"] == "revision" and row.get("completed_at")
        ],
        key=lambda row: (row["completed_at"], row["session_index"]),
    )
    active_revision = sorted(
        [
            row for row in timetable
            if (not row["completed"]) and row["session_kind"] == "revision"
        ],
        key=lambda row: (row["session_date"], row["session_index"]),
    )

    completed_counts = Counter()
    for item in completed_revision:
        for subtopic_id in item["subtopic_ids"]:
            completed_counts[subtopic_id] += 1

    baseline_confidence = {
        subtopic_id: max(0, current_confidence[subtopic_id] - completed_counts.get(subtopic_id, 0))
        for subtopic_id in current_confidence
    }

    def add_snapshot(points: list[dict[str, object]], snapshot_date: date, stage: str, state: dict[int, int]) -> None:
        totals: dict[str, int] = Counter()
        for subtopic_id, confidence in state.items():
            totals[subject_map[subtopic_id]] += confidence
        total_count = sum(subtopic_counts.values()) or 1
        for subject_name, total in sorted(totals.items()):
            points.append(
                {
                    "date": snapshot_date,
                    "series": stage,
                    "subject": subject_name,
                    "avg_confidence": total / max(1, subtopic_counts[subject_name]),
                }
            )
        points.append(
            {
                "date": snapshot_date,
                "series": stage,
                "subject": "Overall",
                "avg_confidence": sum(state.values()) / total_count,
            }
        )

    points: list[dict[str, object]] = []
    anchor_date = date.today()
    if completed_revision:
        anchor_date = datetime.fromisoformat(str(completed_revision[0]["completed_at"])).date()
    elif active_revision:
        anchor_date = datetime.fromisoformat(active_revision[0]["session_date"]).date()
    add_snapshot(points, anchor_date, "Actual", baseline_confidence)

    running_actual = dict(baseline_confidence)
    if completed_revision:
        completed_df = pd.DataFrame(completed_revision)
        completed_df["group_date"] = pd.to_datetime(completed_df["completed_at"]).dt.date
        for completed_day, day_rows in completed_df.groupby("group_date"):
            for _, item in day_rows.iterrows():
                for subtopic_id in item["subtopic_ids"]:
                    running_actual[subtopic_id] = min(10, running_actual[subtopic_id] + 1)
            add_snapshot(points, completed_day, "Actual", running_actual)

    if active_revision:
        current_day = date.today()
        add_snapshot(points, current_day, "Projected", current_confidence)
        running_projected = dict(current_confidence)
        active_df = pd.DataFrame(active_revision)
        active_df["group_date"] = pd.to_datetime(active_df["session_date"]).dt.date
        for planned_day, day_rows in active_df.groupby("group_date"):
            for _, item in day_rows.iterrows():
                for subtopic_id in item["subtopic_ids"]:
                    running_projected[subtopic_id] = min(10, running_projected[subtopic_id] + 1)
            add_snapshot(points, planned_day, "Projected", running_projected)

    frame = pd.DataFrame(points).drop_duplicates(subset=["date", "series", "subject"], keep="last")
    return frame.sort_values(["date", "series", "subject"]).reset_index(drop=True)


def projected_table_confidence_frame() -> pd.DataFrame:
    subtopics = db.get_all_subtopics()
    if not subtopics:
        return pd.DataFrame()
    active_items = [
        item for item in db.get_timetable(active_only=False)
        if not item["completed"] and item["session_kind"] == "revision"
    ]
    if not active_items:
        return pd.DataFrame()

    table_label_map = {
        row["id"]: f"{row['subject_name']} · {row['table_title']}"
        for row in subtopics
    }
    table_counts = Counter(table_label_map.values())
    projected = {row["id"]: int(row["confidence"]) for row in subtopics}
    points: list[dict[str, object]] = []

    def add_snapshot(snapshot_date: date) -> None:
        totals: dict[str, int] = Counter()
        for subtopic_id, confidence in projected.items():
            totals[table_label_map[subtopic_id]] += confidence
        for table_label, total in sorted(totals.items()):
            points.append(
                {
                    "date": snapshot_date,
                    "table": table_label,
                    "avg_confidence": total / max(1, table_counts[table_label]),
                }
            )

    add_snapshot(date.today())
    active_df = pd.DataFrame(active_items)
    active_df["group_date"] = pd.to_datetime(active_df["session_date"]).dt.date
    for planned_day, day_rows in active_df.groupby("group_date"):
        for _, item in day_rows.iterrows():
            for subtopic_id in item["subtopic_ids"]:
                projected[subtopic_id] = min(10, projected[subtopic_id] + 1)
        add_snapshot(planned_day)

    return (
        pd.DataFrame(points)
        .drop_duplicates(subset=["date", "table"], keep="last")
        .sort_values(["date", "table"])
    )


def projected_confidence_frame() -> pd.DataFrame:
    subtopics = db.get_all_subtopics()
    if not subtopics:
        return pd.DataFrame()
    active_items = [
        item for item in db.get_timetable(active_only=False)
        if not item["completed"] and item["session_kind"] == "revision"
    ]
    if not active_items:
        return pd.DataFrame()

    subject_map = {row["id"]: row["subject_name"] for row in subtopics}
    subject_counts = Counter(row["subject_name"] for row in subtopics)
    projected = {row["id"]: int(row["confidence"]) for row in subtopics}

    points: list[dict[str, object]] = []

    def add_snapshot(snapshot_date: date) -> None:
        totals: dict[str, int] = Counter()
        for subtopic_id, confidence in projected.items():
            totals[subject_map[subtopic_id]] += confidence
        for subject_name, total in sorted(totals.items()):
            points.append(
                {
                    "date": snapshot_date,
                    "subject": subject_name,
                    "avg_confidence": total / max(1, subject_counts[subject_name]),
                }
            )

    today = date.today()
    add_snapshot(today)
    active_df = pd.DataFrame(active_items)
    active_df["group_date"] = pd.to_datetime(active_df["session_date"]).dt.date
    for planned_day, day_rows in active_df.groupby("group_date"):
        for _, item in day_rows.iterrows():
            for subtopic_id in item["subtopic_ids"]:
                projected[subtopic_id] = min(10, projected[subtopic_id] + 1)
        add_snapshot(planned_day)

    return pd.DataFrame(points).drop_duplicates(subset=["date", "subject"], keep="last").sort_values(["date", "subject"])


def subject_track_status_frame() -> pd.DataFrame:
    subtopics = db.get_all_subtopics()
    exams = db.get_exams()
    if not subtopics or not exams:
        return pd.DataFrame()
    projected = {row["id"]: int(row["confidence"]) for row in subtopics}
    active_items = sorted(
        [
            item for item in db.get_timetable(active_only=False)
            if not item["completed"] and item["session_kind"] == "revision"
        ],
        key=lambda item: (item["session_date"], item["session_index"]),
    )
    for item in active_items:
        for subtopic_id in item["subtopic_ids"]:
            projected[subtopic_id] = min(10, projected[subtopic_id] + 1)

    rows = []
    by_subject = {}
    for row in subtopics:
        by_subject.setdefault(row["subject_id"], []).append(row)

    for exam in exams:
        subject_id = exam.get("subject_id")
        if subject_id is None:
            continue
        linked_ids = set(exam.get("linked_subtopic_ids", []))
        relevant = [row for row in by_subject.get(subject_id, []) if (row["id"] in linked_ids)] if linked_ids else by_subject.get(subject_id, [])
        if not relevant:
            continue
        projected_avg = sum(projected[row["id"]] for row in relevant) / len(relevant)
        rows.append(
            {
                "exam_name": exam["name"],
                "subject": exam.get("subject_name") or "Unassigned",
                "target_date": fmt_date((datetime.fromisoformat(exam["exam_date"]).date() - timedelta(days=7)).isoformat()),
                "projected_avg_confidence": round(projected_avg, 2),
                "on_track": "Yes" if projected_avg >= 10 else "No",
            }
        )
    return pd.DataFrame(rows)


def past_paper_frame() -> pd.DataFrame:
    items = db.get_timetable(active_only=False)
    rows = [
        {
            "subject": item["subject_name"],
            "date": datetime.fromisoformat(item["session_date"]).date(),
        }
        for item in items
        if item["session_kind"] == "past_paper"
    ]
    return pd.DataFrame(rows)


def exam_timeline_frame() -> pd.DataFrame:
    exams = db.get_exams()
    rows = []
    for exam in exams:
        raw_date = str(exam.get("exam_date", "")).strip()
        if not raw_date:
            continue
        exam_day = datetime.fromisoformat(raw_date)
        rows.append(
            {
                "subject": exam.get("subject_name") or "Unassigned",
                "exam_name": exam["name"],
                "date": exam_day,
                "display_date": fmt_date(raw_date),
                "countdown_days": max((exam_day.date() - date.today()).days, 0),
            }
        )
    return pd.DataFrame(rows).sort_values("date") if rows else pd.DataFrame()


def session_blocks_figure() -> go.Figure | None:
    items = db.get_timetable(active_only=False)
    if not items:
        return None

    ordered_items = sorted(items, key=lambda item: (item["session_date"], item["session_index"]))
    dates = sorted({item["session_date"] for item in ordered_items})
    max_session = max(item["session_index"] for item in ordered_items)
    session_labels = [f"Session {index}" for index in range(max_session, 0, -1)]
    session_to_row = {label: idx for idx, label in enumerate(session_labels)}

    subject_names = sorted({item["subject_name"] for item in ordered_items})
    palette = [
        "#4FD1C5",
        "#F6B73C",
        "#F472B6",
        "#7AA2FF",
        "#7DD3FC",
        "#A3E635",
        "#FB7185",
        "#C084FC",
    ]
    subject_color = {name: palette[idx % len(palette)] for idx, name in enumerate(subject_names)}
    subject_value = {name: idx + 1 for idx, name in enumerate(subject_names)}

    z = [[0 for _ in dates] for _ in session_labels]
    text = [["" for _ in dates] for _ in session_labels]
    custom = [[["", "", "", "", ""] for _ in dates] for _ in session_labels]

    date_to_col = {value: idx for idx, value in enumerate(dates)}
    for item in ordered_items:
        row_idx = session_to_row[f"Session {item['session_index']}"]
        col_idx = date_to_col[item["session_date"]]
        z[row_idx][col_idx] = subject_value[item["subject_name"]]
        text[row_idx][col_idx] = "P" if item["session_kind"] == "past_paper" else ""
        custom[row_idx][col_idx] = [
            fmt_date(item["session_date"]),
            item["subject_name"],
            item["title"],
            "Past paper" if item["session_kind"] == "past_paper" else "Revision",
            item["details"],
        ]

    colorscale = [(0.0, "#0F172A"), (0.000001, "#0F172A")]
    if subject_names:
        step = 1 / max(len(subject_names), 1)
        for idx, name in enumerate(subject_names, start=1):
            start = (idx - 1) * step
            end = idx * step
            color = subject_color[name]
            colorscale.append((start, color))
            colorscale.append((end, color))

    fig = go.Figure(
        data=go.Heatmap(
            z=z,
            x=[fmt_date(value) for value in dates],
            y=session_labels,
            text=text,
            texttemplate="%{text}",
            textfont={"color": "white", "size": 12},
            customdata=custom,
            colorscale=colorscale,
            zmin=0,
            zmax=max(len(subject_names), 1),
            showscale=False,
            xgap=3,
            ygap=3,
            hovertemplate="<b>%{customdata[0]}</b><br>%{y}<br>%{customdata[1]}<br>%{customdata[2]}<br>%{customdata[3]}<br>%{customdata[4]}<extra></extra>",
        )
    )
    fig.update_layout(
        title="Daily Session Blocks",
        height=max(320, 90 + (max_session * 70)),
        margin=dict(t=50, b=20, l=10, r=10),
        xaxis_title="Date",
        yaxis_title="",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_yaxes(autorange="reversed")
    return fig


def render_metrics() -> None:
    summary = db.progress_summary()
    cols = st.columns(4)
    next_exam_value, next_exam_note = next_exam_summary()
    payload = [
        ("Confidence points left", summary["remaining_points"]),
        ("Active sessions", summary["active_tasks"]),
        ("Completed sessions", summary["completed_tasks"]),
        ("Next exam", next_exam_value),
    ]
    notes = ["Points needed to reach confidence 10", "Unticked timetable items", "Completed revision and past paper sessions", next_exam_note]
    for col, (label, value), note in zip(cols, payload, notes):
        with col:
            st.markdown(
                f'<div class="metric-card"><div class="metric-label">{label}</div><div class="metric-value">{value}</div><div style="color:#b6cae2;font-size:0.9rem;">{note}</div></div>',
                unsafe_allow_html=True,
            )


def render_storage_status() -> None:
    summary = db.progress_summary()
    storage_label = "Supabase Postgres" if db._database_url() else "Local SQLite"
    with st.sidebar:
        st.divider()
        st.subheader("Storage")
        st.caption(f"The app auto-loads from `{storage_label}` on startup.")
        st.caption(f"Current person: `{db.get_current_person()}`")
        if db._database_url():
            st.caption("Database: hosted and persistent")
        else:
            st.caption("Database: `revision_app.db`")
        st.caption(
            f"{summary['subtopic_count']} subtopics · {summary['active_tasks']} active sessions · {summary['completed_tasks']} completed sessions"
        )
        if st.button("Reload from database", use_container_width=True):
            st.rerun()


def person_controls() -> None:
    people = db.get_people()
    if not people:
        people = [db.create_person("Gus")]

    current_person = st.session_state.get("current_person", db.get_current_person())
    if current_person not in people:
        current_person = "Gus" if "Gus" in people else people[0]
    db.set_current_person(current_person)

    with st.sidebar:
        st.subheader("Person")
        selected_person = st.selectbox(
            "Open plan for",
            options=people,
            index=people.index(db.get_current_person()),
        )
        if selected_person != db.get_current_person():
            st.session_state["current_person"] = selected_person
            db.set_current_person(selected_person)
            st.rerun()

        new_person = st.text_input(
            "Add person",
            placeholder="e.g. Alice",
            key="new-person-name",
        )
        if st.button("Create person", use_container_width=True):
            created_person = db.create_person(new_person)
            st.session_state["current_person"] = created_person
            db.set_current_person(created_person)
            st.rerun()


def planner_controls() -> tuple[str, str]:
    planner_range = db.get_planner_range()
    with st.sidebar:
        st.subheader("Timetable Range")
        start_date = st.date_input(
            "Start date",
            value=datetime.fromisoformat(planner_range["start_date"]).date(),
        )
        end_date = st.date_input(
            "End date",
            value=datetime.fromisoformat(planner_range["end_date"]).date(),
        )
        if st.button("Save range", use_container_width=True):
            db.save_planner_range(start_date.isoformat(), end_date.isoformat())
            st.success("Date range saved.")
            st.rerun()
    return start_date.isoformat(), end_date.isoformat()


def render_subjects() -> None:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Subjects")
    subject_df = pd.DataFrame(db.get_subjects(), columns=["id", "name"])
    edited = st.data_editor(
        subject_df,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        key="subjects-editor",
        column_config={
            "id": None,
            "name": st.column_config.TextColumn("Subject"),
        },
    )
    if st.button("Save subjects"):
        db.save_subjects(edited.to_dict("records"))
        st.success("Subjects updated.")
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


def render_exams() -> None:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Exam Timetable")
    subjects = db.get_subjects()
    subject_names = [row["name"] for row in subjects]
    subject_id_lookup = {row["name"]: row["id"] for row in subjects}
    exam_rows = db.get_exams()
    exam_df = pd.DataFrame(exam_rows, columns=["id", "name", "subject_name", "exam_date", "notes", "linked_topics"])
    if exam_df.empty:
        exam_df = pd.DataFrame(columns=["id", "name", "subject_name", "exam_date", "notes", "linked_topics"])
    if not exam_df.empty:
        exam_df["exam_date"] = pd.to_datetime(exam_df["exam_date"], errors="coerce").dt.date
    edited = st.data_editor(
        exam_df,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        key="exams-editor",
        column_config={
            "id": None,
            "name": st.column_config.TextColumn("Exam name"),
            "subject_name": st.column_config.SelectboxColumn("Subject", options=[""] + subject_names),
            "exam_date": st.column_config.DateColumn("Date", format="DD MMMM YYYY"),
            "notes": st.column_config.TextColumn("Notes"),
            "linked_topics": st.column_config.TextColumn("Linked topics", disabled=True),
        },
    )
    if st.button("Save exams"):
        rows = edited.to_dict("records")
        for row in rows:
            if isinstance(row.get("exam_date"), date):
                row["exam_date"] = row["exam_date"].isoformat()
        db.save_exams(rows)
        st.success("Exams updated.")
        st.rerun()
    existing_exams = [row for row in db.get_exams() if row.get("id")]
    if existing_exams:
        st.caption("Link each saved exam to the subtopics it actually covers. The timetable generator will prefer those topics as the exam gets closer.")
    for exam in existing_exams:
        subject_id = exam.get("subject_id") or subject_id_lookup.get(exam.get("subject_name", ""))
        options = db.get_subtopic_options(subject_id)
        option_labels = {
            row["id"]: f"{row['table_title']} · {row['subtopic_name']}"
            for row in options
        }
        with st.expander(f"{exam['name']} · {exam.get('subject_name') or 'No subject'} · {fmt_date(exam['exam_date'])}", expanded=False):
            if not options:
                st.info("No subtopics available for this exam's subject yet.")
                continue
            selected = st.multiselect(
                "Linked subtopics",
                options=[row["id"] for row in options],
                default=[subtopic_id for subtopic_id in exam.get("linked_subtopic_ids", []) if subtopic_id in option_labels],
                format_func=lambda subtopic_id: option_labels[subtopic_id],
                key=f"exam-links-{exam['id']}",
                placeholder="Choose the subtopics covered by this exam",
            )
            if st.button("Save linked subtopics", key=f"save-exam-links-{exam['id']}"):
                db.save_exam_links(int(exam["id"]), selected)
                st.success("Linked subtopics updated.")
                st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


def render_topic_tables() -> None:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Subject Topic Tables")
    subjects = db.get_subjects()
    tables = db.get_topic_tables()
    if not subjects:
        st.info("Add at least one subject before creating topic tables.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    tabs = st.tabs([row["name"] for row in subjects])
    for tab, subject in zip(tabs, subjects):
        with tab:
            col1, col2 = st.columns([2.2, 1])
            with col1:
                new_title = st.text_input(
                    f"New table title for {subject['name']}",
                    placeholder="e.g. Pure, CP1, Paper 2",
                    key=f"new-table-{subject['id']}",
                )
            with col2:
                st.write("")
                if st.button(f"Add table to {subject['name']}", key=f"add-table-{subject['id']}", use_container_width=True):
                    db.create_topic_table(subject["id"], new_title)
                    st.rerun()

            subject_tables = [row for row in tables if row["subject_id"] == subject["id"]]
            if not subject_tables:
                st.info("No topic tables yet for this subject.")
                continue

            for table in subject_tables:
                with st.expander(table["title"], expanded=True):
                    title_col, delete_col = st.columns([2.4, 1])
                    with title_col:
                        updated_title = st.text_input(
                            "Table title",
                            value=table["title"],
                            key=f"title-{table['id']}",
                        )
                    with delete_col:
                        st.write("")
                        if st.button("Delete table", key=f"delete-table-{table['id']}", use_container_width=True):
                            db.delete_topic_table(table["id"])
                            st.rerun()
                    if st.button("Rename table", key=f"rename-table-{table['id']}"):
                        db.rename_topic_table(table["id"], updated_title)
                        st.rerun()

                    rows = db.get_subtopics_for_table(table["id"])
                    subtopic_df = pd.DataFrame(rows, columns=["id", "subtopic", "confidence"])
                    edited = st.data_editor(
                        subtopic_df,
                        use_container_width=True,
                        hide_index=True,
                        num_rows="dynamic",
                        key=f"table-editor-{table['id']}",
                        column_config={
                            "id": None,
                            "subtopic": st.column_config.TextColumn("Subtopic"),
                            "confidence": st.column_config.NumberColumn("Confidence", min_value=0, max_value=10, step=1),
                        },
                    )
                    if st.button("Save subtopics", key=f"save-subtopics-{table['id']}"):
                        db.save_subtopics(table["id"], edited.to_dict("records"))
                        st.success("Subtopics saved.")
                        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


def render_generation(start_date: str, end_date: str) -> None:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Generate Timetable")
    st.caption(
        "Weekdays use 5 sessions of 90 minutes with 3 low-confidence sessions, 1 past paper, and 1 balancing session. Weekends use 2 sessions: one lower-confidence and one higher-confidence."
    )
    if st.button("Generate or refresh timetable", use_container_width=True):
        subjects = db.get_subjects()
        exams = db.get_exams()
        subtopics = db.get_all_subtopics()
        items, summary = generate_timetable(start_date, end_date, subjects, exams, subtopics)
        db.save_planner_range(start_date, end_date)
        db.replace_timetable(items)
        if summary["completed_within_range"]:
            st.success(f"Timetable generated. All tracked subtopics can reach confidence 10 within this range in {summary['scheduled_sessions']} sessions.")
        else:
            st.warning(
                f"Timetable generated with {summary['scheduled_sessions']} sessions, but {summary['remaining_points']} confidence points still remain after the end date."
            )
        st.rerun()
    if st.button("Clear timetable", use_container_width=True):
        db.clear_timetable()
        st.success("Timetable cleared.")
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


def render_active_tasks() -> None:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Active Tasks")
    tasks = db.get_timetable(active_only=True)
    if not tasks:
        st.info("No active sessions. Generate a timetable or complete remaining tasks.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    grouped: dict[str, list[dict[str, object]]] = {}
    for task in tasks:
        grouped.setdefault(task["session_date"], []).append(task)

    for task_date, day_rows in grouped.items():
        st.markdown(f"**{fmt_date(task_date)}**")
        for task in day_rows:
            label = (
                f"{task['session_label']} · {task['subject_name']} · {task['title']} "
                f"({task['duration_minutes']} min)"
            )
            if task["details"]:
                label += f" - {task['details']}"
            checked = st.checkbox(label, key=f"complete-{task['id']}")
            if checked:
                db.complete_timetable_item(task["id"])
                st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


def render_timetable_overview() -> None:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Full Timetable")
    items = db.get_timetable(active_only=False)
    if not items:
        st.info("No timetable generated yet.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    rows = []
    for item in items:
        rows.append(
            {
                "Date": fmt_date(item["session_date"]),
                "Session": item["session_label"],
                "Type": "Past paper" if item["session_kind"] == "past_paper" else "Revision",
                "Subject": item["subject_name"],
                "Task": item["title"],
                "Details": item["details"],
                "Done": "Yes" if item["completed"] else "No",
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.markdown("</div>", unsafe_allow_html=True)


def render_progress_table() -> None:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Progress Summary")
    rows = db.get_all_subtopics()
    if not rows:
        st.info("No subtopics tracked yet.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    summary_rows = []
    grouped = {}
    for row in rows:
        grouped.setdefault(row["subject_name"], []).append(row)
    for subject_name, subject_rows in grouped.items():
        confidences = [row["confidence"] for row in subject_rows]
        summary_rows.append(
            {
                "Subject": subject_name,
                "Subtopics": len(subject_rows),
                "Average confidence": round(sum(confidences) / len(confidences), 1),
                "Points remaining": sum(10 - value for value in confidences),
            }
        )
    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)
    st.markdown("</div>", unsafe_allow_html=True)


def render_analytics() -> None:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Progress Visuals")
    progress_rows = subject_progress_rows()
    if not progress_rows:
        st.info("Add some subtopics to unlock progress graphs.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    progress_df = pd.DataFrame(progress_rows)
    table_projected_df = projected_table_confidence_frame()
    past_df = past_paper_frame()
    projected_df = projected_confidence_frame()
    track_df = subject_track_status_frame()
    exam_df = exam_timeline_frame()
    session_blocks_fig = session_blocks_figure()
    weak_rows = db.get_all_subtopics()
    weak_df = pd.DataFrame(weak_rows)
    weak_df["distance_to_10"] = 10 - weak_df["confidence"]
    weak_df = weak_df.sort_values(["distance_to_10", "confidence"], ascending=[False, True]).head(12)

    row1a, row1b = st.columns(2)
    with row1a:
        if not table_projected_df.empty:
            fig = px.line(
                table_projected_df,
                x="date",
                y="avg_confidence",
                color="table",
                markers=True,
                title="Average Table Projected Confidence Over Time",
                range_y=[0, 10],
            )
            fig.update_layout(height=360, margin=dict(t=50, b=10, l=10, r=10))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Generate a timetable to see projected confidence by table.")
    with row1b:
        fig = px.bar(
            progress_df,
            x="subject",
            y=["avg_confidence", "distance_from_10"],
            barmode="group",
            title="Current Confidence vs Distance From 10",
        )
        fig.update_layout(height=360, margin=dict(t=50, b=10, l=10, r=10), yaxis_title="Score")
        st.plotly_chart(fig, use_container_width=True)

    row2a, row2b = st.columns(2)
    with row2a:
        fig = px.bar(
            weak_df,
            x="distance_to_10",
            y="subtopic",
            color="subject_name",
            orientation="h",
            title="Weakest Areas Still Needing Work",
        )
        fig.update_layout(height=380, margin=dict(t=50, b=10, l=10, r=10), yaxis_title="")
        st.plotly_chart(fig, use_container_width=True)
    with row2b:
        if past_df.empty:
            st.info("Generate a timetable to see past paper allocation.")
        else:
            fig = px.bar(
                past_df.groupby("subject", as_index=False).size(),
                x="subject",
                y="size",
                title="Past Paper Sessions by Subject",
            )
            fig.update_layout(height=380, margin=dict(t=50, b=10, l=10, r=10), yaxis_title="Sessions")
            st.plotly_chart(fig, use_container_width=True)

    st.write("")
    if projected_df.empty:
        st.info("Generate a timetable to see projected confidence over time.")
    else:
        fig = px.line(
            projected_df,
            x="date",
            y="avg_confidence",
            color="subject",
            markers=True,
            title="Projected Confidence Over Time",
            range_y=[0, 10],
        )
        fig.update_layout(height=420, margin=dict(t=50, b=10, l=10, r=10), xaxis_title="Date", yaxis_title="Average confidence")
        st.plotly_chart(fig, use_container_width=True)

    if not track_df.empty:
        st.dataframe(track_df, use_container_width=True, hide_index=True)

    if session_blocks_fig is None:
        st.info("Generate a timetable to see the daily session blocks.")
    else:
        st.plotly_chart(session_blocks_fig, use_container_width=True)

    if not past_df.empty:
        past_by_day = past_df.groupby(["date", "subject"], as_index=False).size()
        fig = px.area(
            past_by_day,
            x="date",
            y="size",
            color="subject",
            title="Past Paper Allocation Over Time",
        )
        fig.update_layout(height=340, margin=dict(t=50, b=10, l=10, r=10), yaxis_title="Past paper sessions")
        st.plotly_chart(fig, use_container_width=True)

    if exam_df.empty:
        st.info("Add exams to see the exam timeline.")
    else:
        fig = px.scatter(
            exam_df,
            x="date",
            y="subject",
            color="subject",
            size="countdown_days",
            hover_name="exam_name",
            hover_data={"display_date": True, "countdown_days": True, "date": False, "subject": False},
            title="Exam Timeline",
        )
        fig.update_traces(marker=dict(line=dict(width=1, color="rgba(255,255,255,0.35)"), sizemin=10))
        fig.update_layout(height=340, margin=dict(t=50, b=10, l=10, r=10), xaxis_title="Exam date", yaxis_title="")
        st.plotly_chart(fig, use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)


def main() -> None:
    db.init_db()
    inject_styles()
    person_controls()
    start_date, end_date = planner_controls()
    render_storage_status()

    st.markdown(
        """
        <div class="hero">
          <h1>Revision App</h1>
          <p>Build your subjects, define subtopics, add exams, and generate a deterministic timetable focused on lifting every subtopic to confidence 10.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    render_metrics()
    with st.expander("Generate Timetable", expanded=True):
        render_generation(start_date, end_date)
    with st.expander("Subjects", expanded=False):
        render_subjects()
    with st.expander("Exam Timetable", expanded=True):
        render_exams()
    with st.expander("Topic Tables", expanded=True):
        render_topic_tables()
    with st.expander("Active Tasks", expanded=True):
        render_active_tasks()
    with st.expander("Full Timetable", expanded=False):
        render_timetable_overview()
    with st.expander("Progress Summary", expanded=False):
        render_progress_table()
    with st.expander("Progress Visuals", expanded=False):
        render_analytics()


if __name__ == "__main__":
    main()
