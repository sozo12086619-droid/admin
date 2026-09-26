import os
import re
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, HTTPException
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from google.oauth2 import service_account
from googleapiclient.discovery import build
import db

app = FastAPI()

CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
USER_ID = os.environ.get("APP_USER_ID", "default")
CALENDAR_ID = os.environ.get("GOOGLE_CALENDAR_ID", "")

# -------------------------------------------------------------
# バイト先ごとの時給設定（昼: 9:00〜22:00 / 深夜: 22:00〜翌9:00）
# 新しいバイト先が増えたらここに追加できます
# -------------------------------------------------------------
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
    """GoogleカレンダーAPIのクライアントを作成"""
    if not os.path.exists(CREDENTIALS_PATH):
        return None
    creds = service_account.Credentials.from_service_account_file(
        CREDENTIALS_PATH,
        scopes=["https://www.googleapis.com/auth/calendar"]
    )
    return build("calendar", "v3", credentials=creds)

def calculate_salary(start_dt: datetime, end_dt: datetime, summary: str):
    """
    勤務時間から通常時間・深夜時間を集計し、見込み給料を計算する
    """
    # バイト先に応じた時給を取得
    wage_info = WAGE_SETTINGS["default"]
    for key in WAGE_SETTINGS:
        if key in summary:
            wage_info = WAGE_SETTINGS[key]
            break

    current = start_dt
    day_minutes = 0
    night_minutes = 0

    # 1分刻みで昼（9-22時）と深夜（22-9時）を正確に判定
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
    """
    メッセージから日付・時間・シフト名を解析し、給料も算出する
    """
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
    # 日またぎ（終了時刻が開始時刻より前）の対応
    if end_h < start_h:
        end_dt = datetime(year, month, day, end_h, end_m) + timedelta(days=1)
    else:
        end_dt = datetime(year, month, day, end_h, end_m)

    summary = text.replace(date_match.group(0), "").replace(time_match.group(0), "").strip()
    if not summary:
        summary = "シフト"

    # 給料計算を実行
    salary = calculate_salary(start_dt, end_dt, summary)

    return {
        "summary": summary,
        "start": start_dt.strftime("%Y-%m-%dT%H:%M:%S+09:00"),
        "end": end_dt.strftime("%Y-%m-%dT%H:%M:%S+09:00"),
        "date_str": f"{month}/{day}",
        "time_str": f"{start_h:02d}:{start_m:02d}〜{end_h:02d}:{end_m:02d}",
        "salary": salary
    }

def add_event_to_calendar(parsed):
    """Googleカレンダーに予定を登録"""
    service = get_calendar_service()
    if not service or not CALENDAR_ID:
        raise Exception("カレンダー認証情報またはCALENDAR_IDが未設定です")

    event = {
        'summary': f"[{parsed['summary']}] ¥{parsed['salary']['total_pay']:,}",
        'description': f"見込み給料: ¥{parsed['salary']['total_pay']:,}\n(通常 {parsed['salary']['day_hours']}h / 深夜 {parsed['salary']['night_hours']}h)",
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

@app.get("/")
def health_check():
    return {"status": "ok"}

@app.post("/callback")
async def callback(request: Request):
    signature = request.headers.get("X-Line-Signature", "")
    body = await request.body()
    try:
        handler.handle(body.decode("utf-8"), signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    return "OK"

@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    text = event.message.text.strip()
    
    # 1. Supabaseの raw_notes に保存
    raw_id = None
    try:
        raw_id = db.save_raw_note(user_id=USER_ID, body=text, source="line")
    except Exception as e:
        print(f"DB Error: {e}")

    # 2. シフト判定・カレンダー登録・給料計算
    calendar_success = []
    calendar_error = None
    total_expected_salary = 0
    lines = [line.strip() for line in text.split("\n") if line.strip()]

    for line in lines:
        parsed = parse_shift_text(line)
        if parsed:
            try:
                add_event_to_calendar(parsed)
                sal = parsed['salary']
                total_expected_salary += sal['total_pay']
                
                detail = f"・{parsed['date_str']} {parsed['time_str']} {parsed['summary']}\n  💰見込: ¥{sal['total_pay']:,} (昼{sal['day_hours']}h / 深夜{sal['night_hours']}h)"
                calendar_success.append(detail)
            except Exception as e:
                calendar_error = str(e)
                print(f"Calendar Error: {e}")

    # 3. LINE返信メッセージの作成
    if calendar_success:
        reply_lines = ["カレンダー登録 & 給料計算完了！📅💰", ""]
        reply_lines.extend(calendar_success)
        
        # 複数シフトが送られた場合は合計金額も表示
        if len(calendar_success) > 1:
            reply_lines.append("")
            reply_lines.append(f"【今回の一括合計】 ¥{total_expected_salary:,}")

        reply_lines.append("\n（TimeTreeにも反映されるで！）")
        
        if calendar_error:
            reply_lines.append(f"\n※一部エラー: {calendar_error}")
            
        reply_text = "\n".join(reply_lines)
    elif calendar_error:
        reply_text = f"メモは保存したけどカレンダー登録でエラーが出たで💦\n{calendar_error}"
    elif raw_id:
        reply_text = f"メモを受け取ったで！\n「{text}」\n(ID: {raw_id})"
    else:
        reply_text = f"メモを受け取ったで！\n「{text}」"

    # 4. LINEに返信
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )
