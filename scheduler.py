from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
from math import exp
from typing import Any


SESSION_MINUTES = 90
WEEKDAY_PLAN = [
    ("Session 1", "low"),
    ("Session 2", "low"),
    ("Session 3", "low"),
    ("Session 4", "past_paper"),
    ("Session 5", "balance"),
]
WEEKEND_PLAN = [
    ("Session 1", "weekend_low"),
    ("Session 2", "weekend_high"),
    ("Session 3", "balance"),
]
EXAM_DAY_PLAN = [
    ("Session 1", "low"),
    ("Session 2", "past_paper"),
    ("Session 3", "balance"),
]
FINAL_WEEKDAY_PLAN = [
    ("Session 1", "low"),
    ("Session 2", "past_paper"),
    ("Session 3", "past_paper"),
    ("Session 4", "past_paper"),
    ("Session 5", "balance"),
]
FINAL_WEEKEND_PLAN = [
    ("Session 1", "low"),
    ("Session 2", "past_paper"),
    ("Session 3", "balance"),
]
PAST_PAPER_ONLY_WEEKDAY_PLAN = [
    ("Session 1", "past_paper"),
    ("Session 2", "past_paper"),
    ("Session 3", "past_paper"),
    ("Session 4", "past_paper"),
    ("Session 5", "past_paper"),
]
PAST_PAPER_ONLY_WEEKEND_PLAN = [
    ("Session 1", "past_paper"),
    ("Session 2", "past_paper"),
    ("Session 3", "past_paper"),
]


def _parse_day(value: str) -> date:
    return datetime.fromisoformat(value).date()


def _exam_schedule_map(subjects: list[dict[str, Any]], exams: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    lookup: dict[int, list[dict[str, Any]]] = {}
    for subject in subjects:
        matching = []
        for exam in exams:
            if exam.get("subject_id") != subject["id"]:
                continue
            raw_date = str(exam.get("exam_date", "")).strip()
            if not raw_date:
                continue
            matching.append(
                {
                    "exam_day": _parse_day(raw_date),
                    "exam_name": str(exam.get("name", "")).strip() or subject["name"],
                    "linked_subtopic_ids": set(exam.get("linked_subtopic_ids", [])),
                }
            )
        lookup[subject["id"]] = sorted(matching, key=lambda row: row["exam_day"])
    return lookup


def _subtopic_exam_days(exams: list[dict[str, Any]]) -> dict[int, list[date]]:
    lookup: dict[int, list[date]] = {}
    for exam in exams:
        raw_date = str(exam.get("exam_date", "")).strip()
        if not raw_date:
            continue
        exam_day = _parse_day(raw_date)
        for subtopic_id in exam.get("linked_subtopic_ids", []) or []:
            lookup.setdefault(int(subtopic_id), []).append(exam_day)
    for subtopic_id, days in lookup.items():
        lookup[subtopic_id] = sorted(days)
    return lookup


def _subtopic_target_days(exams: list[dict[str, Any]]) -> dict[int, list[date]]:
    lookup: dict[int, list[date]] = {}
    for exam in exams:
        raw_date = str(exam.get("exam_date", "")).strip()
        if not raw_date:
            continue
        target_day = _parse_day(raw_date) - timedelta(days=5)
        for subtopic_id in exam.get("linked_subtopic_ids", []) or []:
            lookup.setdefault(int(subtopic_id), []).append(target_day)
    for subtopic_id, days in lookup.items():
        lookup[subtopic_id] = sorted(days)
    return lookup


def _next_exam(subject_id: int, current_day: date, exam_schedule: dict[int, list[dict[str, Any]]]) -> dict[str, Any] | None:
    exams = exam_schedule.get(subject_id, [])
    if not exams:
        return None
    for exam in exams:
        if exam["exam_day"] >= current_day:
            return exam
    return exams[-1]


def _final_exam_day(subject_id: int, exam_schedule: dict[int, list[dict[str, Any]]]) -> date | None:
    exams = exam_schedule.get(subject_id, [])
    if not exams:
        return None
    return exams[-1]["exam_day"]


def _exam_weight(days_until_exam: int | None) -> float:
    if days_until_exam is None:
        return 1.0
    days = max(days_until_exam, 0)
    medium_term = 1 / (1 + days / 21)
    short_term = 1 / (1 + days / 7)
    immediate_term = exp(-days / 5)
    return 1.0 + (0.22 * medium_term) + (0.16 * short_term) + (0.08 * immediate_term)


def _past_paper_weight(days_until_exam: int | None) -> float:
    if days_until_exam is None:
        return 1.0
    days = max(days_until_exam, 0)
    medium_term = 1 / (1 + days / 18)
    short_term = 1 / (1 + days / 7)
    immediate_term = exp(-days / 4)
    return 1.0 + (0.25 * medium_term) + (0.28 * short_term) + (0.14 * immediate_term)


def _subject_exam_state(
    subject_id: int,
    current_day: date,
    exam_schedule: dict[int, list[dict[str, Any]]],
) -> dict[str, Any]:
    exam = _next_exam(subject_id, current_day, exam_schedule)
    if exam is None:
        return {
            "exam_day": None,
            "exam_name": "",
            "days_until_exam": None,
            "exam_weight": 1.0,
            "past_paper_weight": 1.0,
            "linked_subtopic_ids": set(),
        }
    days_until_exam = max((exam["exam_day"] - current_day).days, 0)
    target_day = exam["exam_day"] - timedelta(days=5)
    days_to_target = (target_day - current_day).days
    return {
        "exam_day": exam["exam_day"],
        "exam_name": exam["exam_name"],
        "days_until_exam": days_until_exam,
        "target_day": target_day,
        "days_to_target": days_to_target,
        "exam_weight": _exam_weight(days_until_exam),
        "past_paper_weight": _past_paper_weight(days_until_exam),
        "linked_subtopic_ids": set(exam.get("linked_subtopic_ids", set())),
        "final_week": days_until_exam <= 7,
    }


def _linked_gap_for_subject(
    subject_id: int,
    exam_state: dict[str, Any],
    subtopics: list[dict[str, Any]],
) -> int:
    linked_ids = exam_state.get("linked_subtopic_ids", set())
    if linked_ids:
        return sum(
            max(0, 10 - int(row["confidence"]))
            for row in subtopics
            if row["subject_id"] == subject_id and row["id"] in linked_ids
        )
    return sum(
        max(0, 10 - int(row["confidence"]))
        for row in subtopics
        if row["subject_id"] == subject_id
    )


def _target_pressure(exam_state: dict[str, Any], linked_gap: int) -> float:
    if linked_gap <= 0:
        return 0.0
    days_to_target = exam_state.get("days_to_target")
    if days_to_target is None:
        return 0.0
    if days_to_target < 0:
        return 2.0
    return linked_gap / max(days_to_target + 1, 1)


def _subject_has_exam_on_day(subject_id: int, current_day: date, exam_schedule: dict[int, list[dict[str, Any]]]) -> bool:
    return any(exam["exam_day"] == current_day for exam in exam_schedule.get(subject_id, []))


def _revision_capacity_modes_for_day(
    current_day: date,
    subjects: list[dict[str, Any]],
    exam_schedule: dict[int, list[dict[str, Any]]],
) -> list[tuple[str, str]]:
    if any(
        exam["exam_day"] == current_day
        for subject in subjects
        for exam in exam_schedule.get(subject["id"], [])
    ):
        return EXAM_DAY_PLAN
    if any(_subject_exam_state(subject["id"], current_day, exam_schedule)["final_week"] for subject in subjects):
        return FINAL_WEEKDAY_PLAN if current_day.weekday() < 5 else FINAL_WEEKEND_PLAN
    return WEEKDAY_PLAN if current_day.weekday() < 5 else WEEKEND_PLAN


def _available_revision_slots_before_target(
    subject_id: int,
    current_day: date,
    target_day: date | None,
    subjects: list[dict[str, Any]],
    exam_schedule: dict[int, list[dict[str, Any]]],
) -> int:
    if target_day is None or target_day < current_day:
        return 0
    final_exam_day = _final_exam_day(subject_id, exam_schedule)
    if final_exam_day is None:
        return 0
    end_day = min(target_day, final_exam_day)
    slots = 0
    day = current_day
    while day <= end_day:
        if _subject_has_exam_on_day(subject_id, day, exam_schedule):
            day += timedelta(days=1)
            continue
        modes = _revision_capacity_modes_for_day(day, subjects, exam_schedule)
        slots += sum(1 for _, mode in modes if mode != "past_paper")
        day += timedelta(days=1)
    return slots


def _reservation_pressure(
    subject_id: int,
    current_day: date,
    exam_state: dict[str, Any],
    linked_gap: int,
    subjects: list[dict[str, Any]],
    exam_schedule: dict[int, list[dict[str, Any]]],
) -> float:
    if linked_gap <= 0 or not exam_state.get("linked_subtopic_ids"):
        return 0.0
    available_slots = _available_revision_slots_before_target(
        subject_id,
        current_day,
        exam_state.get("target_day"),
        subjects,
        exam_schedule,
    )
    if available_slots <= 0:
        return 3.0
    return linked_gap / available_slots


def _critical_linked_ids(
    current_day: date,
    subjects: list[dict[str, Any]],
    subtopics: list[dict[str, Any]],
    exam_schedule: dict[int, list[dict[str, Any]]],
) -> set[int]:
    critical_ids: set[int] = set()
    for subject in subjects:
        exam_state = _subject_exam_state(subject["id"], current_day, exam_schedule)
        linked_ids = exam_state.get("linked_subtopic_ids", set())
        if not linked_ids:
            continue
        linked_gap = _linked_gap_for_subject(subject["id"], exam_state, subtopics)
        if linked_gap <= 0:
            continue
        pressure = _target_pressure(exam_state, linked_gap)
        reservation = _reservation_pressure(subject["id"], current_day, exam_state, linked_gap, subjects, exam_schedule)
        if exam_state.get("days_to_target", 9999) <= 0 or reservation >= 0.78 or pressure >= 0.7:
            critical_ids.update(linked_ids)
    return critical_ids


def _daily_plan(
    current_day: date,
    subjects: list[dict[str, Any]],
    subtopics: list[dict[str, Any]],
    exam_schedule: dict[int, list[dict[str, Any]]],
) -> list[tuple[str, str]]:
    if any(
        exam["exam_day"] == current_day
        for subject in subjects
        for exam in exam_schedule.get(subject["id"], [])
    ):
        return EXAM_DAY_PLAN
    overall_gap = sum(max(0, 10 - int(row["confidence"])) for row in subtopics)
    has_future_exam = any(_next_exam(subject["id"], current_day, exam_schedule) is not None for subject in subjects)
    if overall_gap == 0 and has_future_exam:
        return PAST_PAPER_ONLY_WEEKDAY_PLAN if current_day.weekday() < 5 else PAST_PAPER_ONLY_WEEKEND_PLAN

    if any(_subject_exam_state(subject["id"], current_day, exam_schedule)["final_week"] for subject in subjects):
        return FINAL_WEEKDAY_PLAN if current_day.weekday() < 5 else FINAL_WEEKEND_PLAN

    return WEEKDAY_PLAN if current_day.weekday() < 5 else WEEKEND_PLAN


def _exam_day_blocks(
    current_day: date,
    subjects: list[dict[str, Any]],
    subtopics: list[dict[str, Any]],
    exam_schedule: dict[int, list[dict[str, Any]]],
) -> tuple[set[int], set[int]]:
    blocked_subject_ids: set[int] = set()
    blocked_subtopic_ids: set[int] = set()
    subject_subtopics: dict[int, list[int]] = {}
    for row in subtopics:
        subject_subtopics.setdefault(row["subject_id"], []).append(row["id"])

    for subject in subjects:
        subject_id = subject["id"]
        for exam in exam_schedule.get(subject_id, []):
            if exam["exam_day"] != current_day:
                continue
            blocked_subject_ids.add(subject_id)
            linked_ids = set(exam.get("linked_subtopic_ids", set()))
            if linked_ids:
                blocked_subtopic_ids.update(linked_ids)
            else:
                blocked_subtopic_ids.update(subject_subtopics.get(subject_id, []))
    return blocked_subject_ids, blocked_subtopic_ids


def _subject_need_map(subtopics: list[dict[str, Any]]) -> dict[int, int]:
    subject_need: dict[int, int] = Counter()
    for row in subtopics:
        subject_need[row["subject_id"]] += max(0, 10 - int(row["confidence"]))
    return subject_need


def _subject_balance_ratio(subject_id: int, assigned_counts: Counter, need_map: dict[int, int]) -> float:
    outstanding = max(1, need_map.get(subject_id, 0))
    return assigned_counts[subject_id] / outstanding


def _pending_rows(
    projected: dict[int, int],
    subtopics: list[dict[str, Any]],
    minimum_gap: int = 1,
) -> list[dict[str, Any]]:
    rows = []
    for row in subtopics:
        current = projected[row["id"]]
        gap = 10 - current
        if gap < minimum_gap:
            continue
        rows.append({**row, "projected_confidence": current, "gap": gap})
    return rows


def _has_future_linked_exam(subtopic_id: int, current_day: date, subtopic_exam_days: dict[int, list[date]]) -> bool:
    exam_days = subtopic_exam_days.get(subtopic_id, [])
    if not exam_days:
        return True
    return any(exam_day >= current_day for exam_day in exam_days)


def _same_slot_repeat_penalty(
    current_day: date,
    session_index: int,
    subject_id: int,
    slot_subject_history: dict[tuple[date, int], int],
) -> float:
    penalty = 0.0
    previous_day = current_day - timedelta(days=1)
    two_days_back = current_day - timedelta(days=2)
    if slot_subject_history.get((previous_day, session_index)) == subject_id:
        penalty += 0.55
    if slot_subject_history.get((two_days_back, session_index)) == subject_id:
        penalty += 0.25
    return penalty


def _pick_past_paper_subject(
    current_day: date,
    session_index: int,
    subjects: list[dict[str, Any]],
    subtopics: list[dict[str, Any]],
    past_paper_counts: Counter,
    assigned_counts: Counter,
    day_counts: Counter,
    exam_schedule: dict[int, list[dict[str, Any]]],
    need_map: dict[int, int],
    blocked_subject_ids: set[int],
    slot_subject_history: dict[tuple[date, int], int],
) -> dict[str, Any] | None:
    eligible_subjects = [row for row in subjects if row["id"] not in blocked_subject_ids]
    if not eligible_subjects:
        return None
    max_need = max([need_map.get(row["id"], 0) for row in eligible_subjects], default=1)

    def past_paper_key(row: dict[str, Any]) -> tuple[Any, ...]:
        exam_state = _subject_exam_state(row["id"], current_day, exam_schedule)
        linked_gap = _linked_gap_for_subject(row["id"], exam_state, subtopics)
        if exam_state["linked_subtopic_ids"]:
            linked_ratio = linked_gap / max(1, need_map.get(row["id"], 0))
        else:
            linked_ratio = 0.0
        final_week_bonus = 0.8 if exam_state["final_week"] else 0.0
        all_linked_ready_bonus = 0.6 if linked_gap == 0 else 0.0
        need_multiplier = 1.0 + (0.35 * (need_map.get(row["id"], 0) / max(1, max_need))) + (0.3 * linked_ratio)
        slot_penalty = _same_slot_repeat_penalty(current_day, session_index, row["id"], slot_subject_history)
        desirability = (
            (exam_state["past_paper_weight"] + final_week_bonus + all_linked_ready_bonus) * need_multiplier
        ) / (1 + past_paper_counts[row["id"]] + slot_penalty)
        return (
            -desirability,
            day_counts[row["id"]],
            _subject_balance_ratio(row["id"], assigned_counts, need_map),
            past_paper_counts[row["id"]],
            assigned_counts[row["id"]],
            exam_state["days_until_exam"] if exam_state["days_until_exam"] is not None else 9999,
            row["name"].casefold(),
        )

    return sorted(
        eligible_subjects,
        key=past_paper_key,
    )[0]


def _candidate_key(
    current_day: date,
    session_index: int,
    row: dict[str, Any],
    subject: dict[str, Any],
    subjects: list[dict[str, Any]],
    mode: str,
    assigned_counts: Counter,
    day_counts: Counter,
    need_map: dict[int, int],
    exam_state: dict[str, Any],
    subtopics: list[dict[str, Any]],
    exam_schedule: dict[int, list[dict[str, Any]]],
    slot_subject_history: dict[tuple[date, int], int],
    last_subject_id: int | None,
) -> tuple[Any, ...]:
    subject_id = subject["id"]
    ratio = _subject_balance_ratio(subject_id, assigned_counts, need_map)
    linked_gap = _linked_gap_for_subject(subject_id, exam_state, subtopics)
    pressure = _target_pressure(exam_state, linked_gap)
    reservation = _reservation_pressure(subject_id, current_day, exam_state, linked_gap, subjects, exam_schedule)
    gap_signal = 1.0 + (min(row["gap"], 4) * 0.45) + (max(row["gap"] - 4, 0) * 0.12)
    weighted_gap = gap_signal * exam_state["exam_weight"]
    linked_ids = exam_state["linked_subtopic_ids"]
    if linked_ids:
        if row["id"] in linked_ids:
            weighted_gap *= 1.0 + (0.8 * (exam_state["exam_weight"] - 1.0)) + min(1.8, pressure * 0.8) + min(2.6, reservation * 1.7)
        else:
            weighted_gap *= max(0.4, 0.9 - min(0.5, reservation * 0.45))
    elif row["gap"] > 0:
        weighted_gap *= 1.0 + min(0.35, pressure * 0.08)
    mix_penalty = 0.0
    if pressure < 0.55 and reservation < 0.72:
        mix_penalty += day_counts[subject_id] * 0.35
        if last_subject_id == subject_id:
            mix_penalty += 0.6
        mix_penalty += _same_slot_repeat_penalty(current_day, session_index, subject_id, slot_subject_history)
    common = (
        ratio,
        day_counts[subject_id],
        assigned_counts[subject_id],
        subject["name"].casefold(),
        row["table_title"].casefold(),
        row["subtopic"].casefold(),
    )
    if mode in {"low", "weekend_low"}:
        return (-(weighted_gap - mix_penalty), row["projected_confidence"], *common)
    if mode == "balance":
        return (ratio / max(exam_state["exam_weight"], 1.0), day_counts[subject_id], -(weighted_gap - mix_penalty), row["projected_confidence"], *common[4:])
    return (-(row["projected_confidence"] * exam_state["exam_weight"] - mix_penalty), ratio, day_counts[subject_id], *common[3:])


def _pick_revision_rows(
    current_day: date,
    session_index: int,
    mode: str,
    subjects: list[dict[str, Any]],
    subtopics: list[dict[str, Any]],
    projected: dict[int, int],
    assigned_counts: Counter,
    day_counts: Counter,
    need_map: dict[int, int],
    exam_schedule: dict[int, list[dict[str, Any]]],
    blocked_subtopic_ids: set[int],
    used_subtopic_ids: set[int],
    subtopic_exam_days: dict[int, list[date]],
    slot_subject_history: dict[tuple[date, int], int],
    last_subject_id: int | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]] | tuple[None, list[Any]]:
    critical_ids = _critical_linked_ids(current_day, subjects, subtopics, exam_schedule)
    candidates = [
        row
        for row in _pending_rows(projected, subtopics, minimum_gap=1)
        if row["id"] not in blocked_subtopic_ids
        and row["id"] not in used_subtopic_ids
        and _has_future_linked_exam(row["id"], current_day, subtopic_exam_days)
    ]
    if critical_ids:
        critical_candidates = [row for row in candidates if row["id"] in critical_ids]
        if critical_candidates and mode != "weekend_high":
            candidates = critical_candidates
    if not candidates or not subjects:
        return None, []

    subject_lookup = {row["id"]: row for row in subjects}
    ranked = sorted(
        candidates,
        key=lambda row: _candidate_key(
            current_day,
            session_index,
            row,
            subject_lookup[row["subject_id"]],
            subjects,
            mode,
            assigned_counts,
            day_counts,
            need_map,
            _subject_exam_state(row["subject_id"], current_day, exam_schedule),
            subtopics,
            exam_schedule,
            slot_subject_history,
            last_subject_id,
        ),
    )
    first = ranked[0]
    subject = subject_lookup[first["subject_id"]]
    return subject, [first]


def _build_revision_item(
    session_date: date,
    session_index: int,
    session_label: str,
    subject: dict[str, Any],
    chosen_rows: list[dict[str, Any]],
    mode: str,
) -> dict[str, Any]:
    names = [row["subtopic"] for row in chosen_rows]
    title = " + ".join(names)
    details = ", ".join(sorted({row["table_title"] for row in chosen_rows}))
    if mode == "balance":
        details = f"Balanced coverage · {details}"
    if mode == "weekend_high":
        details = f"Higher-confidence maintenance · {details}"
    return {
        "session_date": session_date.isoformat(),
        "session_index": session_index,
        "session_label": session_label,
        "session_kind": "revision",
        "subject_id": subject["id"],
        "subject_name": subject["name"],
        "title": title,
        "details": details,
        "subtopic_ids": [row["id"] for row in chosen_rows],
        "duration_minutes": SESSION_MINUTES,
    }


def _build_past_paper_item(
    session_date: date,
    session_index: int,
    session_label: str,
    subject: dict[str, Any],
    exam_state: dict[str, Any],
) -> dict[str, Any]:
    details = f"Past paper focus"
    if exam_state["exam_day"] is not None:
        details = f"Nearest exam: {exam_state['exam_name']} on {exam_state['exam_day'].isoformat()} · urgency {round(exam_state['past_paper_weight'], 2)}"
    return {
        "session_date": session_date.isoformat(),
        "session_index": session_index,
        "session_label": session_label,
        "session_kind": "past_paper",
        "subject_id": subject["id"],
        "subject_name": subject["name"],
        "title": f"Past paper - {subject['name']}",
        "details": details,
        "subtopic_ids": [],
        "duration_minutes": SESSION_MINUTES,
    }


def _item_is_valid_on_day(
    item: dict[str, Any],
    day: date,
    exam_schedule: dict[int, list[dict[str, Any]]],
    subtopic_exam_days: dict[int, list[date]],
) -> bool:
    subject_id = item.get("subject_id")
    if subject_id is None:
        return False
    final_exam = _final_exam_day(subject_id, exam_schedule)
    if final_exam is not None and day > final_exam:
        return False
    for exam in exam_schedule.get(subject_id, []):
        if exam["exam_day"] != day:
            continue
        if item["session_kind"] == "past_paper":
            return False
        linked_ids = set(exam.get("linked_subtopic_ids", set()))
        item_subtopic_ids = set(item.get("subtopic_ids", []))
        if linked_ids:
            return not bool(item_subtopic_ids & linked_ids)
        return False
    if item["session_kind"] == "revision":
        for subtopic_id in item.get("subtopic_ids", []):
            exam_days = subtopic_exam_days.get(subtopic_id, [])
            if exam_days and all(exam_day < day for exam_day in exam_days):
                return False
    return True


def _item_misses_target_on_day(item: dict[str, Any], day: date, subtopic_target_days: dict[int, list[date]]) -> bool:
    if item.get("session_kind") != "revision":
        return False
    for subtopic_id in item.get("subtopic_ids", []):
        target_days = subtopic_target_days.get(subtopic_id, [])
        if target_days and day > min(target_days):
            return True
    return False


def _reorder_day_items(
    day: date,
    day_items: list[dict[str, Any]],
    previous_day_lookup: dict[int, int],
) -> list[dict[str, Any]]:
    slots = sorted(item["session_index"] for item in day_items)
    remaining = [dict(item) for item in day_items]
    assigned: list[dict[str, Any]] = []
    last_subject_id: int | None = None
    for slot in slots:
        best = min(
            remaining,
            key=lambda item: (
                2 if previous_day_lookup.get(slot) == item["subject_id"] else 0,
                1 if last_subject_id == item["subject_id"] else 0,
                item["subject_name"].casefold(),
                item["title"].casefold(),
            ),
        )
        remaining.remove(best)
        best["session_index"] = slot
        best["session_label"] = f"Session {slot}"
        assigned.append(best)
        last_subject_id = best["subject_id"]
    return assigned


def _optimise_timetable_items(
    items: list[dict[str, Any]],
    subjects: list[dict[str, Any]],
    exams: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    exam_schedule = _exam_schedule_map(subjects, exams)
    subtopic_exam_days = _subtopic_exam_days(exams)
    subtopic_target_days = _subtopic_target_days(exams)
    working = [dict(item) for item in items]

    invalid_indexes = [
        index
        for index, item in enumerate(working)
        if not _item_is_valid_on_day(item, _parse_day(item["session_date"]), exam_schedule, subtopic_exam_days)
    ]
    for invalid_index in invalid_indexes:
        item = working[invalid_index]
        current_day = _parse_day(item["session_date"])
        for swap_index, candidate in enumerate(working):
            if swap_index == invalid_index:
                continue
            candidate_day = _parse_day(candidate["session_date"])
            if candidate_day >= current_day:
                continue
            if not _item_is_valid_on_day(item, candidate_day, exam_schedule, subtopic_exam_days):
                continue
            if not _item_is_valid_on_day(candidate, current_day, exam_schedule, subtopic_exam_days):
                continue
            item["session_date"], candidate["session_date"] = candidate["session_date"], item["session_date"]
            item["session_index"], candidate["session_index"] = candidate["session_index"], item["session_index"]
            item["session_label"], candidate["session_label"] = candidate["session_label"], item["session_label"]
            break

    late_target_indexes = [
        index
        for index, item in enumerate(working)
        if _item_misses_target_on_day(item, _parse_day(item["session_date"]), subtopic_target_days)
    ]
    for late_index in late_target_indexes:
        item = working[late_index]
        current_day = _parse_day(item["session_date"])
        swap_candidates = sorted(
            (
                (swap_index, candidate)
                for swap_index, candidate in enumerate(working)
                if swap_index != late_index and _parse_day(candidate["session_date"]) < current_day
            ),
            key=lambda pair: (
                _parse_day(pair[1]["session_date"]),
                pair[1]["session_index"],
            ),
        )
        for swap_index, candidate in swap_candidates:
            candidate_day = _parse_day(candidate["session_date"])
            if not _item_is_valid_on_day(item, candidate_day, exam_schedule, subtopic_exam_days):
                continue
            if _item_misses_target_on_day(item, candidate_day, subtopic_target_days):
                continue
            if not _item_is_valid_on_day(candidate, current_day, exam_schedule, subtopic_exam_days):
                continue
            if _item_misses_target_on_day(candidate, current_day, subtopic_target_days):
                continue
            item["session_date"], candidate["session_date"] = candidate["session_date"], item["session_date"]
            item["session_index"], candidate["session_index"] = candidate["session_index"], item["session_index"]
            item["session_label"], candidate["session_label"] = candidate["session_label"], item["session_label"]
            break

    by_day: dict[str, list[dict[str, Any]]] = {}
    for item in working:
        by_day.setdefault(item["session_date"], []).append(item)

    optimised: list[dict[str, Any]] = []
    previous_day_lookup: dict[int, int] = {}
    for day_key in sorted(by_day):
        day = _parse_day(day_key)
        reordered = _reorder_day_items(day, sorted(by_day[day_key], key=lambda item: item["session_index"]), previous_day_lookup)
        optimised.extend(reordered)
        previous_day_lookup = {item["session_index"]: item["subject_id"] for item in reordered}

    return sorted(optimised, key=lambda item: (item["session_date"], item["session_index"]))


def generate_timetable(
    start_date: str,
    end_date: str,
    subjects: list[dict[str, Any]],
    exams: list[dict[str, Any]],
    subtopics: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    start = _parse_day(start_date)
    end = _parse_day(end_date)
    if end < start:
        raise ValueError("End date must be on or after start date.")

    projected = {row["id"]: int(row["confidence"]) for row in subtopics}
    assigned_counts: Counter = Counter()
    past_paper_counts: Counter = Counter()
    exam_schedule = _exam_schedule_map(subjects, exams)
    subtopic_exam_days = _subtopic_exam_days(exams)
    slot_subject_history: dict[tuple[date, int], int] = {}
    items: list[dict[str, Any]] = []

    current = start
    while current <= end:
        active_subjects = [
            subject
            for subject in subjects
            if (_final_exam_day(subject["id"], exam_schedule) is None or current <= _final_exam_day(subject["id"], exam_schedule))
        ]
        active_subject_ids = {subject["id"] for subject in active_subjects}
        current_subtopics = [
            {**row, "confidence": projected[row["id"]]}
            for row in subtopics
            if row["subject_id"] in active_subject_ids
        ]
        if not _pending_rows(projected, current_subtopics) and not any(
            _next_exam(subject["id"], current, exam_schedule) is not None for subject in active_subjects
        ):
            break

        blocked_subject_ids, blocked_subtopic_ids = _exam_day_blocks(current, active_subjects, current_subtopics, exam_schedule)
        day_counts: Counter = Counter()
        used_subtopic_ids: set[int] = set()
        last_subject_id: int | None = None
        plan = _daily_plan(current, active_subjects, current_subtopics, exam_schedule)
        for offset, (label, mode) in enumerate(plan, start=1):
            current_subtopics = [
                {**row, "confidence": projected[row["id"]]}
                for row in subtopics
                if row["subject_id"] in active_subject_ids
            ]
            need_map = _subject_need_map(current_subtopics)
            if mode == "past_paper":
                subject = _pick_past_paper_subject(
                    current,
                    offset,
                    active_subjects,
                    current_subtopics,
                    past_paper_counts,
                    assigned_counts,
                    day_counts,
                    exam_schedule,
                    need_map,
                    blocked_subject_ids,
                    slot_subject_history,
                )
                if subject is None:
                    continue
                items.append(
                    _build_past_paper_item(
                        current,
                        offset,
                        label,
                        subject,
                        _subject_exam_state(subject["id"], current, exam_schedule),
                    )
                )
                past_paper_counts[subject["id"]] += 1
                assigned_counts[subject["id"]] += 1
                day_counts[subject["id"]] += 1
                slot_subject_history[(current, offset)] = subject["id"]
                last_subject_id = subject["id"]
                continue

            subject, chosen_rows = _pick_revision_rows(
                current,
                offset,
                mode,
                active_subjects,
                current_subtopics,
                projected,
                assigned_counts,
                day_counts,
                need_map,
                exam_schedule,
                blocked_subtopic_ids,
                used_subtopic_ids,
                subtopic_exam_days,
                slot_subject_history,
                last_subject_id,
            )
            if subject is None or not chosen_rows:
                continue

            items.append(_build_revision_item(current, offset, label, subject, chosen_rows, mode))
            assigned_counts[subject["id"]] += 1
            day_counts[subject["id"]] += 1
            last_subject_id = subject["id"]
            slot_subject_history[(current, offset)] = subject["id"]
            for row in chosen_rows:
                projected[row["id"]] = min(10, projected[row["id"]] + 1)
                used_subtopic_ids.add(row["id"])
        current += timedelta(days=1)

    items = _optimise_timetable_items(items, subjects, exams)
    remaining_points = sum(max(0, 10 - value) for value in projected.values())
    return items, {
        "scheduled_sessions": len(items),
        "remaining_points": remaining_points,
        "completed_within_range": remaining_points == 0,
    }
