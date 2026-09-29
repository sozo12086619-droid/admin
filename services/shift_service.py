"""shift_service.py — 「9/21 すき家 18:00-23:00」のような1行をシフトとして読み取る"""

import re
from datetime import datetime, timedelta

from services.datetext import find_date, remove_span
from services.salary_service import calculate_salary

_TIME_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*[-〜~～]\s*(\d{1,2})(?::(\d{2}))?")


def parse_shift_text(text: str) -> dict | None:
    """シフトとして読めなければ None。読めれば登録に必要な情報をまとめた dict を返す。"""
    found = find_date(text)
    if not found:
        return None
    date_match, day = found

    # 日付の部分を取り除いてから時間帯を探す
    # （2026-09-15 の "26-09" などを時間帯と取り違えないため）
    rest = remove_span(text, date_match.start(), date_match.end())
    time_match = _TIME_RE.search(rest)
    if not time_match:
        return None

    start_h = int(time_match.group(1))
    start_m = int(time_match.group(2)) if time_match.group(2) else 0
    end_h = int(time_match.group(3))
    end_m = int(time_match.group(4)) if time_match.group(4) else 0

    # 25時や 70分 のようなありえない時刻はシフトとして扱わない
    if not (0 <= start_h <= 23 and 0 <= start_m <= 59 and 0 <= end_h <= 24 and 0 <= end_m <= 59):
        return None
    if end_h == 24 and end_m != 0:
        return None

    start_dt = datetime(day.year, day.month, day.day, start_h, start_m)
    if end_h == 24:  # 「22:00-24:00」は翌日の 0:00 終わり
        end_dt = datetime(day.year, day.month, day.day) + timedelta(days=1)
    else:
        end_dt = datetime(day.year, day.month, day.day, end_h, end_m)
        if end_h < start_h:  # 「22:00-2:00」のような日またぎ
            end_dt += timedelta(days=1)

    summary = rest.replace(time_match.group(0), "", 1)
    summary = re.sub(r"\s+", " ", summary).strip() or "シフト"

    salary = calculate_salary(start_dt, end_dt, summary)

    return {
        "summary": summary,
        "record_date": day.isoformat(),
        "start": start_dt.strftime("%Y-%m-%dT%H:%M:%S+09:00"),
        "end": end_dt.strftime("%Y-%m-%dT%H:%M:%S+09:00"),
        "date_str": f"{day.month}/{day.day}",
        "time_str": f"{start_h:02d}:{start_m:02d}〜{end_h:02d}:{end_m:02d}",
        "salary": salary,
    }
