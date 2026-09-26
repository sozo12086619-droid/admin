"""
db.py — データの保存・読み出しを担当するファイル（Supabase / PostgreSQL）
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
    try:
        import streamlit as st
        if key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return os.getenv(key, default)

def _dsn() -> str:
    url = _secret("SUPABASE_DB_URL") or _secret("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "接続先が設定されてへん。"
            ".streamlit/secrets.toml か環境変数に SUPABASE_DB_URL を設定してな。"
        )
    return url

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
    global _pool
    with _pool_lock:
        if _pool is not None:
            try:
                _pool.closeall()
            except Exception:
                pass
            _pool = None

@contextmanager
def get_conn():
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
        except Exception:
            broken = True
        raise
    finally:
        # ここを close=broken に修正
        p.putconn(conn, close=broken)

# ---------------------------------------------------------------------------
# 小さなヘルパー
# ---------------------------------------------------------------------------

def query(sql: str, params: tuple | list = ()) -> list[dict]:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

def execute(sql: str, params: tuple | list = ()) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)

def health_check() -> tuple[bool, str]:
    try:
        row = query("SELECT current_database() AS db, version() AS v")[0]
        return True, f"{row['db']} / {row['v'].split(',')[0]}"
    except Exception as e:
        return False, str(e)

def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")

# ---------------------------------------------------------------------------
# テーブル作成
# ---------------------------------------------------------------------------

def init_db() -> None:
    """テーブルが無ければ自動作成する"""
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
        """
        CREATE TABLE IF NOT EXISTS public.money_records (
            id          bigserial PRIMARY KEY,
            user_id     text NOT NULL DEFAULT 'default',
            created_at  text NOT NULL,
            record_date text NOT NULL,
            record_type text NOT NULL,
            category    text NOT NULL,
            title       text NOT NULL,
            amount      integer NOT NULL,
            status      text NOT NULL DEFAULT 'confirmed',
            detail      text DEFAULT '',
            raw_note_id bigint REFERENCES public.raw_notes(id) ON DELETE SET NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_items_user ON public.items (user_id)",
        "CREATE INDEX IF NOT EXISTS idx_items_category ON public.items (category)",
        "CREATE INDEX IF NOT EXISTS idx_raw_notes_user ON public.raw_notes (user_id)",
        "CREATE INDEX IF NOT EXISTS idx_money_user_date ON public.money_records (user_id, record_date)",
    ]
    with get_conn() as conn:
        with conn.cursor() as cur:
            for sql in ddl:
                cur.execute(sql)

# ---------------------------------------------------------------------------
# 家計簿・給料関連
# ---------------------------------------------------------------------------

def insert_money_record(
    record_date: str,
    record_type: str,
    category: str,
    title: str,
    amount: int,
    status: str = "confirmed",
    detail: str = "",
    raw_note_id: int | None = None,
    user_id: str | None = None,
) -> int:
    target_user = user_id or USER_ID
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.money_records 
                (user_id, created_at, record_date, record_type, category, title, amount, status, detail, raw_note_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
                """,
                (target_user, now_iso(), record_date, record_type, category, title, amount, status, detail, raw_note_id),
            )
            return cur.fetchone()[0]

def fetch_monthly_money_summary(year_month: str, user_id: str | None = None) -> dict:
    target_user = user_id or USER_ID
    sql = """
        SELECT record_type, status, SUM(amount) AS total
        FROM public.money_records
        WHERE user_id = %s AND record_date LIKE %s
        GROUP BY record_type, status
    """
    rows = query(sql, (target_user, f"{year_month}%"))
    
    expected_income = 0
    confirmed_income = 0
    expenses = 0

    for r in rows:
        rtype = r["record_type"]
        status = r["status"]
        total = int(r["total"] or 0)
        if rtype == "income":
            if status == "expected":
                expected_income += total
            else:
                confirmed_income += total
        elif rtype == "expense":
            expenses += total

    return {
        "year_month": year_month,
        "expected_income": expected_income,
        "confirmed_income": confirmed_income,
        "total_income": expected_income + confirmed_income,
        "expenses": expenses,
        "balance": (expected_income + confirmed_income) - expenses,
    }

# ---------------------------------------------------------------------------
# 既存の保存・取得関数
# ---------------------------------------------------------------------------

def insert_raw_note(body: str, source: str = "manual", user_id: str | None = None, **kwargs) -> int:
    target_user = user_id or USER_ID
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO public.raw_notes (user_id, created_at, body, source) "
                "VALUES (%s, %s, %s, %s) RETURNING id",
                (target_user, now_iso(), body, source),
            )
            return cur.fetchone()[0]

save_raw_note = insert_raw_note

_ITEM_COLUMNS = (
    "user_id", "raw_note_id", "created_at", "updated_at",
    "category", "title", "detail", "tags", "date_text",
    "event_date", "due_date", "start_at", "end_at", "all_day",
    "importance", "estimated_minutes", "status", "ai_model", "confidence",
)

def _row_values(it: dict, raw_note_id: int | None, ts: str, ai_model: str, user_id: str = USER_ID) -> tuple:
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

def insert_items(items: list[dict], raw_note_id: int | None, ai_model: str, user_id: str | None = None, **kwargs) -> int:
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

def fetch_items(categories: list[str] | None = None, statuses: list[str] | None = None, keyword: str = "", order: str = "timeline", descending: bool = True, user_id: str | None = None, **kwargs) -> list[dict]:
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
