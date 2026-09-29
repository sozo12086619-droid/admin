"""salary_service.py — シフト時間から見込み給料を計算する"""

from datetime import datetime, timedelta

import config


def calculate_salary(start_dt: datetime, end_dt: datetime, summary: str) -> dict:
    """1分ずつ「昼／深夜」に振り分けて時給を掛ける。

    昼 = 9時〜22時、それ以外 = 深夜（config.DAY_START_HOUR / DAY_END_HOUR）。
    勤務先名（summary）に WAGE_SETTINGS のキーが含まれていればその時給を使う。
    """
    wage_info = config.WAGE_SETTINGS["default"]
    for key in config.WAGE_SETTINGS:
        if key in summary:
            wage_info = config.WAGE_SETTINGS[key]
            break

    current = start_dt
    day_minutes = 0
    night_minutes = 0

    while current < end_dt:
        if config.DAY_START_HOUR <= current.hour < config.DAY_END_HOUR:
            day_minutes += 1
        else:
            night_minutes += 1
        current += timedelta(minutes=1)

    day_hours = day_minutes / 60
    night_hours = night_minutes / 60

    day_pay = round(day_hours * wage_info["day"])
    night_pay = round(night_hours * wage_info["night"])

    return {
        "total_pay": day_pay + night_pay,
        "day_hours": round(day_hours, 1),
        "night_hours": round(night_hours, 1),
        "total_hours": round(day_hours + night_hours, 1),
        "day_pay": day_pay,
        "night_pay": night_pay,
    }
