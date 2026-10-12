"""routers/dashboard.py — 画面（/）と、手動入力・編集・削除の API"""

import logging
import time
from collections import defaultdict
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

import config
import db
from security import require_dashboard_auth
from services import dashboard_service

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_dashboard_auth)])

templates = Jinja2Templates(directory=str(config.BASE_DIR / "templates"))
_ASSET_VERSION = str(int(time.time()))


def _yen(value, signed: bool = False) -> str:
    n = int(value or 0)
    text = f"¥{abs(n):,}"
    if n < 0:
        return "-" + text
    return "+" + text if signed and n > 0 else text


templates.env.filters["yen"] = _yen


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    month: str | None = None,
    start: str | None = None,
    end: str | None = None,
    range: str | None = None,
    cat: str | None = None,
):
    try:
        user_id = config.APP_USER_ID

        # カスタム期間または全期間、カテゴリー絞り込みが指定された場合
        is_custom = bool(start or end or range or cat)

        if not is_custom:
            context = dashboard_service.build_context(month)
        else:
            today = date.today()
            start_d = None
            end_d = None

            if range == "all":
                label = "全期間"
            elif range == "this_year":
                start_d = f"{today.year}-01-01"
                end_d = f"{today.year}-12-31"
                label = f"{today.year}年 通算"
            elif start or end:
                start_d = start or "2000-01-01"
                end_d = end or today.isoformat()
                label = f"{start_d} 〜 {end_d}"
            else:
                label = "指定期間"

            records = db.fetch_records_filtered(user_id, start=start_d, end=end_d, category=cat)

            income = sum(r["amount"] for r in records if r["record_type"] == "income")
            expense = sum(r["amount"] for r in records if r["record_type"] == "expense")
            balance = income - expense

            # 日毎のグルーピング
            by_date = defaultdict(list)
            for r in records:
                d_str = r["record_date"].strftime("%Y-%m-%d") if isinstance(r["record_date"], (date, datetime)) else str(r["record_date"])
                r_dict = dict(r)
                r_dict["is_income"] = (r["record_type"] == "income")
                r_dict["badge"] = r["category"]
                r_dict["color"] = "#4f46e5"
                r_dict["color_soft"] = "#e0e7ff"
                by_date[d_str].append(r_dict)

            groups = []
            for d_str in sorted(by_date.keys(), reverse=True):
                recs = by_date[d_str]
                net = sum(r["amount"] if r["is_income"] else -r["amount"] for r in recs)
                groups.append({
                    "date": d_str,
                    "label": d_str,
                    "is_today": (d_str == today.isoformat()),
                    "net": net,
                    "records": recs,
                })

            # 全カテゴリリスト取得（フィルターボタン用）
            all_cat_breakdown = db.fetch_category_breakdown(user_id)
            cat_list = [c["category"] for c in all_cat_breakdown]

            base_ctx = dashboard_service.build_context(month)
            context = {
                **base_ctx,
                "month_label": label + (f" · {cat}" if cat and cat != 'all' else ""),
                "income": income,
                "expense": expense,
                "balance": balance,
                "groups": groups,
                "record_count": len(records),
                "is_custom_filter": True,
                "current_cat": cat or "all",
                "current_range": range or "",
                "start_date": start or "",
                "end_date": end or "",
                "available_categories": cat_list,
            }

        # カテゴリ一覧をテンプレートに常に渡す
        if "available_categories" not in context:
            all_cats = db.fetch_category_breakdown(user_id)
            context["available_categories"] = [c["category"] for c in all_cats]
            context["current_cat"] = "all"

        context["asset_v"] = _ASSET_VERSION
        return templates.TemplateResponse(request, "dashboard.html", context)

    except Exception:
        logger.exception("ダッシュボードの表示に失敗")
        return HTMLResponse(
            "<h2>読み込みに失敗しました</h2><p>Render のログを確認してください。</p>",
            status_code=500,
        )


class RecordIn(BaseModel):
    record_date: date
    record_type: Literal["income", "expense"] = "expense"
    category: str = "その他"
    title: str = ""
    amount: int = Field(gt=0, le=100_000_000)
    detail: str = ""


@router.post("/api/records")
def add_record(rec: RecordIn):
    try:
        new_id = db.insert_money_record(
            record_date=rec.record_date,
            record_type=rec.record_type,
            category=rec.category.strip()[:30] or "その他",
            title=rec.title.strip()[:100] or "手動入力",
            amount=rec.amount,
            status="confirmed",
            detail=rec.detail.strip()[:200],
            user_id=config.APP_USER_ID,
        )
        return {"status": "success", "id": new_id}
    except Exception:
        logger.exception("手動入力の保存に失敗")
        return JSONResponse({"status": "error", "message": "保存に失敗しました"}, status_code=500)


@router.put("/api/records/{record_id}")
def update_record(record_id: int, rec: RecordIn):
    try:
        updated = db.update_money_record(
            record_id=record_id,
            user_id=config.APP_USER_ID,
            record_date=rec.record_date,
            record_type=rec.record_type,
            category=rec.category.strip()[:30] or "その他",
            title=rec.title.strip()[:100] or "手動入力",
            amount=rec.amount,
            detail=rec.detail.strip()[:200],
        )
        if not updated:
            return JSONResponse({"status": "error", "message": "データが見つかりませんでした"}, status_code=404)
        return {"status": "success", "updated": updated}
    except Exception:
        logger.exception("更新に失敗")
        return JSONResponse({"status": "error", "message": "更新に失敗しました"}, status_code=500)


@router.delete("/api/records/{record_id}")
def delete_record(record_id: int):
    try:
        deleted = db.delete_money_record(record_id, config.APP_USER_ID)
        return {"status": "success", "deleted": deleted}
    except Exception:
        logger.exception("削除に失敗")
        return JSONResponse({"status": "error", "message": "削除に失敗しました"}, status_code=500)
