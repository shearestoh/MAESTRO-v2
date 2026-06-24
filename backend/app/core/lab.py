"""
Virtual lab clock and time management.

The virtual lab runs from 09:00 to 17:00 (480 minutes).
Each sample preparation costs VIRTUAL_MIN_SAMPLER minutes.
Each test costs VIRTUAL_MIN_TESTER minutes.
This creates realistic time pressure for the agent.
"""
from app.core.config import (
    LAB_START_HOUR, LAB_START_MINUTE,
    LAB_END_HOUR, LAB_END_MINUTE,
    VIRTUAL_MIN_SAMPLER, VIRTUAL_MIN_TESTER,
)


def format_virtual_time(total_minutes: int) -> str:
    total = LAB_START_HOUR * 60 + LAB_START_MINUTE + total_minutes
    hours = (total // 60) % 24
    mins  = total % 60
    return f"{hours:02d}:{mins:02d}"


def lab_day_total_minutes() -> int:
    return (LAB_END_HOUR * 60 + LAB_END_MINUTE) - (LAB_START_HOUR * 60 + LAB_START_MINUTE)


def lab_minutes_remaining(session) -> int:
    return max(0, lab_day_total_minutes() - session.virtual_clock_minutes)


def add_virtual_time(session, minutes: int):
    session.virtual_clock_minutes += minutes


def max_successes_fit_in_remaining_time(session) -> int:
    per_success = VIRTUAL_MIN_SAMPLER + VIRTUAL_MIN_TESTER
    if per_success <= 0:
        return 0
    return lab_minutes_remaining(session) // per_success


def advance_to_next_day(session):
    session.virtual_day_index    += 1
    session.virtual_clock_minutes = 0