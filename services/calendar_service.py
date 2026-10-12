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

    # message_service 側で計算された給与情報（バイト先別対応）、なければ従来の salary
    sal = parsed.get("salary_calc") or parsed.get("salary") or {}
    total_pay = sal.get("total_pay", 0)
    detail_str = sal.get("detail", "")
    time_str = parsed.get("time_str", "")

    description_lines = [
        f"見込み: ¥{total_pay:,}",
    ]
    if detail_str:
        description_lines.append(f"内訳: {detail_str}")
    if time_str:
        description_lines.append(f"時間: {time_str}")

    event = {
        "summary": parsed["summary"],
        "description": "\n".join(description_lines),
        "start": {"dateTime": parsed["start"], "timeZone": "Asia/Tokyo"},
        "end": {"dateTime": parsed["end"], "timeZone": "Asia/Tokyo"},
    }

    # 色分け指定がある場合は colorId を付与（Google カレンダー / TimeTree 反映）
    if parsed.get("color_id"):
        event["colorId"] = str(parsed["color_id"])

    return service.events().insert(calendarId=config.GOOGLE_CALENDAR_ID, body=event).execute()
