"""
Lab clock and scheduling utilities.

Time is tracked in real wall-clock seconds for actual deployments.
The virtual clock (minutes) is retained for demo instruments that
execute instantly — it provides a simulated time budget for planning.
"""
from __future__ import annotations
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.models import SessionModel


LAB_START_HOUR = 9
LAB_START_MINUTE = 0
LAB_END_HOUR = 17
LAB_END_MINUTE = 0
LAB_DAY_MINUTES = (LAB_END_HOUR * 60 + LAB_END_MINUTE) - (LAB_START_HOUR * 60 + LAB_START_MINUTE)


def format_clock_time(total_minutes: int) -> str:
    """Format virtual clock minutes as HH:MM from lab start."""
    total = LAB_START_HOUR * 60 + LAB_START_MINUTE + total_minutes
    hours = (total // 60) % 24
    mins  = total % 60
    return f"{hours:02d}:{mins:02d}"


def lab_minutes_remaining(session: "SessionModel") -> int:
    return max(0, LAB_DAY_MINUTES - session.virtual_clock_minutes)


def add_virtual_time(session: "SessionModel", minutes: int) -> None:
    session.virtual_clock_minutes += minutes


def max_steps_in_remaining_time(session: "SessionModel", minutes_per_step: int) -> int:
    if minutes_per_step <= 0:
        return 0
    return lab_minutes_remaining(session) // minutes_per_step


def advance_to_next_day(session: "SessionModel") -> None:
    session.virtual_day_index    += 1
    session.virtual_clock_minutes = 0