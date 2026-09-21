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
# 「コネクションプール」＝ DBへの接続を数本作って使い回す仕組み。
# 接続を作る処理は重い（ネットワーク越しに認証するため）ので、
# 毎回作っていると画面の操作が1つ1つ遅くなる。
#
# Streamlit はユーザー操作のたびにスクリプトを再実行し、
# しかも複数スレッドで動くことがあるので ThreadedConnectionPool を使う。

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
                # 重いクエリが詰まったままにならんように15秒で打ち切る
                "options": "-c statement_timeout=15000",
            }
            # Supabaseは暗号化必須。
            # ただしURL側に sslmode が書かれている場合はそちらを尊重する
            # （ローカルのPostgreSQLで動作確認するときに sslmode=disable にできる）
            if "sslmode=" not in dsn:
                opts["sslmode"] = "require"

            _pool = pg_pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=5,          # 無料プランは接続数の上限が小さいので控えめに
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
    """プールから接続を借りて、終わったら返す。

    正常終了 → commit（変更を確定）
    例外発生 → rollback（変更を取り消し）
    をこの中で自動でやるので、呼び出し側は with で囲むだけでええ。
    """
    p = _get_pool()
    conn = p.getconn()
    broken = False

    # ★事前チェック（プレピン）★
    # Streamlit Cloud のアプリはしばらく使わんとスリープする。
    # 起きた時、プールの中の接続はすでに切れていることがある。
    # 借りた直後に SELECT 1 を投げて生死を確認し、死んでたら繋ぎ直す。
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
    """SELECT用。結果を辞書のリストで返す。

    RealDictCursor を使うと row["title"] のようにカラム名で読める。
    SQLite版の sqlite3.Row と同じ使い勝手なので、app.py は変更不要。
    """
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
    """接続できるかを確認する。サイドバーなどに出すと便利。"""
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
    """テーブルが無ければ作る。

    通常は Supabase の SQL Editor で supabase_schema.sql を実行して作るが、
    やり忘れても動くように、アプリ側からも同じものを作れるようにしてある。
    （SQLiteの時と同じく、毎回呼んでも害はない）
    """
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

def insert_raw_note(body: str, source: str = "manual") -> int:
    """殴り書きの原文を保存し、そのIDを返す。

    SQLiteの cur.lastrowid に相当するものが PostgreSQL には無いので、
    RETURNING id を付けて「挿入した行のidを返せ」と指示する。
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO public.raw_notes (user_id, created_at, body, source) "
                "VALUES (%s, %s, %s, %s) RETURNING id",
                (USER_ID, now_iso(), body, source),
            )
            return cur.fetchone()[0]


# INSERT する列の並び。ここと _row_values の並びは必ず一致させること
_ITEM_COLUMNS = (
    "user_id", "raw_note_id", "created_at", "updated_at",
    "category", "title", "detail", "tags", "date_text",
    "event_date", "due_date", "start_at", "end_at", "all_day",
    "importance", "estimated_minutes", "status", "ai_model", "confidence",
)


def _row_values(it: dict, raw_note_id: int | None, ts: str, ai_model: str) -> tuple:
    return (
        USER_ID,
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


def insert_items(items: list[dict], raw_note_id: int | None, ai_model: str) -> int:
    """項目リストをまとめて保存する。保存件数を返す。

    execute_values を使うと、何十件あっても1回の通信で送れる。
    クラウドDBは1往復ごとに通信時間がかかるので、まとめて送るのが大事。
    """
    if not items:
        return 0

    ts = now_iso()
    rows = [_row_values(it, raw_note_id, ts, ai_model) for it in items]
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
) -> list[dict]:
    """条件に合う項目を取り出す。

    order="timeline" … event_date（無ければ登録日）の日付順
    order="created"  … 登録した順
    """
    sql = "SELECT * FROM public.items WHERE user_id = %s"
    params: list = [USER_ID]

    if categories:
        # PostgreSQL では = ANY(%s) にリストをそのまま渡せる。
        # SQLiteのように ? を個数ぶん並べる必要がない。
        sql += " AND category = ANY(%s)"
        params.append(list(categories))

    if statuses:
        sql += " AND status = ANY(%s)"
        params.append(list(statuses))

    if keyword:
        # ILIKE は大文字小文字を区別しない検索（PostgreSQL独自）
        sql += " AND (title ILIKE %s OR detail ILIKE %s)"
        params.extend([f"%{keyword}%", f"%{keyword}%"])

    direction = "DESC" if descending else "ASC"
    if order == "timeline":
        # COALESCE(a, b) = 「aがNULLならbを使う」
        # 日付が無い項目は登録日で並べ、かつ日付ありを先に出す
        sql += (
            " ORDER BY (event_date IS NULL) ASC,"
            f" COALESCE(event_date, substr(created_at, 1, 10)) {direction},"
            " COALESCE(substr(start_at, 12, 5), '99:99') ASC, id DESC"
        )
    else:
        sql += f" ORDER BY id {direction}"

    return query(sql, params)


def fetch_raw_notes(limit: int = 50) -> list[dict]:
    return query(
        "SELECT * FROM public.raw_notes WHERE user_id = %s ORDER BY id DESC LIMIT %s",
        (USER_ID, limit),
    )


def existing_schedule_keys() -> set[tuple[str, str]]:
    """すでに登録済みの (日付, 開始日時) の組を集めて返す。

    シフト表を2回読み込んでしまったときの二重登録を防ぐために使う。
    """
    rows = query(
        "SELECT event_date, start_at FROM public.items "
        "WHERE user_id = %s AND event_date IS NOT NULL AND start_at IS NOT NULL",
        (USER_ID,),
    )
    return {(r["event_date"], r["start_at"]) for r in rows}


def count_by_category() -> dict[str, int]:
    rows = query(
        "SELECT category, COUNT(*) AS n FROM public.items "
        "WHERE user_id = %s GROUP BY category",
        (USER_ID,),
    )
    return {r["category"]: int(r["n"]) for r in rows}


# ---------------------------------------------------------------------------
# 更新・削除
# ---------------------------------------------------------------------------

# 更新を許す列の一覧。
# ここに無い名前は弾く（SQL文に列名を直接埋め込むため、安全のための門番）
_UPDATABLE = {
    "category", "title", "detail", "tags", "date_text", "event_date",
    "due_date", "start_at", "end_at", "all_day", "importance",
    "estimated_minutes", "priority_score", "status", "calendar_synced",
}


def update_item(item_id: int, **fields) -> None:
    """使い方: update_item(3, status="完了")"""
    fields = {k: v for k, v in fields.items() if k in _UPDATABLE}
    if not fields:
        return

    fields["updated_at"] = now_iso()
    assignments = ", ".join(f"{k} = %s" for k in fields)
    params = list(fields.values()) + [item_id, USER_ID]
    execute(
        f"UPDATE public.items SET {assignments} WHERE id = %s AND user_id = %s",
        params,
    )


def delete_item(item_id: int) -> None:
    execute(
        "DELETE FROM public.items WHERE id = %s AND user_id = %s",
        (item_id, USER_ID),
    )
