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

# -------------------------------------------------------------
# 家計簿ダッシュボード（視覚化＆グラフ完全対応）
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
    for row in all_time_rows:
        if row["record_type"] == "income":
            all_time_income = int(row["total"])
        elif row["record_type"] == "expense":
            all_time_expense = int(row["total"])
    all_time_balance = all_time_income - all_time_expense

    # 3. 月別推移（直近12ヶ月分）
    monthly_trends = db.query(
        """
        SELECT 
            SUBSTRING(record_date, 1, 7) as ym,
            COALESCE(SUM(CASE WHEN record_type = 'income' THEN amount ELSE 0 END), 0) as inc,
            COALESCE(SUM(CASE WHEN record_type = 'expense' THEN amount ELSE 0 END), 0) as exp
        FROM public.money_records
        WHERE user_id = %s
        GROUP BY SUBSTRING(record_date, 1, 7)
        ORDER BY ym ASC
        LIMIT 12
        """,
        (USER_ID,)
    )
    trend_labels = [r["ym"] for r in monthly_trends]
    trend_incomes = [int(r["inc"]) for r in monthly_trends]
    trend_expenses = [int(r["exp"]) for r in monthly_trends]

    # 4. 当月のカテゴリ別支出内訳
    category_rows = db.query(
        """
        SELECT category, COALESCE(SUM(amount), 0) as cat_total
        FROM public.money_records
        WHERE user_id = %s AND record_date LIKE %s AND record_type = 'expense'
        GROUP BY category
        ORDER BY cat_total DESC
        """,
        (USER_ID, f"{target_month}%")
    )
    cat_labels = [r["category"] for r in category_rows]
    cat_data = [int(r["cat_total"]) for r in category_rows]

    # 5. 当月の取引レコード一覧
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
        <title>家計簿 & シフト管理ダッシュボード</title>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
            * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
            body {{ background-color: #f4f6f9; color: #333; padding-bottom: 50px; }}
            .header {{ background: #1e293b; color: white; padding: 16px 20px; text-align: center; position: sticky; top: 0; z-index: 10; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
            .header h1 {{ font-size: 1.15rem; font-weight: 700; letter-spacing: 0.5px; }}
            
            .container {{ max-width: 550px; margin: 0 auto; padding: 16px; }}

            /* 全期間サマリー */
            .all-time-card {{ background: linear-gradient(135deg, #1e293b, #334155); color: white; border-radius: 16px; padding: 18px 20px; margin-bottom: 16px; box-shadow: 0 4px 14px rgba(30,41,59,0.15); }}
            .all-time-title {{ font-size: 0.8rem; color: #cbd5e1; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }}
            .all-time-balance {{ font-size: 2.1rem; font-weight: 800; color: {'#38bdf8' if all_time_balance >= 0 else '#f87171'}; }}
            .all-time-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 14px; padding-top: 12px; border-top: 1px solid rgba(255,255,255,0.1); font-size: 0.85rem; }}
            .all-time-grid span {{ color: #94a3b8; display: block; font-size: 0.75rem; }}

            /* 月ナビゲーション */
            .month-nav {{ display: flex; justify-content: space-between; align-items: center; background: white; padding: 12px 18px; margin-bottom: 14px; border-radius: 14px; box-shadow: 0 2px 6px rgba(0,0,0,0.03); }}
            .month-nav a {{ text-decoration: none; color: #2563eb; font-size: 0.9rem; font-weight: 700; padding: 6px 14px; border-radius: 8px; background: #eff6ff; }}
            .current-month {{ font-size: 1.15rem; font-weight: 700; color: #0f172a; }}

            /* 当月カード */
            .summary-card {{ background: white; border-radius: 14px; padding: 18px; box-shadow: 0 2px 8px rgba(0,0,0,0.04); margin-bottom: 16px; }}
            .summary-main {{ text-align: center; margin-bottom: 14px; padding-bottom: 14px; border-bottom: 1px dashed #e2e8f0; }}
            .summary-main-label {{ font-size: 0.8rem; color: #64748b; margin-bottom: 4px; }}
            .summary-main-val {{ font-size: 1.8rem; font-weight: 800; color: #10b981; }}
            .summary-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; text-align: center; }}
            .summary-sub-label {{ font-size: 0.75rem; color: #64748b; }}
            .summary-sub-val {{ font-size: 1.1rem; font-weight: 700; margin-top: 3px; }}
            .val-expense {{ color: #ef4444; }}
            .val-balance {{ color: #0284c7; }}

            /* グラフカード */
            .chart-card {{ background: white; border-radius: 14px; padding: 16px; margin-bottom: 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.04); }}
            .chart-title {{ font-size: 0.9rem; font-weight: 700; color: #334155; margin-bottom: 12px; }}

            /* リスト一覧 */
            .section-title {{ font-size: 0.95rem; font-weight: 700; color: #475569; margin: 18px 0 10px 4px; }}
            .record-card {{ background: white; border-radius: 12px; padding: 13px 16px; display: flex; justify-content: space-between; align-items: center; margin-bottom: 9px; box-shadow: 0 2px 5px rgba(0,0,0,0.02); }}
            .record-left {{ display: flex; flex-direction: column; gap: 3px; }}
            .record-title {{ font-size: 0.95rem; font-weight: 700; color: #1e293b; margin-left: 3px; }}
            .record-date {{ font-size: 0.72rem; color: #94a3b8; }}
            .record-detail {{ font-size: 0.75rem; color: #64748b; margin-top: 1px; }}
            .badge {{ font-size: 0.68rem; padding: 2px 6px; border-radius: 4px; font-weight: 700; width: fit-content; }}
            .badge-income {{ background: #ecfdf5; color: #059669; }}
            .badge-expense {{ background: #fef2f2; color: #dc2626; }}
            .record-amount {{ font-size: 1.05rem; font-weight: 800; white-space: nowrap; }}
            .amount-income {{ color: #059669; }}
            .amount-expense {{ color: #dc2626; }}
            .empty-state {{ text-align: center; padding: 26px; color: #94a3b8; font-size: 0.85rem; background: white; border-radius: 12px; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>家計簿 & シフト管理</h1>
        </div>

        <div class="container">
            <!-- 全期間の通算収支 -->
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

            <!-- 月別推移グラフ -->
            <div class="chart-card">
                <div class="chart-title">📊 月別 収支推移</div>
                <canvas id="monthlyTrendChart" height="150"></canvas>
            </div>

            <!-- 当月のナビゲーション -->
            <div class="month-nav">
                <a href="/?month={prev_month_str}">◀ 前月</a>
                <div class="current-month">{year_str}年 {month_str}月</div>
                <a href="/?month={next_month_str}">翌月 ▶</a>
            </div>

            <!-- 当月のサマリーカード -->
            <div class="summary-card">
                <div class="summary-main">
                    <div class="summary-main-label">{month_str}月 バイト給料（見込）</div>
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

            <!-- 当月のカテゴリ別支出内訳グラフ -->
            {f'''
            <div class="chart-card">
                <div class="chart-title">🍩 {month_str}月 支出内訳</div>
                <canvas id="categoryChart" height="140"></canvas>
            </div>
            ''' if cat_data else ''}

            <!-- 履歴リスト -->
            <div class="section-title">登録済みのシフト・収支一覧（{len(records)}件）</div>
            {records_html}
        </div>

        <script>
            // 月別推移バーチャート
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

            // カテゴリ別支出ドーナツチャート
            const catCanvas = document.getElementById('categoryChart');
            if (catCanvas) {{
                new Chart(catCanvas.getContext('2d'), {{
                    type: 'doughnut',
                    data: {{
                        labels: {json.dumps(cat_labels)},
                        datasets: [{{
                            data: {json.dumps(cat_data)},
                            backgroundColor: ['#3b82f6', '#ec4899', '#f59e0b', '#10b981', '#8b5cf6', '#64748b']
                        }}]
                    }},
                    options: {{
                        responsive: true,
                        plugins: {{
                            legend: {{ position: 'right', labels: {{ boxWidth: 12, font: {{ size: 11 }} }} }}
                        }}
                    }}
                }});
            }}
        </script>
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
                    WHERE user_id = %s AND record_date = %s AND title = %s AND amount = %s AND record_type = 'expense'
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
