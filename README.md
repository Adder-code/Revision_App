# Revision App

Minimal SQL-backed Streamlit app for building subjects, tracking subtopic confidence, managing exams, and generating a deterministic revision timetable.

## Run

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

The app creates a local SQLite database file called `revision_app.db` on first run.

## What it does

- Add, edit, and delete subjects
- Add, edit, and delete exams
- Create multiple topic tables per subject
- Track subtopics with confidence scores from `0` to `10`
- Generate a revision timetable over a chosen date range
- Persist completion state and automatically raise confidence when a revision session is completed

## Database

The schema lives in [schema.sql](/Users/gusroberts/dev/revision_app/schema.sql).

- `settings`: stores the planner start and end dates
- `subjects`: the subject list
- `exams`: editable exam timetable entries
- `topic_tables`: named topic tables per subject
- `subtopics`: subtopics and their confidence scores
- `timetable_items`: generated revision and past paper sessions plus completion state

## Timetable rules

- Weekdays generate `5` sessions of `90` minutes
- `3` weekday sessions target the lowest-confidence subtopics
- `1` weekday session is reserved for a past paper
- `1` weekday session is used for balance and coverage
- Weekends generate `2` sessions:
  - `1` lower-confidence session
  - `1` higher-confidence maintenance session
- Completing a revision session increases each included subtopic by exactly `1`
