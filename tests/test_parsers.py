"""解析ロジックのテスト（DB・ネットワーク不要）"""
from datetime import date

import timeutil
from services.datetext import find_date
from services.expense_service import guess_category, parse_expense_text
from services.gemini_service import normalize_items
from services.salary_service import calculate_salary
from services.shift_service import parse_shift_text

YEAR = timeutil.today_jst().year


def test_shift_basic():
    r = parse_shift_text("9/21 すき家 18:00〜23:00")
    assert r["summary"] == "すき家"
    assert r["record_date"] == f"{YEAR}-09-21"
    assert r["time_str"] == "18:00〜23:00"
    # 昼(18-22時)4h x 1150 + 深夜(22-23時)1h x 1438
    assert r["salary"]["total_pay"] == 4 * 1150 + 1438


def test_shift_crossing_midnight():
    r = parse_shift_text("10月3日 22:00-2:00")
    assert r["end"].startswith(f"{YEAR}-10-04T02:00")
    assert r["salary"]["total_pay"] == 4 * 1438        # 全部深夜


def test_shift_default_summary():
    assert parse_shift_text("9/21 18-23")["summary"] == "シフト"


def test_shift_time_before_date_no_longer_crashes():
    r = parse_shift_text("18:00-23:00 9/21")
    assert r and r["record_date"] == f"{YEAR}-09-21"


def test_shift_iso_date():
    r = parse_shift_text("2026-09-15 18:00-23:00")
    assert r and r["record_date"] == "2026-09-15" and r["time_str"] == "18:00〜23:00"


def test_shift_rejects_impossible_values():
    assert parse_shift_text("13/45 18:00-23:00") is None
    assert parse_shift_text("9/21 25:00-26:00") is None


def test_shift_midnight_end():
    r = parse_shift_text("9/21 22:00-24:00")
    assert r["end"].startswith(f"{YEAR}-09-22T00:00")


def test_expense_basic():
    r = parse_expense_text("9/21 セブン 1,234円")
    assert r == {"record_date": f"{YEAR}-09-21", "title": "セブン", "amount": 1234, "category": "食費"}


def test_expense_title_with_space():
    assert parse_expense_text("9/21 スーパー 弁当 980円")["title"] == "スーパー 弁当"


def test_expense_ignores_non_expenses():
    for line in ["合計 1000円", "PayPay 1,000円 (3件)", "セブン 150円", "牛乳買う",
                 "9/21 18:00-23:00", "1/1 初詣 0円", "13/45 セブン 100円"]:
        assert parse_expense_text(line) is None, line


def test_category_order():
    assert guess_category("居酒屋") == "外食費"
    assert guess_category("ユニクロ") == "衣服"
    assert guess_category("なにか") == "その他"


def test_find_date_variants():
    for text, expect in [("9/21", (9, 21)), ("9月21日", (9, 21)), ("2027/1/5", (1, 5)), ("2027年1月5日", (1, 5))]:
        m, d = find_date(text)
        assert (d.month, d.day) == expect, text
    assert find_date("2027/1/5")[1] == date(2027, 1, 5)
    assert find_date("13/45") is None


def test_salary_day_and_night_split():
    from datetime import datetime
    s = calculate_salary(datetime(2026, 9, 21, 20, 0), datetime(2026, 9, 21, 23, 0), "すき家")
    assert (s["day_hours"], s["night_hours"]) == (2.0, 1.0)
    assert s["total_pay"] == 2 * 1150 + 1438


def test_gemini_normalize_is_defensive():
    today = date(2026, 9, 21)
    items = normalize_items([
        {"date": "2026-09-01", "store": "ローソン", "amount": "1,280円", "category": "食費"},
        {"date": "不明", "store": None, "amount": 500.0, "category": "謎カテゴリ"},
        {"date": "2026-09-02", "store": "返金", "amount": -300, "category": "食費"},   # 除外される
        "ゴミ",
    ], today)
    assert [i["amount"] for i in items] == [1280, 500]
    assert items[1]["date"] == "2026-09-21"          # 日付不明は今日
    assert items[1]["store"] == "店舗"               # 店名なしは既定値
    assert items[1]["category"] == "その他"           # 想定外カテゴリは その他
    assert normalize_items({"amount": 100}, today)[0]["amount"] == 100   # 単体の dict も受け付ける
    assert normalize_items("壊れた出力", today) == []
