"""
security.py — ダッシュボードの保護（任意）

環境変数 DASHBOARD_PASSWORD を設定すると、ダッシュボードと /api/records に
Basic認証がかかる（ブラウザがID/パスワードのダイアログを出す）。
未設定なら何もしない。LINE の Webhook（/callback）は署名検証で守られているので対象外。
"""

import secrets

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials

import config

_basic = HTTPBasic(auto_error=False)


def require_dashboard_auth(credentials: HTTPBasicCredentials | None = Depends(_basic)) -> None:
    if not config.DASHBOARD_PASSWORD:
        return
    ok = (
        credentials is not None
        # compare_digest は「一致するまでの時間差」から推測されるのを防ぐ比較関数
        and secrets.compare_digest(credentials.username.encode(), config.DASHBOARD_USER.encode())
        and secrets.compare_digest(credentials.password.encode(), config.DASHBOARD_PASSWORD.encode())
    )
    if not ok:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": 'Basic realm="kakeibo", charset="UTF-8"'},
        )
