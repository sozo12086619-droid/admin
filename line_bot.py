import os
import re
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
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

# 起動時にデータベーステーブルの存在確認・作成
try:
    db.init_db()
except Exception as e:
    print(f"DB Init Error: {e}")

# バイト先ごとの時給設定
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

# -------------------------------------------------------------
# 家計簿ダッシュボード（スマホ対応Web画面）
# -------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def dashboard(month: str | None = None):
    # 月の指定がない場合は今月（例: 2026-10）
    target_month = month or datetime.now().strftime("%Y-%m")
    
    # 前月・翌月の計算
    curr_dt = datetime.strptime(f"{target_month}-01", "%Y-%m-%d")
    prev_dt = (curr_dt - timedelta(days=1)).replace(day=1)
    next_dt = (curr_dt + timedelta(days=32)).replace(day=1)
    prev_month_str = prev_dt.strftime("%Y-%m")
    next_month_str = next_dt.strftime("%Y-%m")
    year_str, month_str = target_month.split("-")

    # Supabaseから集計サマリーと明細を取得
    summary = db.fetch_monthly_money_summary(target_month, USER_ID)
    records = db.query(
        """
        SELECT * FROM public.money_records
        WHERE user_id = %s AND record_date LIKE %s
        ORDER BY record_date DESC, id DESC
        """,
        (USER_ID, f"{target_month}%")
    )

    # 明細カードのHTML作成
    records_html = ""
    if not records:
        records_html = '<div class="empty-state">この月の記録はまだありません</div>'
    else:
        for r in records:
            is_income = r["record_type"] == "income"
            sign = "+" if is_income else "-"
            badge_class = "badge-income" if is_income else "badge-expense"
            badge_text = "見込給料" if (is_income and r["status"] == "expected") else ("収入" if is_income else "支出")
            
            detail_line = f'<div class="record-detail">{r["detail"]}</div>' if r["detail"] else ''
            
            records_html += f"""
            <div class="record-card">
                <div class="record-left">
                    <span class="badge {badge_class}">{badge_text}</span>
                    <span class="record-title">{r["title"]}</span>
                    <div class="record-date">{r["record_date"]}</div>
                    {detail_line}
                </div>
                <div class="record-amount {'amount-income' if is_income else 'amount-expense'}">
                    {sign}¥{r["amount"]:,}
                </div>
            </div>
            """

    # 全体HTML
    html_content = f"""
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>家計簿 & シフト管理</title>
        <style>
            * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
            body {{ background-color: #f7f8fa; color: #333; padding-bottom: 40px; }}
            .header {{ background: #2c3e50; color: white; padding: 18px 20px; text-align: center; position: sticky; top: 0; z-index: 10; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
            .header h1 {{ font-size: 1.1rem; font-weight: 600; letter-spacing: 0.5px; }}
            .month-nav {{ display: flex; justify-content: space-between; align-items: center; background: white; padding: 12px 20px; margin-bottom: 16px; border-bottom: 1px solid #eee; }}
            .month-nav a {{ text-decoration: none; color: #3498db; font-size: 0.95rem; font-weight: bold; padding: 6px 12px; border-radius: 6px; background: #edf5fc; }}
            .current-month {{ font-size: 1.2rem; font-weight: 700; color: #2c3e50; }}
            .container {{ max-width: 500px; margin: 0 auto; padding: 0 16px; }}
            
            /* サマリーカード */
            .summary-card {{ background: white; border-radius: 14px; padding: 20px; box-shadow: 0 3px 12px rgba(0,0,0,0.04); margin-bottom: 20px; }}
            .summary-main {{ text-align: center; margin-bottom: 16px; padding-bottom: 16px; border-bottom: 1px dashed #eee; }}
            .summary-main-label {{ font-size: 0.85rem; color: #7f8c8d; margin-bottom: 4px; }}
            .summary-main-val {{ font-size: 2rem; font-weight: 800; color: #27ae60; }}
            .summary-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; text-align: center; }}
            .summary-sub-label {{ font-size: 0.8rem; color: #7f8c8d; }}
            .summary-sub-val {{ font-size: 1.15rem; font-weight: 700; margin-top: 4px; }}
            .val-expense {{ color: #e74c3c; }}
            .val-balance {{ color: #2980b9; }}
            
            /* 明細リスト */
            .section-title {{ font-size: 0.95rem; font-weight: 700; color: #555; margin-bottom: 10px; padding-left: 4px; }}
            .record-card {{ background: white; border-radius: 12px; padding: 14px 16px; display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; box-shadow: 0 2px 6px rgba(0,0,0,0.03); }}
            .record-left {{ display: flex; flex-direction: column; gap: 4px; }}
            .record-title {{ font-size: 1rem; font-weight: 700; color: #2c3e50; margin-left: 4px; }}
            .record-date {{ font-size: 0.75rem; color: #95a5a6; }}
            .record-detail {{ font-size: 0.78rem; color: #7f8c8d; margin-top: 2px; }}
            .badge {{ font-size: 0.7rem; padding: 2px 7px; border-radius: 4px; font-weight: bold; width: fit-content; }}
            .badge-income {{ background: #e8f8f0; color: #27ae60; }}
            .badge-expense {{ background: #fdf0ee; color: #e74c3c; }}
            .record-amount {{ font-size: 1.1rem; font-weight: 800; white-space: nowrap; }}
            .amount-income {{ color: #27ae60; }}
            .amount-expense {{ color: #e74c3c; }}
            .empty-state {{ text-align: center; padding: 30px; color: #bdc3c7; font-size: 0.9rem; background: white; border-radius: 12px; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>家計簿 & シフト管理</h1>
        </div>
        
        <div class="month-nav">
            <a href="/?month={prev_month_str}">◀ 前月</a>
            <div class="current-month">{year_str}年 {month_str}月</div>
            <a href="/?month={next_month_str}">翌月 ▶</a>
        </div>
        
        <div class="container">
            <div class="summary-card">
                <div class="summary-main">
                    <div class="summary-main-label">バイト給料（見込み合計）</div>
                    <div class="summary-main-val">¥{summary["total_income"]:,}</div>
                </div>
                <div class="summary-grid">
                    <div>
                        <div class="summary-sub-label">支出合計</div>
                        <div class="summary-sub-val val-expense">¥{summary["expenses"]:,}</div>
                    </div>
                    <div>
                        <div class="summary-sub-label">今月の差引残高</div>
                        <div class="summary-sub-val val-balance">¥{summary["balance"]:,}</div>
                    </div>
                </div>
            </div>
            
            <div class="section-title">登録済みのシフト・収支一覧</div>
            {records_html}
        </div>
    </body>
    </html>
    """
    return html_content

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

    # 2. シフト判定・カレンダー登録・家計簿保存
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
                
                detail_text = f"{parsed['time_str']} (昼{sal['day_hours']}h/深夜{sal['night_hours']}h)"
                db.insert_money_record(
                    record_date=parsed["record_date"],
                    record_type="income",
                    category="バイト",
                    title=parsed["summary"],
                    amount=sal["total_pay"],
                    status="expected",
                    detail=detail_text,
                    raw_note_id=raw_id,
                    user_id=USER_ID
                )

                detail = f"・{parsed['date_str']} {parsed['time_str']} {parsed['summary']}\n  💰見込: ¥{sal['total_pay']:,} (昼{sal['day_hours']}h / 深夜{sal['night_hours']}h)"
                calendar_success.append(detail)
            except Exception as e:
                calendar_error = str(e)
                print(f"Calendar / DB Error: {e}")

    # 3. LINE返信
    if calendar_success:
        reply_lines = ["カレンダー & 家計簿に登録したで！📅💰", ""]
        reply_lines.extend(calendar_success)
        
        if len(calendar_success) > 1:
            reply_lines.append("")
            reply_lines.append(f"【今回の一括合計】 ¥{total_expected_salary:,}")

        reply_lines.append("\n（カレンダーは予定名のみスッキリ反映済！）")
        
        if calendar_error:
            reply_lines.append(f"\n※一部エラー: {calendar_error}")
            
        reply_text = "\n".join(reply_lines)
    elif calendar_error:
        reply_text = f"メモは保存したけどカレンダー登録でエラーが出たで💦\n{calendar_error}"
    elif raw_id:
        reply_text = f"メモを受け取ったで！\n「{text}」\n(ID: {raw_id})"
    else:
        reply_text = f"メモを受け取ったで！\n「{text}」"

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )
