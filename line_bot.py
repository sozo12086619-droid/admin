import os
import re
import json
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

# -------------------------------------------------------------
# 最新の利用可能Geminiモデルを自動検出
# -------------------------------------------------------------
def get_best_gemini_model() -> str:
    clean_key = GEMINI_API_KEY.strip("[] \t\r\n'\"")
    if not clean_key:
        raise Exception("Renderの環境変数に GEMINI_API_KEY が設定されていません")

    list_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={clean_key}".strip("[] \t\r\n'\"")
    try:
        req = urllib.request.Request(list_url, method="GET")
        with urllib.request.urlopen(req, timeout=10) as res:
            res_data = json.loads(res.read().decode("utf-8"))
            available = [
                m["name"] for m in res_data.get("models", [])
                if "generateContent" in m.get("supportedGenerationMethods", [])
            ]
            preferred = [
                "models/gemini-3.8-flash",
                "models/gemini-3.0-flash",
                "models/gemini-3-flash",
                "models/gemini-2.0-flash",
            ]
            for p in preferred:
                if p in available:
                    return p
            for a in available:
                if "3." in a and "flash" in a.lower():
                    return a
            for a in available:
                if "flash" in a.lower():
                    return a
            if available:
                return available[0]
    except Exception as e:
        print(f"ListModels Warning: {e}")

    return "models/gemini-3.8-flash"

# -------------------------------------------------------------
# 支出画像解析（PayPay支出厳格判定＆除外機能付き）
# -------------------------------------------------------------
def analyze_expense_image(image_bytes: bytes) -> list[dict]:
    clean_key = GEMINI_API_KEY.strip("[] \t\r\n'\"")
    if not clean_key:
        raise Exception("Renderの環境変数に GEMINI_API_KEY が設定されていません")

    model_name = get_best_gemini_model()
    target_url = f"https://generativelanguage.googleapis.com/v1beta/{model_name}:generateContent?key={clean_key}".strip("[] \t\r\n'\"")
    
    b64_img = base64.b64encode(image_bytes).decode("utf-8")
    now_str = datetime.now().strftime("%Y-%m-%d")

    prompt = (
        f"この画像（レシート写真、銀行口座、クレジットカード、またはPayPayなどの決済アプリの取引履歴スクショ）から、"
        f"実際に支払いが完了した【支出】のみをすべて抽出してください。\n\n"
        f"【絶対に除外する項目】\n"
        f"・「支払い失敗」や未完了の取引（グレー表示や取り消し線など）\n"
        f"・「チャージ」「ATMからのチャージ」\n"
        f"・「受け取る」「受け取り完了」「送金受取」\n"
        f"・「PayPayポイント」「付与処理中」「ポイント付与」\n"
        f"・口座残高やポイント残高の数字\n\n"
        f"上記を除外し、実際に買い物や決済が完了した支出のみを以下のJSON配列形式で出力してください。\n"
        f"マークダウンの```json等は含めず、純粋なJSON文字列（配列）のみを出力してください。\n"
        f"[\n"
        f"  {{\n"
        f'    "date": "YYYY-MM-DD形式（例: 2026-09-27）。年がない場合は2026年を補完。不明なら「{now_str}」",\n'
        f'    "store": "店名やサービス名（例: ミスタードーナツ、すき家、ダイソー、Amazonなど）",\n'
        f'    "amount": 金額（マイナスや円、カンマは除いた正の整数。例: 1065）,\n'
        f'    "category": "食費" または "日用品" または "交通費" または "交際費" または "趣味・娯楽" または "その他",\n'
        f'    "detail": "店舗支店名や品目があれば簡潔に（例: サンエー西原ショップ）"\n'
        f"  }}\n"
        f"]"
    )

    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {
                    "inline_data": {
                        "mime_type": "image/jpeg",
                        "data": b64_img
                    }
                }
            ]
        }],
        "generationConfig": {
            "response_mime_type": "application/json"
        }
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
            clean_text = re.sub(r"\s*```$", "", clean_text.strip())
            parsed = json.loads(clean_text)
            if isinstance(parsed, dict):
                return [parsed]
            elif isinstance(parsed, list):
                return parsed
            return []
    except urllib.error.HTTPError as he:
        err_msg = he.read().decode("utf-8", errors="ignore")
        raise Exception(f"HTTP {he.code}: {err_msg}")

# -------------------------------------------------------------
# 家計簿ダッシュボード（Web画面）
# -------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def dashboard(month: str | None = None):
    target_month = month or datetime.now().strftime("%Y-%m")
    
    curr_dt = datetime.strptime(f"{target_month}-01", "%Y-%m-%d")
    prev_dt = (curr_dt - timedelta(days=1)).replace(day=1)
    next_dt = (curr_dt + timedelta(days=32)).replace(day=1)
    prev_month_str = prev_dt.strftime("%Y-%m")
    next_month_str = next_dt.strftime("%Y-%m")
    year_str, month_str = target_month.split("-")

    summary = db.fetch_monthly_money_summary(target_month, USER_ID)
    records = db.query(
        """
        SELECT * FROM public.money_records
        WHERE user_id = %s AND record_date LIKE %s
        ORDER BY record_date DESC, id DESC
        """,
        (USER_ID, f"{target_month}%")
    )

    records_html = ""
    if not records:
        records_html = '<div class="empty-state">この月の記録はまだありません</div>'
    else:
        for r in records:
            is_income = r["record_type"] == "income"
            sign = "+" if is_income else "-"
            badge_class = "badge-income" if is_income else "badge-expense"
            badge_text = "見込給料" if (is_income and r["status"] == "expected") else ("収入" if is_income else r["category"])
            
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
            
            .summary-card {{ background: white; border-radius: 14px; padding: 20px; box-shadow: 0 3px 12px rgba(0,0,0,0.04); margin-bottom: 20px; }}
            .summary-main {{ text-align: center; margin-bottom: 16px; padding-bottom: 16px; border-bottom: 1px dashed #eee; }}
            .summary-main-label {{ font-size: 0.85rem; color: #7f8c8d; margin-bottom: 4px; }}
            .summary-main-val {{ font-size: 2rem; font-weight: 800; color: #27ae60; }}
            .summary-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; text-align: center; }}
            .summary-sub-label {{ font-size: 0.8rem; color: #7f8c8d; }}
            .summary-sub-val {{ font-size: 1.15rem; font-weight: 700; margin-top: 4px; }}
            .val-expense {{ color: #e74c3c; }}
            .val-balance {{ color: #2980b9; }}
            
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
    
    raw_id = None
    try:
        raw_id = db.save_raw_note(user_id=USER_ID, body=text, source="line")
    except Exception as e:
        print(f"DB Error: {e}")

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

@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image_message(event):
    try:
        with ApiClient(configuration) as api_client:
            blob_client = MessagingApiBlob(api_client)
            image_bytes = blob_client.get_message_content(event.message.id)
    except Exception as e:
        _send_reply(event.reply_token, f"画像の取得に失敗しました💦\n{e}")
        return

    try:
        items = analyze_expense_image(image_bytes)
    except Exception as e:
        _send_reply(event.reply_token, f"明細の読み取りでエラーが出たで💦\n{e}")
        return

    saved_items = []
    skipped_count = 0
    total_amount = 0

    for item in items:
        try:
            rec_date = str(item.get("date") or datetime.now().strftime("%Y-%m-%d")).strip()
            store = str(item.get("store") or "不明な支出").strip()
            amount = int(item.get("amount") or 0)
            category = str(item.get("category") or "その他").strip()
            detail = str(item.get("detail") or "").strip()

            if amount > 0:
                # 重複登録防止チェック（同じ日・同じ店・同じ金額が既にあればスキップ）
                existing = db.query(
                    """
                    SELECT id FROM public.money_records 
                    WHERE user_id = %s AND record_date = %s AND title = %s AND amount = %s AND record_type = 'expense'
                    LIMIT 1
                    """,
                    (USER_ID, rec_date, store, amount)
                )
                if existing:
                    skipped_count += 1
                    continue

                db.insert_money_record(
                    record_date=rec_date,
                    record_type="expense",
                    category=category,
                    title=store,
                    amount=amount,
                    status="confirmed",
                    detail=detail,
                    user_id=USER_ID
                )
                saved_items.append(f"・{store} ({rec_date})\n  ¥{amount:,}（{category}） {detail}".strip())
                total_amount += amount
        except Exception as e:
            print(f"Item save error: {e}")

    if saved_items:
        reply_lines = [f"💳 支出明細 {len(saved_items)}件 を一括記録したで！", ""]
        reply_lines.extend(saved_items)
        if len(saved_items) > 1:
            reply_lines.append("")
            reply_lines.append(f"【今回の支出合計】 ¥{total_amount:,}")
        if skipped_count > 0:
            reply_lines.append(f"\n（※重複していた {skipped_count}件 は自動スキップ済）")
        reply_lines.append("\n家計簿ダッシュボードに即時反映されたで！")
        reply_text = "\n".join(reply_lines)
    elif skipped_count > 0:
        reply_text = f"写っていた支出（{skipped_count}件）は既に登録済みやったで！重複登録は防いでおいたよ👍"
    else:
        reply_text = "支払い完了の支出が見つからんかったで💦（チャージやポイント付与、失敗した取引は自動除外してるよ）"

    _send_reply(event.reply_token, reply_text)

def _send_reply(reply_token: str, text: str):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=text)]
            )
        )
