"""
互換用の薄いラッパー。

Render の Start Command が `uvicorn line_bot:app --host 0.0.0.0 --port $PORT` のままでも
動くようにするためのファイル。Start Command を `uvicorn main:app ...` に変えたら削除してよい。
"""

from main import app  # noqa: F401
