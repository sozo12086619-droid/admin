"""
dashboard_service.py — ダッシュボードに表示するデータを組み立てる

DB から取り出した生のデータを「画面でそのまま使える形」に整える。
HTML は一切ここで作らない（見た目は templates/dashboard.html の仕事）。
"""

import re
from collections import OrderedDict
from datetime import date, timedelta

import config
import db
import timeutil
from services.expense_service import EXPENSE_CATEGORIES, INCOME_CATEGORIES

WEEKDAYS = "月火水木金土日"

CATEGORY_COLORS = {
    "食費": "#10b981", "外食費": "#f59e0b", "日用品": "#06b6d4",
    "趣味": "#ef4444", "自分磨き": "#3b82f6", "交際費": "#eab308",
    "交通費": "#ec4899", "ガソリン": "#14b8a6", "衣服": "#8b5cf6", "その他": "#84cc16",
}
FALLBACK_COLORS = ["#f97316", "#06b6d4", "#a855f7", "#ec4899", "#14b8a6", "#3b82f6"]

# 過去データの一括取り込み時に付けた定型文。明細に出すとノイズなので隠す
_HIDDEN_DETAILS = {"過去アプリより引き継ぎ"}


def _color_for(name: str, index: int = 0) -> str:
    return CATEGORY_COLORS.get(name) or FALLBACK_COLORS[index % len(FALLBACK_COLORS)]


def _soft(hex_color: str, alpha: float = 0.14) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _parse_month(value: str | None) -> date | None:
    if value and re.fullmatch(r"\d{4}-\d{2}", value):
        try:
            return date(int(value[:4]), int(value[5:7]), 1)
        except ValueError:
            return None
    return None


def _next_month(d: date) -> date:
    return (d.replace(day=28) + timedelta(days=4)).replace(day=1)


def _prev_month(d: date) -> date:
    return (d - timedelta(days=1)).replace(day=1)


def build_context(month_param: str | None) -> dict:
    uid = config.APP_USER_ID
    today = timeutil.today_jst()
    # 不正な ?month= は今月に戻す（元コードは 500 エラーになっていた）
    target = _parse_month(month_param) or today.replace(day=1)
    nxt, prv = _next_month(target), _prev_month(target)
    month_key = target.strftime("%Y-%m")

    # ---- 月別の合計（1回のクエリで、通算・年累計・当月・推移を全部まかなう） ----
    totals = db.fetch_monthly_totals(uid)
    all_income = sum(int(r["inc"]) for r in totals)
    all_expense = sum(int(r["exp"]) for r in totals)
    this_month = next((r for r in totals if r["ym"] == month_key), None)
    income = int(this_month["inc"]) if this_month else 0
    expense = int(this_month["exp"]) if this_month else 0
    ytd = sum(int(r["inc"]) for r in totals if r["ym"].startswith(f"{target.year}-"))

    # ---- 扶養の壁 ----
    limit = config.FUYOU_LIMIT
    pct = min(100.0, round(ytd / limit * 100, 1))
    fuyou = {
        "year": target.year,
        "ytd": ytd,
        "limit": limit,
        "remaining": max(0, limit - ytd),
        "over": max(0, ytd - limit),
        "pct": pct,
        "level": "danger" if pct >= 90 else "warn" if pct >= 70 else "ok",
    }

    # ---- 支出の内訳 ----
    categories = []
    for i, r in enumerate(db.fetch_category_breakdown(uid, target, nxt)):
        name = str(r["category"] or "その他")
        amount = int(r["cat_total"] or 0)
        categories.append({
            "name": name,
            "amount": amount,
            "pct": round(amount / (expense or 1) * 100, 1),
            "color": _color_for(name, i),
        })

    # ---- 明細（日ごとにまとめる） ----
    groups: "OrderedDict[date, dict]" = OrderedDict()
    records = db.fetch_records(uid, target, nxt)
    for r in records:
        d = r["record_date"]
        is_income = r["record_type"] == "income"
        color = _color_for(r["category"])
        detail = (r["detail"] or "").strip()
        rec = {
            "id": r["id"],
            "title": r["title"],
            "detail": "" if detail in _HIDDEN_DETAILS else detail,
            "amount": int(r["amount"]),
            "is_income": is_income,
            "badge": ("見込給料" if r["status"] == "expected" else "収入") if is_income else r["category"],
            "color": color,
            "color_soft": _soft(color),
        }
        g = groups.setdefault(d, {
            "label": f"{d.month}月{d.day}日({WEEKDAYS[d.weekday()]})",
            "is_today": d == today,
            "net": 0,
            "records": [],
        })
        g["records"].append(rec)
        g["net"] += rec["amount"] if is_income else -rec["amount"]

    trend = {
        "labels": [r["ym"] for r in totals],
        "incomes": [int(r["inc"]) for r in totals],
        "expenses": [int(r["exp"]) for r in totals],
    }

    return {
        "month": month_key,
        "month_label": f"{target.year}年{target.month}月",
        "prev_month": prv.strftime("%Y-%m"),
        "next_month": nxt.strftime("%Y-%m"),
        "is_current_month": target == today.replace(day=1),
        "income": income,
        "expense": expense,
        "balance": income - expense,
        "all_time": {"income": all_income, "expense": all_expense, "balance": all_income - all_expense},
        "fuyou": fuyou,
        "categories": categories,
        "groups": list(groups.values()),
        "record_count": len(records),
        "today_iso": today.isoformat(),
        "expense_categories": EXPENSE_CATEGORIES,
        "income_categories": INCOME_CATEGORIES,
        # JavaScript に渡すデータ（テンプレート側で tojson して安全に埋め込む）
        "chart_data": {
            "month": month_key,
            "trend": trend,
            "categories": {
                "labels": [c["name"] for c in categories],
                "values": [c["amount"] for c in categories],
                "colors": [c["color"] for c in categories],
            },
            "form": {"expense": EXPENSE_CATEGORIES, "income": INCOME_CATEGORIES},
        },
    }
