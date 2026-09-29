"""routers/line_webhook.py — LINE からの Webhook（/callback）を受け取る"""

import logging

from fastapi import APIRouter, HTTPException, Request
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import ImageMessageContent, MessageEvent, TextMessageContent
from starlette.concurrency import run_in_threadpool

from services import line_service, message_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/callback")
async def callback(request: Request):
    signature = request.headers.get("X-Line-Signature", "")
    body = (await request.body()).decode("utf-8")
    try:
        # handler.handle は同期処理（DB や Gemini を待つ）。
        # そのまま呼ぶとサーバー全体が止まるので、別スレッドで実行する。
        await run_in_threadpool(line_service.handler.handle, body, signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    return "OK"


def _safe_reply(reply_token: str, text: str) -> None:
    try:
        line_service.reply_text(reply_token, text)
    except Exception:
        # 返信トークンの期限切れなど。ここで落とすと LINE が再送してくるので、ログだけ残す
        logger.exception("LINE への返信に失敗")


@line_service.handler.add(MessageEvent, message=TextMessageContent)
def on_text_message(event):
    try:
        reply = message_service.handle_text_message(event.message.text)
    except Exception:
        logger.exception("テキスト処理で予期しない例外")
        reply = "ごめん、処理中にエラーが出たよ💦"
    _safe_reply(event.reply_token, reply)


@line_service.handler.add(MessageEvent, message=ImageMessageContent)
def on_image_message(event):
    try:
        image_bytes = line_service.download_image(event.message.id)
        reply = message_service.handle_image_message(image_bytes)
    except Exception:
        logger.exception("画像処理で予期しない例外")
        reply = "画像を処理できなかったよ💦 もう一度送ってみてね"
    _safe_reply(event.reply_token, reply)
