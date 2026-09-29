"""calendar_service.py — Google カレンダーにシフトを登録する"""

import os

from google.oauth2 import service_account
from googleapiclient.discovery import build

import config

_SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _get_calendar_service():
    if not os.path.exists(config.CREDENTIALS_PATH):
        return None
    creds = service_account.Credentials.from_service_account_file(
        config.CREDENTIALS_PATH, scopes=_SCOPES
    )
    # googleapiclient の接続オブジェクトはスレッド間で共有できないので、毎回作る
    return build("calendar", "v3", credentials=creds)


def add_event_to_calendar(parsed: dict) -> dict:
    """parse_shift_text の結果をカレンダーに登録する。失敗したら例外を投げる。"""
    service = _get_calendar_service()
    if not service or not config.GOOGLE_CALENDAR_ID:
        raise RuntimeError("カレンダー認証情報またはCALENDAR_IDが未設定です")

    salary = parsed["salary"]
    event = {
        "summary": parsed["summary"],
        "description": (
            f"見込み給料: ¥{salary['total_pay']:,}\n"
            f"(昼: {salary['day_hours']}h / 深夜: {salary['night_hours']}h)\n"
            f"時間: {parsed['time_str']}"
        ),
        "start": {"dateTime": parsed["start"], "timeZone": "Asia/Tokyo"},
        "end": {"dateTime": parsed["end"], "timeZone": "Asia/Tokyo"},
    }
    return service.events().insert(calendarId=config.GOOGLE_CALENDAR_ID, body=event).execute()
