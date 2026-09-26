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

# RenderのSecret Files置き場
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

def parse_shift_text(text: str):
    """
    メッセージから日付・時間・シフト名を解析する
    例: 「10/6 18:00-23:00 すき家」「10月6日 18:00〜23:00 バイト」
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
    # 終了時刻が開始時刻より前（夜勤・日またぎ）の場合は翌日にする
    if end_h < start_h:
        end_dt = datetime(year, month, day, end_h, end_m) + timedelta(days=1)
    else:
        end_dt = datetime(year, month, day, end_h, end_m)

    summary = text.replace(date_match.group(0), "").replace(time_match.group(0), "").strip()
    if not summary:
        summary = "シフト"

    return {
        "summary": summary,
        "start": start_dt.strftime("%Y-%m-%dT%H:%M:%S+09:00"),
        "end": end_dt.strftime("%Y-%m-%dT%H:%M:%S+09:00"),
        "date_str": f"{month}/{day}",
        "time_str": f"{start_h:02d}:{start_m:02d}〜{end_h:02d}:{end_m:02d}"
    }

def add_event_to_calendar(parsed):
    """Googleカレンダーに予定を登録"""
    service = get_calendar_service()
    if not service or not CALENDAR_ID:
        raise Exception("カレンダー認証情報またはCALENDAR_IDが未設定です")

    event = {
        'summary': parsed['summary'],
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
    
    # 1. 届いたメッセージをSupabaseの raw_notes に保存（従来機能の維持）
    raw_id = None
    try:
        raw_id = db.save_raw_note(user_id=USER_ID, body=text, source="line")
    except Exception as e:
        print(f"DB Error: {e}")

    # 2. Googleカレンダーへの登録判定（改行で複数日送られても対応）
    calendar_success = []
    calendar_error = None
    lines = [line.strip() for line in text.split("\n") if line.strip()]

    for line in lines:
        parsed = parse_shift_text(line)
        if parsed:
            try:
                add_event_to_calendar(parsed)
                calendar_success.append(f"・{parsed['date_str']} {parsed['time_str']} {parsed['summary']}")
            except Exception as e:
                calendar_error = str(e)
                print(f"Calendar Error: {e}")

    # 3. LINE返信メッセージの作成
    if calendar_success:
        reply_text = "カレンダーにシフトを登録したで！📅\n" + "\n".join(calendar_success) + "\n\n（TimeTreeにもまもなく自動反映されるで！）"
        if calendar_error:
            reply_text += f"\n※一部エラー: {calendar_error}"
    elif calendar_error:
        reply_text = f"メモは保存したけど、カレンダー登録でエラーが出たで💦\n{calendar_error}"
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
