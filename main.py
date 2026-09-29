"""
main.py — アプリの入口。ここには「組み立て」だけを書く

    routers/   … URL ごとの受付窓口（ダッシュボード、LINE Webhook）
    services/  … 中身の処理（給料計算、カレンダー、Gemini、LINE、集計など）
    db.py      … SQL はここだけ
    templates/ static/ … 画面の見た目
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

import config
import db
from routers import dashboard, line_webhook

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("kakeibo")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        db.init_db()
    except Exception:
        # DB に繋がらなくても起動は続ける（LINE の署名検証などは動く）。原因はログで確認
        logger.exception("DB の初期化に失敗")
    if not config.DASHBOARD_PASSWORD:
        logger.warning(
            "DASHBOARD_PASSWORD が未設定です。ダッシュボードと /api/records は誰でもアクセスできます"
        )
    yield
    db.close_pool()


app = FastAPI(title="LINE家計簿", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(config.BASE_DIR / "static")), name="static")
app.include_router(dashboard.router)
app.include_router(line_webhook.router)


@app.get("/healthz", include_in_schema=False)
def healthz():
    """Render のヘルスチェック用。DB には触らない。"""
    return {"status": "ok"}
