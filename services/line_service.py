"""line_service.py — LINE Messaging API とのやりとり（署名検証・返信・画像取得）"""

from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    MessagingApiBlob,
    ReplyMessageRequest,
    TextMessage,
)

import config

configuration = Configuration(access_token=config.LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(config.LINE_CHANNEL_SECRET)

# LINE のテキストメッセージは 5000 文字まで
_MAX_TEXT = 4900


def reply_text(reply_token: str, text: str) -> None:
    with ApiClient(configuration) as api_client:
        MessagingApi(api_client).reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=text[:_MAX_TEXT])],
            )
        )


def download_image(message_id: str) -> bytes:
    with ApiClient(configuration) as api_client:
        return bytes(MessagingApiBlob(api_client).get_message_content(message_id))
