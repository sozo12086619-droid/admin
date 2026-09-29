"""expense_service.py — 「9/21 セブン 150円」のような1行を支出として読み取る"""

import re

from services.datetext import find_date, remove_span

EXPENSE_CATEGORIES = [
    "食費", "外食費", "日用品", "趣味", "自分磨き",
    "交通費", "ガソリン", "交際費", "衣服", "その他",
]
INCOME_CATEGORIES = ["給料", "バイト", "その他"]

# カテゴリ推定のキーワード表（上から順に判定。元コードの判定順・語をそのまま移した）
_CATEGORY_RULES = [
    ("外食費", ["外食", "レストラン", "居酒屋"]),
    ("食費", ["すき家", "サンエー", "セブン", "ファミリーマート", "ファミマ", "ローソン",
             "ミスタードーナツ", "ミスド", "マック", "スーパー", "食堂", "カフェ", "弁当"]),
    ("日用品", ["ダイソー", "マツモトキヨシ", "マツキヨ", "薬", "ドラッグ", "日用品", "セリア"]),
    ("自分磨き", ["脱毛", "美容", "サロン", "カット", "ジム", "サウナ", "エステ"]),
    ("ガソリン", ["ガソリン", "出光", "eneos", "コスモ"]),
    ("衣服", ["服", "ユニクロ", "gu", "zara", "靴"]),
    ("交際費", ["飲み会", "割り勘", "プレゼント"]),
    ("趣味", ["apple", "amazon", "カイカツ", "快活", "netflix", "spotify", "映画", "プライム"]),
    ("交通費", ["電車", "バス", "タクシー", "定期", "高速"]),
]

_TIME_RANGE_RE = re.compile(r"\d{1,2}(?::\d{2})?\s*[-〜~～]\s*\d{1,2}")
_SUMMARY_LINE_RE = re.compile(r"^(?:合計|小計|PayPay|VISAデビット)\s*[\d,]+円?\s*(?:\(\d+件\))?$")
_BODY_RE = re.compile(r"\s+(?P<title>.+?)\s+(?P<amount>[0-9,]+)\s*円?$")


def guess_category(title: str) -> str:
    t = title.lower()
    for category, keywords in _CATEGORY_RULES:
        if any(k in t for k in keywords):
            return category
    return "その他"


def parse_expense_text(text: str) -> dict | None:
    """支出として読めなければ None。"""
    stripped = text.strip()

    # 「合計 1000円」などのレシートの集計行は無視
    if _SUMMARY_LINE_RE.search(stripped):
        return None

    found = find_date(stripped)
    if not found:
        return None
    date_match, day = found

    # 時間帯（18:00-23:00 など）が含まれる行はシフトなので支出にしない
    if _TIME_RANGE_RE.search(remove_span(stripped, date_match.start(), date_match.end())):
        return None

    body = _BODY_RE.match(stripped[date_match.end():])
    if not body:
        return None

    try:
        amount = int(body.group("amount").replace(",", "").strip())
    except ValueError:
        return None
    if amount <= 0:
        return None

    title = body.group("title").strip()
    return {
        "record_date": day.isoformat(),
        "title": title,
        "amount": amount,
        "category": guess_category(title),
    }
