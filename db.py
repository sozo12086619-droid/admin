"""
db.py — データの保存・読み出しを担当するファイル（Supabase / PostgreSQL）

【SQLite版からの変更点】
  - 保存先がローカルの memo.db → クラウド上のPostgreSQLに変わった
  - プレースホルダが ? から %s に変わった（PostgreSQLの書き方）
  - 取り出した行は sqlite3.Row ではなく dict（辞書）で返る
    → row["title"] という書き方は同じなので、app.py 側は変更不要
  - 接続を毎回作らず「コネクションプール」で使い回す
  - user_id 列を追加（将来のマルチユーザー化に備えた土台）

【呼び出し側から見たインターフェースは完全に同じ】
  init_db / insert_raw_note / insert_items / fetch_items /
  fetch_raw_notes / update_item / delete_item /
  existing_schedule_keys / count_by_category
"""

from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from datetime import datetime

import psycopg2
from psycopg2 import pool as pg_pool
from psycopg2.extras import RealDictCursor, execute_values

CATEGORIES = ["買い物", "タスク", "予定", "メモ", "出来事", "やりたいこと"]
STATUSES = ["未着手", "進行中", "完了", "保留"]


# ---------------------------------------------------------------------------
# 設定の読み込み
# ---------------------------------------------------------------------------

def _secret(key: str, default: str | None = None) -> str | None:
    """Streamlit Secrets → 環境変数 → 既定値 の順で設定を探す。

    Streamlit Cloud では画面から Secrets を登録する。
    ローカルや移行スクリプトから使うときは環境変数でも動くようにしてある。
    """
    try:
        import streamlit as st

        if key in st.secrets:
            return str(st.secrets[key])
    except Exception:  # noqa: BLE001  (streamlit外から呼ばれた場合など)
        pass
    return os.getenv(key, default)


def _dsn() -> str:
    """接続文字列（DSN）を取得する。"""
    url = _secret("SUPABASE_DB_URL") or _secret("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "接続先が設定されてへん。"
            ".streamlit/secrets.toml か環境変数に SUPABASE_DB_URL を設定してな。"
        )
    return url


# 誰のデータとして保存するか。今は固定値、将来ログイン機能を付けたらここを差し替える
USER_ID = _secret("APP_USER_ID", "default") or "default"


# ---------------------------------------------------------------------------
# コネクションプール
# ---------------------------------------------------------------------------

_pool = None
_pool_lock = threading.Lock()


def _get_pool():
    global _pool
    with _pool_lock:
        if _pool is None:
            dsn = _dsn()
            opts = {
                "connect_timeout": 10,
                "application_name": "memo-organizer",
                "options": "-c statement_timeout=15000",
            }
            if "sslmode=" not in dsn:
                opts["sslmode"] = "require"

            _pool = pg_pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=5,
                dsn=dsn,
                **opts,
            )
    return _pool


def reset_pool() -> None:
    """接続をいったん全部捨てる（接続エラーからの復帰用）。"""
    global _pool
    with _pool_lock:
        if _pool is not None:
            try:
                _pool.closeall()
            except Exception:  # noqa: BLE001
                pass
            _pool = None


@contextmanager
def get_conn():
    """プールから接続を借りて、終わったら返す。"""
    p = _get_pool()
    conn = p.getconn()
    broken = False

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        conn.commit()
    except (psycopg2.OperationalError, psycopg2.InterfaceError):
        p.putconn(conn, close=True)
        conn = p.getconn()

    try:
        yield conn
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            broken = True
        raise
    finally:
        p.putconn(conn, close=broken)


# ---------------------------------------------------------------------------
# 小さなヘルパー
# ---------------------------------------------------------------------------

def query(sql: str, params: tuple | list = ()) -> list[dict]:
    """SELECT用。結果を辞書のリストで返す。"""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]


def execute(sql: str, params: tuple | list = ()) -> None:
    """INSERT / UPDATE / DELETE 用。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)


def health_check() -> tuple[bool, str]:
    """接続できるかを確認する。"""
    try:
        row = query("SELECT current_database() AS db, version() AS v")[0]
        return True, f"{row['db']} / {row['v'].split(',')[0]}"
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# テーブル作成
# ---------------------------------------------------------------------------

def init_db() -> None:
    """テーブルが無ければ作る。"""
    ddl = [
        """
        CREATE TABLE IF NOT EXISTS public.raw_notes (
            id          bigserial PRIMARY KEY,
            user_id     text NOT NULL DEFAULT 'default',
            created_at  text NOT NULL,
            body        text NOT NULL,
            source      text NOT NULL DEFAULT 'manual'
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS public.items (
            id                bigserial PRIMARY KEY,
            user_id           text NOT NULL DEFAULT 'default',
            raw_note_id       bigint REFERENCES public.raw_notes(id) ON DELETE SET NULL,
            created_at        text NOT NULL,
            updated_at        text NOT NULL,
            category          text NOT NULL,
            title             text NOT NULL,
            detail            text DEFAULT '',
            tags              text DEFAULT '[]',
            date_text         text,
            event_date        text,
            due_date          text,
            start_at          text,
            end_at            text,
            all_day           integer DEFAULT 1,
            importance        integer,
            estimated_minutes integer,
            priority_score    real,
            status            text NOT NULL DEFAULT '未着手',
            calendar_synced   integer NOT NULL DEFAULT 0,
            ai_model          text,
            confidence        real
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_items_user ON public.items (user_id)",
        "CREATE INDEX IF NOT EXISTS idx_items_category ON public.items (category)",
        "CREATE INDEX IF NOT EXISTS idx_items_status ON public.items (status)",
        "CREATE INDEX IF NOT EXISTS idx_items_event_date ON public.items (event_date)",
        "CREATE INDEX IF NOT EXISTS idx_items_schedule "
        "ON public.items (user_id, event_date, start_at)",
        "CREATE INDEX IF NOT EXISTS idx_raw_notes_user ON public.raw_notes (user_id)",
    ]
    with get_conn() as conn:
        with conn.cursor() as cur:
            for sql in ddl:
                cur.execute(sql)


# ---------------------------------------------------------------------------
# 保存
# ---------------------------------------------------------------------------

def insert_raw_note(
    body: str,
    source: str = "manual",
    user_id: str | None = None,
    **kwargs,
) -> int:
    """殴り書きの原文を保存し、そのIDを返す。"""
    target_user = user_id or USER_ID
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO public.raw_notes (user_id, created_at, body, source) "
                "VALUES (%s, %s, %s, %s) RETURNING id",
                (target_user, now_iso(), body, source),
            )
            return cur.fetchone()[0]


# line_bot.py からの呼び出し用エイリアス
save_raw_note = insert_raw_note


# INSERT する列の並び
_ITEM_COLUMNS = (
    "user_id", "raw_note_id", "created_at", "updated_at",
    "category", "title", "detail", "tags", "date_text",
    "event_date", "due_date", "start_at", "end_at", "all_day",
    "importance", "estimated_minutes", "status", "ai_model", "confidence",
)


def _row_values(
    it: dict,
    raw_note_id: int | None,
    ts: str,
    ai_model: str,
    user_id: str = USER_ID,
) -> tuple:
    return (
        user_id,
        raw_note_id,
        ts,
        ts,
        it.get("category") or "メモ",
        (str(it.get("title") or "").strip() or "（無題）"),
        it.get("detail") or "",
        json.dumps(it.get("tags") or [], ensure_ascii=False),
        it.get("date_text"),
        it.get("event_date"),
        it.get("due_date"),
        it.get("start_at"),
        it.get("end_at"),
        1 if it.get("all_day", 1) else 0,
        it.get("importance"),
        it.get("estimated_minutes"),
        it.get("status") or "未着手",
        ai_model,
        it.get("confidence"),
    )


def insert_items(
    items: list[dict],
    raw_note_id: int | None,
    ai_model: str,
    user_id: str | None = None,
    **kwargs,
) -> int:
    """項目リストをまとめて保存する。保存件数を返す。"""
    if not items:
        return 0

    target_user = user_id or USER_ID
    ts = now_iso()
    rows = [_row_values(it, raw_note_id, ts, ai_model, target_user) for it in items]
    cols = ", ".join(_ITEM_COLUMNS)

    with get_conn() as conn:
        with conn.cursor() as cur:
            execute_values(
                cur,
                f"INSERT INTO public.items ({cols}) VALUES %s",
                rows,
            )
    return len(rows)


# ---------------------------------------------------------------------------
# 取り出し
# ---------------------------------------------------------------------------

def fetch_items(
    categories: list[str] | None = None,
    statuses: list[str] | None = None,
    keyword: str = "",
    order: str = "timeline",
    descending: bool = True,
    user_id: str | None = None,
    **kwargs,
) -> list[dict]:
    """条件に合う項目を取り出す。"""
    target_user = user_id or USER_ID
    sql = "SELECT * FROM public.items WHERE user_id = %s"
    params: list = [target_user]

    if categories:
        sql += " AND category = ANY(%s)"
        params.append(list(categories))

    if statuses:
        sql += " AND status = ANY(%s)"
        params.append(list(statuses))

    if keyword:
        sql += " AND (title ILIKE %s OR detail ILIKE %s)"
        params.extend([f"%{keyword}%", f"%{keyword}%"])

    direction = "DESC" if descending else "ASC"
    if order == "timeline":
        sql += (
            " ORDER BY (event_date IS NULL) ASC,"
            f" COALESCE(event_date, substr(created_at, 1, 10)) {direction},"
            " COALESCE(substr(start_at, 12, 5), '99:99') ASC, id DESC"
        )
    else:
        sql += f" ORDER BY id {direction}"

    return query(sql, params)


def fetch_raw_notes(limit: int = 50, user_id: str | None = None, **kwargs) -> list[dict]:
    target_user = user_id or USER_ID
    return query(
        "SELECT * FROM public.raw_notes WHERE user_id = %s ORDER BY id DESC LIMIT %s",
        (target_user, limit),
    )


def existing_schedule_keys(user_id: str | None = None, **kwargs) -> set[tuple[str, str]]:
    """すでに登録済みの (日付, 開始日時) の組を集めて返す。"""
    target_user = user_id or USER_ID
    rows = query(
        "SELECT event_date, start_at FROM public.items "
        "WHERE user_id = %s AND event_date IS NOT NULL AND start_at IS NOT NULL",
        (target_user,),
    )
    return {(r["event_date"], r["start_at"]) for r in rows}


def count_by_category(user_id: str | None = None, **kwargs) -> dict[str, int]:
    target_user = user_id or USER_ID
    rows = query(
        "SELECT category, COUNT(*) AS n FROM public.items "
        "WHERE user_id = %s GROUP BY category",
        (target_user,),
    )
    return {r["category"]: int(r["n"]) for r in rows}


# ---------------------------------------------------------------------------
# 更新・削除
# ---------------------------------------------------------------------------

_UPDATABLE = {
    "category", "title", "detail", "tags", "date_text", "event_date",
    "due_date", "start_at", "end_at", "all_day", "importance",
    "estimated_minutes", "priority_score", "status", "calendar_synced",
}


def update_item(item_id: int, user_id: str | None = None, **fields) -> None:
    target_user = user_id or USER_ID
    fields = {k: v for k, v in fields.items() if k in _UPDATABLE}
    if not fields:
        return

    fields["updated_at"] = now_iso()
    assignments = ", ".join(f"{k} = %s" for k in fields)
    params = list(fields.values()) + [item_id, target_user]
    execute(
        f"UPDATE public.items SET {assignments} WHERE id = %s AND user_id = %s",
        params,
    )


def delete_item(item_id: int, user_id: str | None = None, **kwargs) -> None:
    target_user = user_id or USER_ID
    execute(
        "DELETE FROM public.items WHERE id = %s AND user_id = %s",
        (item_id, target_user),
    )
