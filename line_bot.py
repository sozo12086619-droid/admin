import os
import re
import json
import time
import base64
import traceback
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
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

PAST_RECORDS_DATA = [
    # --- 2025年 支出 ---
    ("2025-07-31", "expense", "食費", "食費", 33988),
    ("2025-07-31", "expense", "日用品", "日用品", 880),
    ("2025-07-31", "expense", "交通費", "交通費", 3100),
    ("2025-07-31", "expense", "衣服", "衣服", 4200),
    ("2025-07-31", "expense", "趣味", "趣味", 37900),
    ("2025-07-31", "expense", "その他", "その他", 560),

    ("2025-08-31", "expense", "食費", "食費", 47474),
    ("2025-08-31", "expense", "日用品", "日用品", 3077),
    ("2025-08-31", "expense", "交通費", "交通費", 2800),
    ("2025-08-31", "expense", "交際費", "交際費", 6080),
    ("2025-08-31", "expense", "趣味", "趣味", 144656),
    ("2025-08-31", "expense", "その他", "その他", 2884),

    ("2025-09-30", "expense", "食費", "食費", 27374),
    ("2025-09-30", "expense", "外食費", "外食費", 3834),
    ("2025-09-30", "expense", "日用品", "日用品", 12800),
    ("2025-09-30", "expense", "趣味", "趣味", 90679),
    ("2025-09-30", "expense", "自分磨き", "自分磨き", 400),

    ("2025-10-31", "expense", "食費", "食費", 14201),
    ("2025-10-31", "expense", "日用品", "日用品", 12777),
    ("2025-10-31", "expense", "趣味", "趣味", 34438),
    ("2025-10-31", "expense", "自分磨き", "自分磨き", 102387),
    ("2025-10-31", "expense", "その他", "その他", 41191),

    ("2025-11-30", "expense", "食費", "食費", 10010),
    ("2025-11-30", "expense", "日用品", "日用品", 21950),
    ("2025-11-30", "expense", "交際費", "交際費", 570),
    ("2025-11-30", "expense", "趣味", "趣味", 55694),
    ("2025-11-30", "expense", "自分磨き", "自分磨き", 55398),
    ("2025-11-30", "expense", "その他", "その他", 50000),

    ("2025-12-31", "expense", "食費", "食費", 6799),
    ("2025-12-31", "expense", "日用品", "日用品", 1288),
    ("2025-12-31", "expense", "交際費", "交際費", 4310),
    ("2025-12-31", "expense", "趣味", "趣味", 28093),
    ("2025-12-31", "expense", "自分磨き", "自分磨き", 80791),

    # --- 2026年 支出 ---
    ("2026-01-31", "expense", "食費", "食費", 63458),
    ("2026-01-31", "expense", "日用品", "日用品", 6229),
    ("2026-01-31", "expense", "趣味", "趣味", 122890),
    ("2026-01-31", "expense", "その他", "その他", 750),

    ("2026-02-28", "expense", "食費", "食費", 14517),
    ("2026-02-28", "expense", "外食費", "外食費", 1419),
    ("2026-02-28", "expense", "日用品", "日用品", 6328),
    ("2026-02-28", "expense", "交際費", "交際費", 2234),
    ("2026-02-28", "expense", "趣味", "趣味", 34789),
    ("2026-02-28", "expense", "自分磨き", "自分磨き", 30800),
    ("2026-02-28", "expense", "その他", "その他", 510),

    ("2026-03-31", "expense", "食費", "食費", 19161),
    ("2026-03-31", "expense", "日用品", "日用品", 7574),
    ("2026-03-31", "expense", "交際費", "交際費", 10650),
    ("2026-03-31", "expense", "趣味", "趣味", 71000),
    ("2026-03-31", "expense", "その他", "その他", 9765),

    ("2026-04-30", "expense", "食費", "食費", 17317),
    ("2026-04-30", "expense", "日用品", "日用品", 8999),
    ("2026-04-30", "expense", "趣味", "趣味", 2500),
    ("2026-04-30", "expense", "自分磨き", "自分磨き", 34920),
    ("2026-04-30", "expense", "その他", "その他", 16483),

    ("2026-05-31", "expense", "食費", "食費", 27075),
    ("2026-05-31", "expense", "日用品", "日用品", 15019),
    ("2026-05-31", "expense", "交通費", "交通費", 3100),
    ("2026-05-31", "expense", "交際費", "交際費", 3168),
    ("2026-05-31", "expense", "趣味", "趣味", 41748),
    ("2026-05-31", "expense", "自分磨き", "自分磨き", 24902),
    ("2026-05-31", "expense", "その他", "その他", 14580),

    ("2026-06-30", "expense", "食費", "食費", 27098),
    ("2026-06-30", "expense", "日用品", "日用品", 19159),
    ("2026-06-30", "expense", "交際費", "交際費", 34590),
    ("2026-06-30", "expense", "趣味", "趣味", 3030),
    ("2026-06-30", "expense", "自分磨き", "自分磨き", 79780),
    ("2026-06-30", "expense", "ガソリン", "ガソリン", 3500),
    ("2026-06-30", "expense", "その他", "その他", 2970),

    ("2026-07-31", "expense", "食費", "食費", 33401),
    ("2026-07-31", "expense", "日用品", "日用品", 12000),
    ("2026-07-31", "expense", "交際費", "交際費", 7925),
    ("2026-07-31", "expense", "趣味", "趣味 (Amazon含む)", 14391),
    ("2026-07-31", "expense", "自分磨き", "自分磨き", 34078),
    ("2026-07-31", "expense", "ガソリン", "ガソリン", 4800),

    ("2026-08-31", "expense", "食費", "食費", 22352),
    ("2026-08-31", "expense", "日用品", "日用品", 13028),
    ("2026-08-31", "expense", "交際費", "交際費", 3276),
    ("2026-08-31", "expense", "趣味", "趣味", 69119),
    ("2026-08-31", "expense", "ガソリン", "ガソリン", 4033),
    ("2026-08-31", "expense", "その他", "その他", 160),

    # --- 過去 収入データ ---
    ("2025-07-31", "income", "給料", "給料まとめ", 102419),
    ("2025-08-31", "income", "給料", "給料まとめ", 236937),
    ("2026-01-31", "income", "給料", "給料まとめ", 52313),
    ("2026-02-28", "income", "給料", "給料まとめ", 94947),
    ("2026-03-31", "income", "給料", "給料まとめ", 119087),
    ("2026-04-30", "income", "給料", "給料まとめ", 60557),
    ("2026-05-31", "income", "給料", "給料まとめ", 147402),
    ("2026-06-30", "income", "給料", "給料まとめ", 170708),
    ("2026-07-31", "income", "給料", "給料まとめ", 78204),
    ("2026-08-31", "income", "給料", "給料まとめ", 117308),
]

@app.get("/sync-past")
def sync_past_data_endpoint():
    try:
        db.query(
            "DELETE FROM public.money_records WHERE user_id = %s AND detail = '過去アプリより引き継ぎ'",
            (USER_ID,)
        )
        for rec_date, r_type, cat, title, amt in PAST_RECORDS_DATA:
            db.insert_money_record(
                record_date=rec_date,
                record_type=r_type,
                category=cat,
                title=title,
                amount=amt,
                status="confirmed",
                detail="過去アプリより引き継ぎ",
                user_id=USER_ID
            )
        return RedirectResponse(url="/?_t=" + str(int(time.time())))
    except Exception as e:
        return HTMLResponse(f"<h3>同期エラー: {e}</h3>")

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
    if any(k in t for k in ["外食", "レストラン", "居酒屋"]):
        return "外食費"
    elif any(k in t for k in ["すき家", "サンエー", "セブン", "ファミリーマート", "ファミマ", "ローソン", "ミスタードーナツ", "ミスド", "マック", "スーパー", "食堂", "カフェ", "弁当"]):
        return "食費"
    elif any(k in t for k in ["ダイソー", "マツモトキヨシ", "マツキヨ", "薬", "ドラッグ", "日用品", "セリア"]):
        return "日用品"
    elif any(k in t for k in ["脱毛", "美容", "サロン", "カット", "ジム", "サウナ", "エステ"]):
        return "自分磨き"
    elif any(k in t for k in ["ガソリン", "出光", "eneos", "コスモ"]):
        return "ガソリン"
    elif any(k in t for k in ["服", "ユニクロ", "gu", "zara", "靴"]):
        return "衣服"
    elif any(k in t for k in ["飲み会", "割り勘", "プレゼント"]):
        return "交際費"
    elif any(k in t for k in ["apple", "amazon", "カイカツ", "快活", "netflix", "spotify", "映画", "プライム"]):
        return "趣味"
    elif any(k in t for k in ["電車", "バス", "タクシー", "定期", "高速"]):
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
        f'    "category": "食費" または "外食費" または "日用品" または "趣味" または "自分磨き" または "交通費" または "ガソリン" または "交際費" または "衣服" または "その他",\n'
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
            clean_text = re.sub(r"\s*```$", "", clean_text.strip())
            parsed = json.loads(clean_text)
            if isinstance(parsed, dict):
                return [parsed]
            elif isinstance(parsed, list):
                return parsed
            return []
    except urllib.error.HTTPError as he:
        if he.code == 429:
            raise Exception("⚠️ Google AIの利用制限（1分間に5回まで）に達しました💦 1分ほど待ってからもう一度送信してください！")
        elif he.code == 503:
            raise Exception("⚠️ Google AIサーバーが一時的に混雑しています💦 30秒ほど待ってからもう一度送信してください！")
        else:
            err_msg = he.read().decode("utf-8", errors="ignore")
            raise Exception(f"HTTP {he.code}: {err_msg}")

@app.post("/api/records")
async def add_manual_record(req: Request):
    try:
        data = await req.json()
        rec_date = data.get("record_date")
        rec_type = data.get("record_type", "expense")
        category = data.get("category", "その他")
        title = data.get("title", "").strip() or "手動入力"
        amount = int(data.get("amount", 0))
        detail = data.get("detail", "").strip()

        if amount <= 0 or not rec_date:
            return JSONResponse({"status": "error", "message": "金額と日付は必須です"}, status_code=400)

        db.insert_money_record(
            record_date=rec_date,
            record_type=rec_type,
            category=category,
            title=title,
            amount=amount,
            status="confirmed",
            detail=detail,
            user_id=USER_ID
        )
        return JSONResponse({"status": "success"})
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

@app.delete("/api/records/{record_id}")
async def delete_record(record_id: int):
    try:
        db.query(
            "DELETE FROM public.money_records WHERE id = %s AND user_id = %s",
            (record_id, USER_ID)
        )
        return JSONResponse({"status": "success"})
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

# -------------------------------------------------------------
# 家計簿ダッシュボード画面
# -------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def dashboard(month: str | None = None):
    try:
        target_month = month or datetime.now().strftime("%Y-%m")
        
        curr_dt = datetime.strptime(f"{target_month}-01", "%Y-%m-%d")
        prev_dt = (curr_dt - timedelta(days=1)).replace(day=1)
        next_dt = (curr_dt + timedelta(days=32)).replace(day=1)
        prev_month_str = prev_dt.strftime("%Y-%m")
        next_month_str = next_dt.strftime("%Y-%m")
        year_str, month_str = target_month.split("-")

        # 1. 選択月のサマリー
        summary = db.fetch_monthly_money_summary(target_month, USER_ID)

        # 2. 全期間の通算収支
        all_time_rows = db.query(
            """
            SELECT record_type, COALESCE(SUM(amount), 0) as total
            FROM public.money_records
            WHERE user_id = %s
            GROUP BY record_type
            """,
            (USER_ID,)
        )
        all_time_income = 0
        all_time_expense = 0
        for row in (all_time_rows or []):
            rtype = row.get("record_type") if isinstance(row, dict) else row[0]
            tot = int((row.get("total") if isinstance(row, dict) else row[1]) or 0)
            if rtype == "income":
                all_time_income = tot
            elif rtype == "expense":
                all_time_expense = tot
        all_time_balance = all_time_income - all_time_expense

        # 3. 2026年の年間累計収入（扶養チェック用）
        income_2026_rows = db.query(
            """
            SELECT COALESCE(SUM(amount), 0) as total
            FROM public.money_records
            WHERE user_id = %s AND record_type = 'income' AND record_date::text LIKE %s
            """,
            (USER_ID, "2026%")
        )
        ytd_income_2026 = 0
        if income_2026_rows and len(income_2026_rows) > 0:
            first_row = income_2026_rows[0]
            val = first_row.get("total") if isinstance(first_row, dict) else first_row[0]
            ytd_income_2026 = int(val or 0)

        limit_103 = 1030000
        rem_103 = limit_103 - ytd_income_2026
        pct_103 = min(100.0, round((ytd_income_2026 / limit_103) * 100, 1))

        # 4. 月別推移（直近15ヶ月分）
        monthly_trends = db.query(
            """
            SELECT 
                SUBSTRING(record_date::text, 1, 7) as ym,
                COALESCE(SUM(CASE WHEN record_type = 'income' THEN amount ELSE 0 END), 0) as inc,
                COALESCE(SUM(CASE WHEN record_type = 'expense' THEN amount ELSE 0 END), 0) as exp
            FROM public.money_records
            WHERE user_id = %s
            GROUP BY SUBSTRING(record_date::text, 1, 7)
            ORDER BY ym ASC
            LIMIT 15
            """,
            (USER_ID,)
        )
        trend_labels = []
        trend_incomes = []
        trend_expenses = []
        for r in (monthly_trends or []):
            ym_val = r.get("ym") if isinstance(r, dict) else r[0]
            inc_val = r.get("inc") if isinstance(r, dict) else r[1]
            exp_val = r.get("exp") if isinstance(r, dict) else r[2]
            trend_labels.append(str(ym_val or ""))
            trend_incomes.append(int(inc_val or 0))
            trend_expenses.append(int(exp_val or 0))

        # 5. 当月のカテゴリ別支出内訳 & カラーパレット
        category_rows = db.query(
            """
            SELECT category, COALESCE(SUM(amount), 0) as cat_total
            FROM public.money_records
            WHERE user_id = %s AND record_date::text LIKE %s AND record_type = 'expense'
            GROUP BY category
            ORDER BY cat_total DESC
            """,
            (USER_ID, f"{target_month}%")
        )

        CAT_PALETTE = {
            "食費": "#10b981",       # 鮮やかなグリーン
            "外食費": "#f59e0b",     # 鮮やかなオレンジ
            "日用品": "#06b6d4",     # 爽快なシアンブルー
            "趣味": "#ef4444",       # レッド
            "趣味・娯楽": "#ef4444",  # レッド
            "自分磨き": "#3b82f6",   # ブルー
            "交際費": "#eab308",     # イエロー
            "交通費": "#ec4899",     # ピンク
            "ガソリン": "#14b8a6",   # ターコイズ
            "衣服": "#8b5cf6",       # パープル
            "その他": "#84cc16",     # ライムグリーン
        }
        FALLBACK_COLORS = ["#f97316", "#06b6d4", "#a855f7", "#ec4899", "#14b8a6", "#3b82f6"]

        cat_labels = []
        cat_data = []
        cat_colors = []
        total_exp_month = (summary.get("expenses") if isinstance(summary, dict) else 0) or 1

        category_list_html = ""
        for i, r in enumerate(category_rows or []):
            c_name = str((r.get("category") if isinstance(r, dict) else r[0]) or "その他")
            c_amt = int((r.get("cat_total") if isinstance(r, dict) else r[1]) or 0)
            cat_labels.append(c_name)
            cat_data.append(c_amt)
            color = CAT_PALETTE.get(c_name, FALLBACK_COLORS[i % len(FALLBACK_COLORS)])
            cat_colors.append(color)

            pct = round((c_amt / total_exp_month) * 100, 1)
            category_list_html += f"""
            <div class="cat-row">
                <div class="cat-row-left">
                    <span class="cat-color-dot" style="background-color: {color};"></span>
                    <span class="cat-row-name">{c_name}</span>
                </div>
                <div class="cat-row-right">
                    <span class="cat-row-pct">{pct}%</span>
                    <span class="cat-row-amt">¥{c_amt:,}</span>
                </div>
            </div>
            """

        category_card_html = ""
        if cat_data:
            category_card_html = f"""
            <div class="chart-card">
                <div class="chart-title">🍩 {month_str}月 支出割合・内訳</div>
                <div style="max-width: 250px; margin: 0 auto 12px auto;">
                    <canvas id="categoryChart" height="240"></canvas>
                </div>
                <div class="category-list">
                    {category_list_html}
                </div>
            </div>
            """

        # 6. 当月の取引レコード一覧
        records = db.query(
            """
            SELECT * FROM public.money_records
            WHERE user_id = %s AND record_date::text LIKE %s
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
                <div class="record-card" id="rec-{r['id']}">
                    <div class="record-left">
                        <span class="badge {badge_class}">{badge_text}</span>
                        <span class="record-title">{r["title"]}</span>
                        <div class="record-date">{r["record_date"]}</div>
                        {detail_line}
                    </div>
                    <div class="record-right">
                        <div class="record-amount {'amount-income' if is_income else 'amount-expense'}">
                            {sign}¥{r["amount"]:,}
                        </div>
                        <button class="delete-btn" onclick="deleteRecord({r['id']})" title="削除">✕</button>
                    </div>
                </div>
                """

        today_str = datetime.now().strftime("%Y-%m-%d")
        bal_color = "#38bdf8" if all_time_balance >= 0 else "#f87171"
        rem_color = "#ef4444" if rem_103 < 0 else "#2563eb"

        html_content = f"""
        <!DOCTYPE html>
        <html lang="ja">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
            <title>家計簿 & シフト管理</title>
            <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
            <style>
                * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
                body {{ background-color: #f1f5f9; color: #1e293b; padding-bottom: 70px; }}
                
                .header {{ 
                    background: #0f172a; 
                    color: white; 
                    padding: 14px 18px; 
                    display: flex; 
                    justify-content: space-between; 
                    align-items: center; 
                    position: sticky; 
                    top: 0; 
                    z-index: 100; 
                    box-shadow: 0 2px 10px rgba(0,0,0,0.15); 
                }}
                .header h1 {{ font-size: 1rem; font-weight: 700; }}
                .header-actions {{ display: flex; gap: 6px; }}
                .btn-action {{
                    border: none;
                    padding: 7px 11px;
                    border-radius: 8px;
                    font-size: 0.78rem;
                    font-weight: 700;
                    cursor: pointer;
                    transition: transform 0.1s;
                }}
                .btn-action:active {{ transform: scale(0.95); }}
                .btn-sync {{ background: #059669; color: white; }}
                .btn-reload {{ background: #334155; color: #e2e8f0; }}
                .btn-add {{ background: #2563eb; color: white; }}

                .container {{ max-width: 550px; margin: 0 auto; padding: 14px; }}

                .fuyou-card {{
                    background: white;
                    border-radius: 14px;
                    padding: 16px;
                    margin-bottom: 14px;
                    box-shadow: 0 2px 6px rgba(0,0,0,0.04);
                    border-left: 5px solid #2563eb;
                }}
                .fuyou-title {{ font-size: 0.85rem; font-weight: 700; color: #1e293b; display: flex; justify-content: space-between; }}
                .fuyou-meter-bg {{ background: #e2e8f0; height: 10px; border-radius: 5px; margin: 10px 0 8px 0; overflow: hidden; }}
                .fuyou-meter-bar {{ background: linear-gradient(90deg, #10b981, #f59e0b, #ef4444); height: 100%; border-radius: 5px; }}
                .fuyou-desc {{ font-size: 0.78rem; color: #64748b; display: flex; justify-content: space-between; }}

                .all-time-card {{ background: linear-gradient(135deg, #1e293b, #0f172a); color: white; border-radius: 16px; padding: 18px 20px; margin-bottom: 14px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }}
                .all-time-title {{ font-size: 0.75rem; color: #94a3b8; letter-spacing: 0.5px; margin-bottom: 4px; }}
                .all-time-balance {{ font-size: 2.1rem; font-weight: 800; color: {bal_color}; }}
                .all-time-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 12px; padding-top: 10px; border-top: 1px solid rgba(255,255,255,0.12); font-size: 0.82rem; }}
                .all-time-grid span {{ color: #94a3b8; display: block; font-size: 0.72rem; }}

                .month-nav {{ display: flex; justify-content: space-between; align-items: center; background: white; padding: 12px 18px; margin-bottom: 14px; border-radius: 12px; box-shadow: 0 1px 4px rgba(0,0,0,0.03); }}
                .month-nav a {{ text-decoration: none; color: #2563eb; font-size: 0.88rem; font-weight: 700; padding: 6px 14px; border-radius: 8px; background: #eff6ff; }}
                .current-month {{ font-size: 1.15rem; font-weight: 800; color: #0f172a; }}

                .summary-card {{ background: white; border-radius: 14px; padding: 16px; box-shadow: 0 2px 6px rgba(0,0,0,0.04); margin-bottom: 14px; }}
                .summary-main {{ text-align: center; margin-bottom: 12px; padding-bottom: 12px; border-bottom: 1px dashed #e2e8f0; }}
                .summary-main-label {{ font-size: 0.78rem; color: #64748b; margin-bottom: 2px; }}
                .summary-main-val {{ font-size: 1.7rem; font-weight: 800; color: #10b981; }}
                .summary-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; text-align: center; }}
                .summary-sub-label {{ font-size: 0.75rem; color: #64748b; }}
                .summary-sub-val {{ font-size: 1.1rem; font-weight: 700; margin-top: 2px; }}
                .val-expense {{ color: #ef4444; }}
                .val-balance {{ color: #0284c7; }}

                .chart-card {{ background: white; border-radius: 14px; padding: 16px; margin-bottom: 14px; box-shadow: 0 2px 6px rgba(0,0,0,0.04); }}
                .chart-title {{ font-size: 0.9rem; font-weight: 700; color: #1e293b; margin-bottom: 12px; }}

                .category-list {{ margin-top: 14px; border-top: 1px solid #f1f5f9; padding-top: 10px; }}
                .cat-row {{ display: flex; justify-content: space-between; align-items: center; padding: 9px 4px; border-bottom: 1px solid #f8fafc; }}
                .cat-row:last-child {{ border-bottom: none; }}
                .cat-row-left {{ display: flex; align-items: center; gap: 8px; }}
                .cat-color-dot {{ width: 12px; height: 12px; border-radius: 50%; display: inline-block; }}
                .cat-row-name {{ font-size: 0.88rem; font-weight: 600; color: #1e293b; }}
                .cat-row-right {{ display: flex; align-items: center; gap: 12px; }}
                .cat-row-pct {{ font-size: 0.8rem; color: #64748b; min-width: 42px; text-align: right; }}
                .cat-row-amt {{ font-size: 0.92rem; font-weight: 700; color: #0f172a; min-width: 75px; text-align: right; }}

                .section-title {{ font-size: 0.92rem; font-weight: 700; color: #475569; margin: 18px 0 10px 4px; }}
                .record-card {{ background: white; border-radius: 12px; padding: 12px 14px; display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.02); }}
                .record-left {{ display: flex; flex-direction: column; gap: 2px; }}
                .record-title {{ font-size: 0.92rem; font-weight: 700; color: #0f172a; margin-left: 2px; }}
                .record-date {{ font-size: 0.7rem; color: #94a3b8; }}
                .record-detail {{ font-size: 0.72rem; color: #64748b; }}
                .badge {{ font-size: 0.65rem; padding: 2px 6px; border-radius: 4px; font-weight: 700; width: fit-content; }}
                .badge-income {{ background: #ecfdf5; color: #059669; }}
                .badge-expense {{ background: #fef2f2; color: #dc2626; }}
                .record-right {{ display: flex; align-items: center; gap: 10px; }}
                .record-amount {{ font-size: 1rem; font-weight: 800; white-space: nowrap; }}
                .amount-income {{ color: #059669; }}
                .amount-expense {{ color: #dc2626; }}
                .delete-btn {{ background: none; border: none; color: #cbd5e1; cursor: pointer; font-size: 0.85rem; padding: 4px; }}
                .delete-btn:hover {{ color: #dc2626; }}
                .empty-state {{ text-align: center; padding: 24px; color: #94a3b8; font-size: 0.85rem; background: white; border-radius: 12px; }}

                .modal-overlay {{ display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); z-index: 200; justify-content: center; align-items: center; padding: 16px; }}
                .modal-content {{ background: white; border-radius: 16px; padding: 22px; width: 100%; max-width: 440px; box-shadow: 0 10px 25px rgba(0,0,0,0.2); }}
                .modal-title {{ font-size: 1.1rem; font-weight: 700; margin-bottom: 14px; color: #0f172a; display: flex; justify-content: space-between; }}
                .form-group {{ margin-bottom: 12px; }}
                .form-label {{ display: block; font-size: 0.75rem; font-weight: 700; color: #64748b; margin-bottom: 4px; }}
                .form-control {{ width: 100%; padding: 10px 12px; border: 1px solid #cbd5e1; border-radius: 8px; font-size: 0.95rem; font-family: inherit; }}
                .form-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
                .btn-submit {{ width: 100%; background: #2563eb; color: white; border: none; padding: 12px; border-radius: 10px; font-size: 1rem; font-weight: 700; cursor: pointer; margin-top: 10px; }}
                .btn-close {{ background: none; border: none; font-size: 1.2rem; cursor: pointer; color: #94a3b8; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>家計簿 & シフト管理</h1>
                <div class="header-actions">
                    <button class="btn-action btn-sync" onclick="location.href='/sync-past'">📥 過去データ同期</button>
                    <button class="btn-action btn-add" onclick="openModal()">➕ 手入力</button>
                    <button class="btn-action btn-reload" onclick="forceReload()">🔄</button>
                </div>
            </div>

            <div class="container">
                <div class="fuyou-card">
                    <div class="fuyou-title">
                        <span>📋 2026年 扶養管理（103万目安）</span>
                        <strong style="color: {rem_color};">{pct_103}%</strong>
                    </div>
                    <div class="fuyou-meter-bg">
                        <div class="fuyou-meter-bar" style="width: {pct_103}%;"></div>
                    </div>
                    <div class="fuyou-desc">
                        <span>累計収入: ¥{ytd_income_2026:,}</span>
                        <span>103万まで残り: <strong>¥{max(0, rem_103):,}</strong></span>
                    </div>
                </div>

                <div class="all-time-card">
                    <div class="all-time-title">💰 全期間の通算残高（総収支）</div>
                    <div class="all-time-balance">¥{all_time_balance:,}</div>
                    <div class="all-time-grid">
                        <div>
                            <span>通算総収入</span>
                            <strong>+¥{all_time_income:,}</strong>
                        </div>
                        <div>
                            <span>通算総支出</span>
                            <strong style="color: #fca5a5;">-¥{all_time_expense:,}</strong>
                        </div>
                    </div>
                </div>

                <div class="chart-card">
                    <div class="chart-title">📊 月別 収支推移（収入 vs 支出）</div>
                    <canvas id="monthlyTrendChart" height="150"></canvas>
                </div>

                <div class="month-nav">
                    <a href="/?month={prev_month_str}">◀ 前月</a>
                    <div class="current-month">{year_str}年 {month_str}月</div>
                    <a href="/?month={next_month_str}">翌月 ▶</a>
                </div>

                <div class="summary-card">
                    <div class="summary-main">
                        <div class="summary-main-label">{month_str}月 バイト給料（見込含む）</div>
                        <div class="summary-main-val">¥{summary.get("total_income", 0):,}</div>
                    </div>
                    <div class="summary-grid">
                        <div>
                            <div class="summary-sub-label">支出合計</div>
                            <div class="summary-sub-val val-expense">¥{summary.get("expenses", 0):,}</div>
                        </div>
                        <div>
                            <div class="summary-sub-label">今月の差引残高</div>
                            <div class="summary-sub-val val-balance">¥{summary.get("balance", 0):,}</div>
                        </div>
                    </div>
                </div>

                {category_card_html}

                <div class="section-title">登録済みレコード一覧（{len(records or [])}件）</div>
                {records_html}
            </div>

            <div class="modal-overlay" id="manualModal">
                <div class="modal-content">
                    <div class="modal-title">
                        <span>収支を手動入力</span>
                        <button class="btn-close" onclick="closeModal()">✕</button>
                    </div>
                    <form id="recordForm" onsubmit="submitManualRecord(event)">
                        <div class="form-row">
                            <div class="form-group">
                                <label class="form-label">日付</label>
                                <input type="date" class="form-control" id="f_date" value="{today_str}" required>
                            </div>
                            <div class="form-group">
                                <label class="form-label">収支タイプ</label>
                                <select class="form-control" id="f_type" onchange="toggleType()">
                                    <option value="expense">支出 (-)</option>
                                    <option value="income">収入 (+)</option>
                                </select>
                            </div>
                        </div>
                        <div class="form-group">
                            <label class="form-label">カテゴリ</label>
                            <select class="form-control" id="f_category">
                                <option value="食費">食費</option>
                                <option value="外食費">外食費</option>
                                <option value="日用品">日用品</option>
                                <option value="趣味">趣味</option>
                                <option value="自分磨き">自分磨き</option>
                                <option value="交際費">交際費</option>
                                <option value="交通費">交通費</option>
                                <option value="ガソリン">ガソリン</option>
                                <option value="衣服">衣服</option>
                                <option value="その他">その他</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label class="form-label">店名・項目名</label>
                            <input type="text" class="form-control" id="f_title" placeholder="例: セブン-イレブン、給料など" required>
                        </div>
                        <div class="form-group">
                            <label class="form-label">金額（円）</label>
                            <input type="number" class="form-control" id="f_amount" placeholder="例: 1500" required>
                        </div>
                        <div class="form-group">
                            <label class="form-label">メモ・詳細（任意）</label>
                            <input type="text" class="form-control" id="f_detail" placeholder="例: 友達とお茶">
                        </div>
                        <button type="submit" class="btn-submit">登録する</button>
                    </form>
                </div>
            </div>

            <script>
                function forceReload() {{
                    const url = new URL(window.location.href);
                    url.searchParams.set('_t', Date.now());
                    window.location.href = url.toString();
                }}

                function openModal() {{
                    document.getElementById('manualModal').style.display = 'flex';
                }}

                function closeModal() {{
                    document.getElementById('manualModal').style.display = 'none';
                }}

                function toggleType() {{
                    const t = document.getElementById('f_type').value;
                    const cat = document.getElementById('f_category');
                    if (t === 'income') {{
                        cat.innerHTML = '<option value="給料">給料</option><option value="バイト">バイト</option><option value="臨時収入">臨時収入</option><option value="その他">その他</option>';
                    }} else {{
                        cat.innerHTML = `
                            <option value="食費">食費</option>
                            <option value="外食費">外食費</option>
                            <option value="日用品">日用品</option>
                            <option value="趣味">趣味</option>
                            <option value="自分磨き">自分磨き</option>
                            <option value="交際費">交際費</option>
                            <option value="交通費">交通費</option>
                            <option value="ガソリン">ガソリン</option>
                            <option value="衣服">衣服</option>
                            <option value="その他">その他</option>
                        `;
                    }}
                }}

                async function submitManualRecord(e) {{
                    e.preventDefault();
                    const payload = {{
                        record_date: document.getElementById('f_date').value,
                        record_type: document.getElementById('f_type').value,
                        category: document.getElementById('f_category').value,
                        title: document.getElementById('f_title').value,
                        amount: parseInt(document.getElementById('f_amount').value),
                        detail: document.getElementById('f_detail').value
                    }};

                    try {{
                        const res = await fetch('/api/records', {{
                            method: 'POST',
                            headers: {{ 'Content-Type': 'application/json' }},
                            body: JSON.stringify(payload)
                        }});
                        if (res.ok) {{
                            const ym = payload.record_date.substring(0, 7);
                            window.location.href = '/?month=' + ym + '&_t=' + Date.now();
                        }} else {{
                            alert('登録に失敗しました💦');
                        }}
                    }} catch (err) {{
                        alert('通信エラー: ' + err);
                    }}
                }}

                async function deleteRecord(id) {{
                    if (!confirm('この明細を削除してもよろしいですか？')) return;
                    try {{
                        const res = await fetch('/api/records/' + id, {{ method: 'DELETE' }});
                        if (res.ok) {{
                            const el = document.getElementById('rec-' + id);
                            if (el) el.remove();
                            forceReload();
                        }} else {{
                            alert('削除に失敗しました💦');
                        }}
                    }} catch (err) {{
                        alert('通信エラー: ' + err);
                    }}
                }}

                const trendCtx = document.getElementById('monthlyTrendChart').getContext('2d');
                new Chart(trendCtx, {{
                    type: 'bar',
                    data: {{
                        labels: {json.dumps(trend_labels)},
                        datasets: [
                            {{
                                label: '収入',
                                data: {json.dumps(trend_incomes)},
                                backgroundColor: '#10b981',
                                borderRadius: 4
                            }},
                            {{
                                label: '支出',
                                data: {json.dumps(trend_expenses)},
                                backgroundColor: '#ef4444',
                                borderRadius: 4
                            }}
                        ]
                    }},
                    options: {{
                        responsive: true,
                        plugins: {{
                            legend: {{ position: 'bottom', labels: {{ boxWidth: 12 }} }}
                        }},
                        scales: {{
                            y: {{
                                beginAtZero: true,
                                ticks: {{ callback: function(val) {{ return '¥' + val.toLocaleString(); }} }}
                            }}
                        }}
                    }}
                }});

                const catCanvas = document.getElementById('categoryChart');
                if (catCanvas) {{
                    new Chart(catCanvas.getContext('2d'), {{
                        type: 'doughnut',
                        data: {{
                            labels: {json.dumps(cat_labels)},
                            datasets: [{{
                                data: {json.dumps(cat_data)},
                                backgroundColor: {json.dumps(cat_colors)},
                                borderWidth: 2,
                                borderColor: '#ffffff'
                            }}]
                        }},
                        options: {{
                            responsive: true,
                            cutout: '58%',
                            plugins: {{
                                legend: {{ display: false }}
                            }}
                        }}
                    }});
                }}
            </script>
        </body>
        </html>
        """
        return html_content
    except Exception as e:
        err_msg = traceback.format_exc()
        return HTMLResponse(f"""
        <html>
        <body style="font-family: sans-serif; padding: 20px; background: #fff5f5;">
            <h2 style="color: #c53030;">画面生成エラー</h2>
            <pre style="background: white; padding: 15px; border-radius: 8px; border: 1px solid #feb2b2; overflow: auto;">{err_msg}</pre>
        </body>
        </html>
        """, status_code=500)

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

    lines = [line.strip() for line in text.split("\n") if line.strip()]
    
    calendar_success = []
    calendar_error = None
    total_expected_salary = 0

    expense_success = []
    skipped_expense_count = 0
    total_expense_amount = 0

    for line in lines:
        parsed_shift = parse_shift_text(line)
        if parsed_shift:
            try:
                add_event_to_calendar(parsed_shift)
                sal = parsed_shift['salary']
                total_expected_salary += sal['total_pay']
                
                detail_text = f"{parsed_shift['time_str']} (昼{sal['day_hours']}h/深夜{sal['night_hours']}h)"
                db.insert_money_record(
                    record_date=parsed_shift["record_date"],
                    record_type="income",
                    category="バイト",
                    title=parsed_shift["summary"],
                    amount=sal["total_pay"],
                    status="expected",
                    detail=detail_text,
                    raw_note_id=raw_id,
                    user_id=USER_ID
                )
                detail = f"・{parsed_shift['date_str']} {parsed_shift['time_str']} {parsed_shift['summary']}\n  💰見込: ¥{sal['total_pay']:,} (昼{sal['day_hours']}h / 深夜{sal['night_hours']}h)"
                calendar_success.append(detail)
            except Exception as e:
                calendar_error = str(e)
                print(f"Calendar / DB Error: {e}")
            continue

        parsed_exp = parse_expense_text(line)
        if parsed_exp:
            try:
                existing = db.query(
                    """
                    SELECT id FROM public.money_records 
                    WHERE user_id = %s AND record_date::text = %s AND title = %s AND amount = %s AND record_type = 'expense'
                    LIMIT 1
                    """,
                    (USER_ID, parsed_exp["record_date"], parsed_exp["title"], parsed_exp["amount"])
                )
                if existing:
                    skipped_expense_count += 1
                    continue

                db.insert_money_record(
                    record_date=parsed_exp["record_date"],
                    record_type="expense",
                    category=parsed_exp["category"],
                    title=parsed_exp["title"],
                    amount=parsed_exp["amount"],
                    status="confirmed",
                    detail="",
                    raw_note_id=raw_id,
                    user_id=USER_ID
                )
                expense_success.append(f"・{parsed_exp['record_date'][5:]} {parsed_exp['title']} ¥{parsed_exp['amount']:,}（{parsed_exp['category']}）")
                total_expense_amount += parsed_exp["amount"]
            except Exception as e:
                print(f"Expense DB Error: {e}")

    reply_lines = []

    if expense_success or skipped_expense_count > 0:
        reply_lines.append(f"💳 支出明細 {len(expense_success)}件 を一括記録したで！💰")
        reply_lines.append("")
        if len(expense_success) <= 15:
            reply_lines.extend(expense_success)
        else:
            reply_lines.extend(expense_success[:8])
            reply_lines.append(f"…ほか {len(expense_success) - 8}件")
        
        reply_lines.append("")
        reply_lines.append(f"【支出合計】 ¥{total_expense_amount:,}")
        if skipped_expense_count > 0:
            reply_lines.append(f"（※重複登録を防ぐため {skipped_expense_count}件 はスキップ済）")
        reply_lines.append("\n家計簿ダッシュボードに即時反映されたで！")

    elif calendar_success:
        reply_lines = ["カレンダー & 家計簿に登録したで！📅💰", ""]
        reply_lines.extend(calendar_success)
        if len(calendar_success) > 1:
            reply_lines.append("")
            reply_lines.append(f"【今回の一括合計】 ¥{total_expected_salary:,}")
        reply_lines.append("\n（カレンダーは予定名のみスッキリ反映済！）")
        if calendar_error:
            reply_lines.append(f"\n※一部エラー: {calendar_error}")

    elif calendar_error:
        reply_lines = [f"メモは保存したけどカレンダー登録でエラーが出たで💦\n{calendar_error}"]
    elif raw_id:
        reply_lines = [f"メモを受け取ったで！\n「{text}」\n(ID: {raw_id})"]
    else:
        reply_lines = [f"メモを受け取ったで！\n「{text}」"]

    reply_text = "\n".join(reply_lines)

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
        _send_reply(event.reply_token, str(e))
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
                existing = db.query(
                    """
                    SELECT id FROM public.money_records 
                    WHERE user_id = %s AND record_date::text = %s AND title = %s AND amount = %s AND record_type = 'expense'
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
