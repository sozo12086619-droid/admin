import os
import re
import json
import time
import base64
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    MessagingApiBlob,
    ReplyMessageRequest,
    TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, ImageMessageContent
from google.oauth2 import service_account
from googleapiclient.discovery import build
import db

app = FastAPI()

CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "").strip("[] \t\r\n'\"")
CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "").strip("[] \t\r\n'\"")
USER_ID = os.environ.get("APP_USER_ID", "default").strip("[] \t\r\n'\"")
CALENDAR_ID = os.environ.get("GOOGLE_CALENDAR_ID", "").strip("[] \t\r\n'\"")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip("[] \t\r\n'\"")

try:
    db.init_db()
except Exception as e:
    print(f"DB Init Error: {e}")

WAGE_SETTINGS = {
    "すき家": {"day": 1150, "night": 1438},
    "default": {"day": 1150, "night": 1438},
}

CREDENTIALS_PATH = "/etc/secrets/google-credentials.json"
if not os.path.exists(CREDENTIALS_PATH):
    CREDENTIALS_PATH = "google-credentials.json"

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

def get_calendar_service():
    if not os.path.exists(CREDENTIALS_PATH):
        return None
    creds = service_account.Credentials.from_service_account_file(
        CREDENTIALS_PATH,
        scopes=["https://www.googleapis.com/auth/calendar"]
    )
    return build("calendar", "v3", credentials=creds)

def calculate_salary(start_dt: datetime, end_dt: datetime, summary: str):
    wage_info = WAGE_SETTINGS["default"]
    for key in WAGE_SETTINGS:
        if key in summary:
            wage_info = WAGE_SETTINGS[key]
            break

    current = start_dt
    day_minutes = 0
    night_minutes = 0

    while current < end_dt:
        if 9 <= current.hour < 22:
            day_minutes += 1
        else:
            night_minutes += 1
        current += timedelta(minutes=1)

    day_hours = day_minutes / 60
    night_hours = night_minutes / 60

    day_pay = round(day_hours * wage_info["day"])
    night_pay = round(night_hours * wage_info["night"])
    total_pay = day_pay + night_pay

    return {
        "total_pay": total_pay,
        "day_hours": round(day_hours, 1),
        "night_hours": round(night_hours, 1),
        "total_hours": round(day_hours + night_hours, 1),
        "day_pay": day_pay,
        "night_pay": night_pay
    }

def parse_shift_text(text: str):
    date_match = re.search(r'(?:(\d{4})[/-年])?\s*(\d{1,2})[/-月](\d{1,2})日?', text)
    time_match = re.search(r'(\d{1,2})(?::(\d{2}))?\s*[-〜~～]\s*(\d{1,2})(?::(\d{2}))?', text)

    if not date_match or not time_match:
        return None

    now = datetime.now()
    year = int(date_match.group(1)) if date_match.group(1) else now.year
    month = int(date_match.group(2))
    day = int(date_match.group(3))

    start_h = int(time_match.group(1))
    start_m = int(time_match.group(2)) if time_match.group(2) else 0
    end_h = int(time_match.group(3))
    end_m = int(time_match.group(4)) if time_match.group(4) else 0

    start_dt = datetime(year, month, day, start_h, start_m)
    if end_h < start_h:
        end_dt = datetime(year, month, day, end_h, end_m) + timedelta(days=1)
    else:
        end_dt = datetime(year, month, day, end_h, end_m)

    summary = text.replace(date_match.group(0), "").replace(time_match.group(0), "").strip()
    if not summary:
        summary = "シフト"

    salary = calculate_salary(start_dt, end_dt, summary)

    return {
        "summary": summary,
        "record_date": f"{year:04d}-{month:02d}-{day:02d}",
        "start": start_dt.strftime("%Y-%m-%dT%H:%M:%S+09:00"),
        "end": end_dt.strftime("%Y-%m-%dT%H:%M:%S+09:00"),
        "date_str": f"{month}/{day}",
        "time_str": f"{start_h:02d}:{start_m:02d}〜{end_h:02d}:{end_m:02d}",
        "salary": salary
    }

def add_event_to_calendar(parsed):
    service = get_calendar_service()
    if not service or not CALENDAR_ID:
        raise Exception("カレンダー認証情報またはCALENDAR_IDが未設定です")

    event = {
        'summary': parsed['summary'],
        'description': (
            f"見込み給料: ¥{parsed['salary']['total_pay']:,}\n"
            f"(昼: {parsed['salary']['day_hours']}h / 深夜: {parsed['salary']['night_hours']}h)\n"
            f"時間: {parsed['time_str']}"
        ),
        'start': {
            'dateTime': parsed['start'],
            'timeZone': 'Asia/Tokyo',
        },
        'end': {
            'dateTime': parsed['end'],
            'timeZone': 'Asia/Tokyo',
        },
    }
    return service.events().insert(calendarId=CALENDAR_ID, body=event).execute()

def guess_category(title: str) -> str:
    t = title.lower()
    if any(k in t for k in ["すき家", "サンエー", "セブン", "ファミリーマート", "ファミマ", "ローソン", "ミスタードーナツ", "ミスド", "マック", "スーパー", "食堂", "カフェ", "弁当"]):
        return "食費"
    elif any(k in t for k in ["ダイソー", "マツモトキヨシ", "マツキヨ", "薬", "ドラッグ", "日用品", "セリア"]):
        return "日用品"
    elif any(k in t for k in ["apple", "amazon", "カイカツ", "快活", "netflix", "spotify", "映画", "プライム"]):
        return "趣味・娯楽"
    elif any(k in t for k in ["電車", "バス", "タクシー", "ガソリン", "定期"]):
        return "交通費"
    return "その他"

def parse_expense_text(text: str):
    if re.search(r'\d{1,2}(?::\d{2})?\s*[-〜~～]\s*\d{1,2}', text):
        return None

    if re.search(r'^(?:合計|小計|PayPay|VISAデビット)\s*[\d,]+円?\s*(?:\(\d+件\))?$', text.strip()):
        return None

    match = re.search(r'(?:(\d{4})[/-年])?\s*(\d{1,2})[/-月](\d{1,2})日?\s+(.+?)\s+([0-9,]+)\s*円?$', text.strip())
    if not match:
        return None

    now = datetime.now()
    year = int(match.group(1)) if match.group(1) else now.year
    month = int(match.group(2))
    day = int(match.group(3))
    title = match.group(4).strip()
    amount_str = match.group(5).replace(",", "").strip()

    try:
        amount = int(amount_str)
    except ValueError:
        return None

    if amount <= 0:
        return None

    category = guess_category(title)
    record_date = f"{year:04d}-{month:02d}-{day:02d}"

    return {
        "record_date": record_date,
        "title": title,
        "amount": amount,
        "category": category
    }

def analyze_expense_image(image_bytes: bytes) -> list[dict]:
    clean_key = GEMINI_API_KEY.strip("[] \t\r\n'\"")
    if not clean_key:
        raise Exception("Renderの環境変数に GEMINI_API_KEY が設定されていません")

    model_name = "models/gemini-3.8-flash"
    target_url = f"https://generativelanguage.googleapis.com/v1beta/{model_name}:generateContent?key={clean_key}".strip("[] \t\r\n'\"")

    b64_img = base64.b64encode(image_bytes).decode("utf-8")
    now_str = datetime.now().strftime("%Y-%m-%d")

    prompt = (
        f"この画像から実際に支払いが完了した【支出】のみをすべて抽出してください。\n"
        f"「支払い失敗」「チャージ」「受取」「ポイント付与」「残高」は絶対に除外してください。\n"
        f"以下のJSON配列形式のみで出力してください（マークダウン不要）。\n"
        f"[\n"
        f"  {{\n"
        f'    "date": "YYYY-MM-DD形式。不明なら「{now_str}」",\n'
        f'    "store": "店名や摘要",\n'
        f'    "amount": 金額（正の整数）,\n'
        f'    "category": "食費" または "日用品" または "交通費" または "交際費" または "趣味・娯楽" または "その他",\n'
        f'    "detail": "品目等"\n'
        f"  }}\n"
        f"]"
    )

    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": "image/jpeg", "data": b64_img}}
            ]
        }],
        "generationConfig": {"response_mime_type": "application/json"}
    }

    req = urllib.request.Request(
        target_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            res_data = json.loads(res.read().decode("utf-8"))
            text = res_data["candidates"][0]["content"]["parts"][0]["text"]
            clean_text = re.sub(r"^```(?:json)?\s*", "", text.strip())
            clean_text = re.sub(r"\s*
