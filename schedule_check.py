import random
from datetime import datetime, timedelta, time as dt_time
from zoneinfo import ZoneInfo
from config import config

def local_today_str():
    return datetime.now(ZoneInfo("America/New_York")).date().isoformat()

def pick_target_publish_datetime(date_str, slot, num_slots=None):
    num_slots = num_slots or config.videos_per_day
    tz = ZoneInfo("America/New_York")
    start_h, start_m = 14, 30
    end_h, end_m = 17, 30
    date = datetime.fromisoformat(date_str).date()
    window_start = datetime.combine(date, dt_time(start_h, start_m), tzinfo=tz)
    window_end = datetime.combine(date, dt_time(end_h, end_m), tzinfo=tz)
    total_seconds = (window_end - window_start).total_seconds()
    slot_seconds = total_seconds / num_slots
    slot_start = window_start + timedelta(seconds=slot_seconds * slot)
    offset_seconds = random.uniform(0, slot_seconds)
    return slot_start + timedelta(seconds=offset_seconds)
