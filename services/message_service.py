"""
message_service.py — LINE のメッセージを受け取って、何をするか決める司令塔
"""

import logging
import re

import config
import db
from services import calendar_service, gemini_service
from services.expense_service import parse_expense_text
from services.shift_service import parse_shift_text

logger = logging.getLogger(__name__)


def _short(e: Exception, limit: int = 80) -> str:
    return str(e).replace("\n", " ")[:limit]


def _detect_shift_job(text: str) -> dict:
    """メッセージ全体または行から、バイト先・対象者・希望かどうかを判定する。"""
    is_hope = bool(re.search(r"希望|未確定|提出", text))

    if re.search(r"ゴン茶|ゴンチャ|gongcha", text, re.IGNORECASE):
        return {
            "name": "ゴン茶",
            "owner": "girlfriend",
            "is_hope": is_hope,
            "color_id": "1" if is_hope else "4",  # 希望: 薄紫 / 確定: ピンク
            "rate_type": "hourly",
            "rate": 1023,
        }
    elif re.search(r"塾", text):
        return {
            "name": "塾",
            "owner": "girlfriend",
            "is_hope": is_hope,
            "color_id": "1" if is_hope else "5",  # 希望: 薄紫 / 確定: 黄色
            "rate_type": "per_class",
            "rate": 1500,
        }
    elif re.search(r"韓国語|家庭教師", text):
        return {
            "name": "韓国語",
            "owner": "girlfriend",
            "is_hope": is_hope,
            "color_id": "1" if is_hope else "6",  # 希望: 薄紫 / 確定: オレンジ
            "rate_type": "hourly",
            "rate": 2000,
        }
    else:
        # デフォルトは自分のすき家
        return {
            "name": "すき家",
            "owner": "me",
            "is_hope": is_hope,
            "color_id": "8" if is_hope else "7",  # 希望: グレー / 確定: 青
            "rate_type": "sukiya",
        }


def _calc_salary(shift: dict, job_info: dict, raw_line: str) -> dict:
    """バイト先に応じた給与・見込みを計算する。"""
    rate_type = job_info.get("rate_type")

    # 1. 塾（1コマ1500円）
    if rate_type == "per_class":
        m = re.search(r"(\d+)\s*コマ", raw_line)
        if m:
            classes = int(m.group(1))
        else:
            # コマ数指定がない場合は時間（90分=1コマ換算）から推定
            orig_sal = shift.get("salary", {})
            total_h = (orig_sal.get("day_hours", 0) or 0) + (orig_sal.get("night_hours", 0) or 0)
            classes = max(1, round(total_h / 1.5)) if total_h > 0 else 1
        return {"total_pay": classes * job_info["rate"], "detail": f"{classes}コマ"}

    # 2. ゴン茶（1,023円）/ 韓国語（2,000円）
    elif rate_type == "hourly":
        orig_sal = shift.get("salary", {})
        total_h = (orig_sal.get("day_hours", 0) or 0) + (orig_sal.get("night_hours", 0) or 0)
        pay = int(round(total_h * job_info["rate"]))
        return {"total_pay": pay, "detail": f"{total_h:.1f}h"}

    # 3. すき家（既存の深夜増し計算をそのまま利用）
    else:
        orig = shift.get("salary", {})
        pay = orig.get("total_pay", 0)
        dh = orig.get("day_hours", 0)
        nh = orig.get("night_hours", 0)
        return {"total_pay": pay, "detail": f"昼{dh}h/深夜{nh}h"}


def handle_text_message(text: str) -> str:
    """テキストの各行を「シフト」「支出」として解釈し、登録結果の返信文を返す。"""
    text = text.strip()

    raw_id = None
    try:
        raw_id = db.save_raw_note(user_id=config.APP_USER_ID, body=text, source="line")
    except Exception:
        logger.exception("raw_notes の保存に失敗")

    # メッセージ全体のキーワードから基本のバイト先・状態を判定
    global_job = _detect_shift_job(text)

    shift_results = {}  # バイト先ごとに件数と金額をまとめる
    expense_count, expense_total = 0, 0
    errors: list[str] = []

    for line in (ln.strip() for ln in text.split("\n")):
        if not line:
            continue

        # ---- シフト解析 ----
        try:
            shift = parse_shift_text(line)
        except Exception:
            logger.exception("シフト解析で例外: %r", line)
            shift = None

        if shift:
            try:
                # 行内にバイト名や「希望」が明記されていれば行単位の判定を優先
                line_job = _detect_shift_job(line) if any(k in line for k in ["ゴン茶", "ゴンチャ", "塾", "韓国語", "すき家", "希望"]) else global_job

                # カレンダー登録用パラメータの付与
                status_prefix = "【希望】" if line_job["is_hope"] else ""
                shift["summary"] = f"{status_prefix}{line_job['name']}"
                shift["color_id"] = line_job["color_id"]

                # 給与・見込みの計算
                sal_info = _calc_salary(shift, line_job, line)
                shift["salary_calc"] = sal_info

                # Googleカレンダーへの登録
                calendar_service.add_event_to_calendar(shift)

                # 家計簿（money_records）への登録判定：
                # 「自分のすき家」かつ「確定シフト（希望ではない）」の時だけ登録する！
                if line_job["owner"] == "me" and not line_job["is_hope"]:
                    db.insert_money_record(
                        record_date=shift["record_date"],
                        record_type="income",
                        category="バイト",
                        title=shift["summary"],
                        amount=sal_info["total_pay"],
                        status="expected",
                        detail=f"{shift.get('time_str', '')} ({sal_info['detail']})",
                        raw_note_id=raw_id,
                        user_id=config.APP_USER_ID,
                    )

                # 結果集計
                j_key = f"{line_job['name']}{'（希望）' if line_job['is_hope'] else ''}"
                if j_key not in shift_results:
                    shift_results[j_key] = {"count": 0, "total": 0, "is_kakeibo": (line_job["owner"] == "me" and not line_job["is_hope"])}
                shift_results[j_key]["count"] += 1
                shift_results[j_key]["total"] += sal_info["total_pay"]

            except Exception as e:
                logger.exception("シフト登録に失敗: %r", line)
                errors.append(f"{shift.get('date_str', '指定日')} のシフト登録失敗（{_short(e)}）")
            continue

        # ---- 支出解析 ----
        try:
            expense = parse_expense_text(line)
        except Exception:
            logger.exception("支出解析で例外: %r", line)
            expense = None

        if expense:
            try:
                db.insert_money_record(
                    record_date=expense["record_date"],
                    record_type="expense",
                    category=expense["category"],
                    title=expense["title"],
                    amount=expense["amount"],
                    status="confirmed",
                    user_id=config.APP_USER_ID,
                )
                expense_count += 1
                expense_total += expense["amount"]
            except Exception:
                logger.exception("支出登録に失敗: %r", line)
                errors.append(f"「{expense['title']}」を保存できませんでした")

    # 返信メッセージの組み立て
    parts = []
    if shift_results:
        for j_name, data in shift_results.items():
            kakeibo_mark = " ➜ 家計簿に反映" if data["is_kakeibo"] else " ➜ カレンダーのみ"
            parts.append(f"{j_name} {data['count']}件 登録 (見込¥{data['total']:,}){kakeibo_mark}")

    if expense_count:
        parts.append(f"支出 {expense_count}件 登録 (計¥{expense_total:,})")
    parts.extend(f"⚠️ {e}" for e in errors)

    return "\n".join(parts) if parts else "記録完了！"


def handle_image_message(image_bytes: bytes) -> str:
    """明細画像から支出を読み取って登録し、返信文を返す。"""
    try:
        items = gemini_service.analyze_expense_image(image_bytes)
    except gemini_service.GeminiError as e:
        return f"画像解析エラー: {e}"
    except Exception as e:
        logger.exception("画像解析で予期しない例外")
        return f"画像解析エラー: {_short(e)}"

    if not items:
        return "画像から支出を読み取れなかったよ💦 明細がはっきり写った画像で試してみてね"

    count, failed = 0, 0
    for item in items:
        try:
            db.insert_money_record(
                record_date=item["date"],
                record_type="expense",
                category=item["category"],
                title=item["store"],
                amount=item["amount"],
                detail=item["detail"],
                user_id=config.APP_USER_ID,
            )
            count += 1
        except Exception:
            logger.exception("画像明細の保存に失敗: %r", item)
            failed += 1

    reply = f"画像から支出 {count}件 を登録したよ！"
    if failed:
        reply += f"\n⚠️ {failed}件は保存できませんでした"
    return reply
