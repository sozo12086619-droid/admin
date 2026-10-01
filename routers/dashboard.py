"""routers/dashboard.py — 画面（/）と、手動入力・編集・削除の API"""

import logging
import time
from datetime import date
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

# デプロイのたびに変わる値。CSS/JS の URL に付けて、古いキャッシュを使わせない
_ASSET_VERSION = str(int(time.time()))


def _yen(value, signed: bool = False) -> str:
    """12345 → ¥12,345 / -500 → -¥500 / signed=True なら正の数に + を付ける。"""
    n = int(value or 0)
    text = f"¥{abs(n):,}"
    if n < 0:
        return "-" + text
    return "+" + text if signed and n > 0 else text


templates.env.filters["yen"] = _yen


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, month: str | None = None):
    try:
        context = dashboard_service.build_context(month)
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
