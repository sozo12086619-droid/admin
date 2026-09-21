"""
app.py — 画面まわり（Streamlit）

【Phase 2.5 での変更点】
  - バラバラだったカードを「1日＝1カード」にまとめた（日報スタイル）
  - 淡い背景＋角丸＋影の、スマホアプリ風デザインに刷新
  - カテゴリ絞り込みをドロップダウンからタブ風ボタンに変更
  - 「予定」を .ics カレンダーファイルとして書き出すボタンを追加

実行方法:
    streamlit run app.py
"""

import html
import json
import os
from collections import OrderedDict
from datetime import date

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

import ai
import calendar_export
import dateparse
import db
import shift

load_dotenv()

st.set_page_config(page_title="admin", page_icon="⚙️", layout="wide")
db.init_db()

# ---------------------------------------------------------------------------
# 配色（ここ1か所を変えれば全画面の色が変わる）
# ---------------------------------------------------------------------------
CATEGORY_STYLE = {
    "買い物":       {"color": "#F5871F", "icon": "🛒"},
    "タスク":       {"color": "#E5484D", "icon": "✅"},
    "予定":         {"color": "#30A46C", "icon": "📅"},
    "メモ":         {"color": "#8B8D98", "icon": "📝"},
    "出来事":       {"color": "#3E7BFA", "icon": "💬"},
    "やりたいこと": {"color": "#8E4EC6", "icon": "✨"},
}
DEFAULT_STYLE = {"color": "#8B8D98", "icon": "📝"}


def hex_to_rgba(hex_color: str, alpha: float) -> str:
    """#F5871F → rgba(245,135,31,0.1)。半透明にすると明暗どちらのテーマでも馴染む。"""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


# ---------------------------------------------------------------------------
# CSS（見た目の指定をまとめて流し込む）
# ---------------------------------------------------------------------------
# st.container(border=True) で作った枠に、CSSで「カードらしさ」を付けている。
# data-testid は Streamlit が各部品に付けてる目印。これを狙い撃ちして装飾する。
# ---------------------------------------------------------------------------
# テーマ（色）の設定 — ここを変えればアプリ全体の色が変わる
# ---------------------------------------------------------------------------
# config.toml を使わず、CSSをその場で流し込んで色を指定する方式。
# 利点: このファイル1つ配れば見た目もそのまま再現できる
# 欠点: Streamlit本体のテーマ設定より後から上書きする形になるので、
#       文字色まで自分で指定してやらんと「白背景に白文字」になる箇所が出る。
#       そのため下で --app-text を全体に効かせている。

THEME = {
    "bg":      "#F4F1EA",   # 背景：文庫本のような温かみのある生成り色
    "accent":  "#3B6E5B",   # アクセント：目に優しい落ち着いたフォレストグリーン
    "accent_d": "#2D5446",  # ボタンホバー用（濃い緑）
    "card":    "#FAF8F5",   # カード枠：ふんわりしたオフホワイト
    "text":    "#2B2B2A",   # 文字色：真っ黒を避けた柔らかな墨色
    "muted":   "#767571",   # 補足文字：落ち着いたグレー
    "border":  "#E2DED4",   # 枠線：目立たない淡いベージュ
}
# CSSの中で使う「変数」を先に定義しておく。
# :root に --名前: 値 を書いておくと、以降 var(--名前) で呼び出せる。
# こうしておくと色を1か所で管理できる（CSSカスタムプロパティという仕組み）。
st.markdown(
    f"""
    <style>
      :root {{
        --app-bg:     {THEME["bg"]};
        --app-accent: {THEME["accent"]};
        --app-accent-d: {THEME["accent_d"]};
        --app-card:   {THEME["card"]};
        --app-text:   {THEME["text"]};
        --app-muted:  {THEME["muted"]};
        --app-border: {THEME["border"]};
      }}
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <style>
      /* ══ 全体の背景と文字色 ══ */
      .stApp,
      section[data-testid="stMain"] {
        background-color: var(--app-bg) !important;
      }
      /* 上部のツールバー帯も背景になじませる */
      header[data-testid="stHeader"] { background: transparent !important; }

      /* 背景を明るい色に固定するので、文字色も明示的に濃くしておく。
         これをやらんと、端末がダークモードのとき白背景に白文字になってまう */
      .stApp, .stApp p, .stApp span, .stApp li, .stApp label,
      .stApp h1, .stApp h2, .stApp h3, .stApp div[data-testid="stMarkdownContainer"] {
        color: var(--app-text);
      }
      .stApp small, .stCaption, .stApp [data-testid="stCaptionContainer"] {
        color: var(--app-muted) !important;
      }

      /* ══ サイドバー ══ */
      section[data-testid="stSidebar"] {
        background-color: var(--app-card) !important;
        border-right: 1px solid var(--app-border);
      }

      /* ══ 1日ぶんのカード ══ */
      div[data-testid="stVerticalBlockBorderWrapper"] {
        background: var(--app-card) !important;
        border-radius: 16px !important;
        border: 1px solid var(--app-border) !important;
        box-shadow: 0 2px 12px rgba(16, 92, 55, .08);
        padding: 4px 16px 10px 16px !important;
        margin-bottom: 14px;
      }

      /* ══ ボタン ══ */
      /* type="primary" のボタンをエメラルドグリーンに */
      .stButton button[kind="primary"],
      .stDownloadButton button[kind="primary"] {
        background-color: var(--app-accent) !important;
        border: 1px solid var(--app-accent) !important;
        color: #fff !important;
      }
      .stButton button[kind="primary"]:hover,
      .stDownloadButton button[kind="primary"]:hover {
        background-color: var(--app-accent-d) !important;
        border-color: var(--app-accent-d) !important;
      }
      /* 普通のボタン（完了・削除）は白地に緑の枠 */
      .stButton button[kind="secondary"] {
        background-color: var(--app-card) !important;
        border: 1px solid var(--app-border) !important;
        color: var(--app-text) !important;
        padding: 2px 6px;
        font-size: 12px;
      }
      .stButton button[kind="secondary"]:hover {
        border-color: var(--app-accent) !important;
        color: var(--app-accent) !important;
      }

      /* ══ 入力欄・選択欄 ══ */
      .stTextInput input, .stTextArea textarea,
      div[data-baseweb="select"] > div {
        background-color: var(--app-card) !important;
        border-color: var(--app-border) !important;
        color: var(--app-text) !important;
      }
      .stTextInput input:focus, .stTextArea textarea:focus {
        border-color: var(--app-accent) !important;
      }
      /* タブ風ボタン（segmented_control）の選択中をアクセント色に */
      div[data-testid="stButtonGroup"] button[aria-checked="true"],
      div[data-testid="stButtonGroup"] button[kind="segmented_controlActive"] {
        background-color: var(--app-accent) !important;
        border-color: var(--app-accent) !important;
        color: #fff !important;
      }
      /* タブ（入力／タイムライン／原文ログ）の下線もアクセント色に */
      .stTabs [aria-selected="true"] { color: var(--app-accent) !important; }
      .stTabs [data-baseweb="tab-highlight"] { background-color: var(--app-accent) !important; }

      /* ══ 日付の見出し ══ */
      .day-head {
        display: flex;
        align-items: baseline;
        gap: 10px;
        padding: 10px 2px 8px 2px;
        margin-bottom: 4px;
        border-bottom: 1px dashed var(--app-border);
      }
      .day-date   { font-size: 17px; font-weight: 800; letter-spacing: .02em; }
      .day-rel    { font-size: 12px; font-weight: 700; padding: 2px 10px;
                    border-radius: 999px; background: #ECFDF5;
                    color: var(--app-accent-d) !important; }
      /* 今日だけ塗りつぶしで強調 */
      .day-rel.is-today { background: var(--app-accent) !important; color: #fff !important; }
      .day-count  { font-size: 11px; color: var(--app-muted) !important; margin-left: auto; }

      /* ══ 1件ぶんの行 ══ */
      .item-row {
        display: flex;
        align-items: flex-start;
        gap: 10px;
        padding: 9px 12px;
        border-radius: 10px;
        border-left: 5px solid var(--accent);
        background: var(--bg);
        margin: 5px 0;
      }
      .item-row.done { opacity: .42; }
      .item-row.done .item-title { text-decoration: line-through; }

      .item-time {
        flex: 0 0 52px;
        font-size: 13px;
        font-weight: 800;
        color: var(--accent) !important;
        padding-top: 1px;
        font-variant-numeric: tabular-nums;
      }
      .item-body  { flex: 1 1 auto; min-width: 0; }
      .item-title { font-size: 15px; font-weight: 600; }
      .item-meta  { font-size: 12px; color: var(--app-muted) !important; margin-top: 4px; }

      /* カテゴリの色付きラベル。文字は必ず白にしたいので !important を付ける
         （上で .stApp span の文字色を指定しているため、それに負けないように） */
      .cat-pill {
        display: inline-block; font-size: 10.5px; font-weight: 800;
        padding: 2px 9px; border-radius: 999px;
        color: #fff !important; background: var(--accent);
        margin-right: 8px; vertical-align: 2px;
      }
      .chip {
        display: inline-block; font-size: 11px; padding: 1px 8px;
        border-radius: 6px; background: var(--chip); margin-right: 6px;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# session_state の初期化
# ---------------------------------------------------------------------------
for key, default in [("pending", None), ("pending_raw", ""), ("pending_model", ""),
                     ("shift_pending", None), ("shift_meta", {})]:
    if key not in st.session_state:
        st.session_state[key] = default

# ---------------------------------------------------------------------------
# サイドバー
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ 設定")

    has_claude = bool(os.getenv("ANTHROPIC_API_KEY"))
    has_gemini = bool(os.getenv("GEMINI_API_KEY"))

    options = ["オフライン簡易分類（APIキー不要）"]
    if has_gemini:
        options.insert(0, "Gemini API")
    if has_claude:
        options.insert(0, "Claude API")

    choice = st.selectbox("AIの種類", options)
    provider = {
        "Claude API": "claude",
        "Gemini API": "gemini",
        "オフライン簡易分類（APIキー不要）": "offline",
    }[choice]

    if provider == "claude":
        model = st.selectbox(
            "モデル", ["claude-haiku-4-5", "claude-sonnet-5"],
            help="haiku は安くて速い。精度が欲しい時だけ sonnet に。",
        )
    elif provider == "gemini":
        model = st.selectbox("モデル", ["gemini-3.6-flash", "gemini-2.5-pro"])
    else:
        model = None
        st.info(".env に APIキーを入れると AI分類が使えるで。今はルールベースで動いてる。")

    st.divider()
    st.caption(f"📅 今日: {dateparse.label_for(date.today().isoformat())}")
    st.caption("📦 保存件数")
    counts = db.count_by_category()
    if counts:
        for cat in db.CATEGORIES:
            if counts.get(cat):
                s = CATEGORY_STYLE.get(cat, DEFAULT_STYLE)
                st.write(f"{s['icon']} {cat}: **{counts[cat]}** 件")
    else:
        st.write("まだ0件")

# ---------------------------------------------------------------------------
# 1件ぶんの行を描く
# ---------------------------------------------------------------------------

def render_item(row) -> None:
    style = CATEGORY_STYLE.get(row["category"], DEFAULT_STYLE)
    accent = style["color"]
    done = row["status"] == "完了"

    # ★ユーザーが書いた文字は必ず html.escape() を通す（XSS対策）★
    title = html.escape(row["title"])

    # 左端の時刻。時刻が無いものは「・」で高さを揃える
    time_label = row["start_at"][11:16] if row["start_at"] else "・"

    chips = []
    if row["due_date"]:
        chips.append(f"⏳ 締切 {row['due_date'][5:].replace('-', '/')}")
    if row["date_text"] and not row["event_date"]:
        chips.append(f"❓ {html.escape(row['date_text'])}")
    imp = row["importance"]
    if imp and imp >= 4 and row["category"] in ("タスク", "やりたいこと"):
        chips.append("★" * imp)
    if row["calendar_synced"]:
        chips.append("📤 カレンダー出力済")
    for t in json.loads(row["tags"] or "[]"):
        chips.append(f"#{html.escape(str(t))}")

    meta_bits = []
    if row["detail"]:
        meta_bits.append(html.escape(row["detail"]))
    chip_html = "".join(f'<span class="chip">{c}</span>' for c in chips)
    meta_html = ""
    if meta_bits or chip_html:
        inner = " ".join(meta_bits)
        meta_html = f'<div class="item-meta">{inner} {chip_html}</div>'

    st.markdown(
        f"""
        <div class="item-row {'done' if done else ''}"
             style="--accent:{accent}; --bg:{hex_to_rgba(accent, 0.10)};
                    --chip:{hex_to_rgba(accent, 0.18)};">
          <div class="item-time">{time_label}</div>
          <div class="item-body">
            <span class="cat-pill">{style['icon']} {row['category']}</span>
            <span class="item-title">{title}</span>
            {meta_html}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def day_header_html(day: str | None, count: int, today_str: str) -> str:
    """日付カードの見出しHTMLを組み立てる。"""
    if day == "__created__":
        title, rel, cls = "登録した順", "", ""
    elif day:
        # label_for は "9月18日(金) · 今日" の形。念のため区切りが無い場合も想定する
        parts = dateparse.label_for(day).split(" · ")
        title = parts[0]
        rel = parts[1] if len(parts) > 1 else ""
        cls = "is-today" if day == today_str else ""
    else:
        title, rel, cls = "📌 日付なし", "買い物・メモなど", ""

    rel_html = f'<span class="day-rel {cls}">{rel}</span>' if rel else ""
    return (
        f'<div class="day-head"><span class="day-date">{title}</span>'
        f'{rel_html}<span class="day-count">{count} 件</span></div>'
    )


def group_by_day(rows) -> "OrderedDict[str | None, list]":
    """行のリストを日付ごとにまとめる。

    fetch_items がすでに日付順で返してくれているので、
    上から順に詰めていくだけで日付ごとの塊ができる。
    """
    groups: OrderedDict = OrderedDict()
    for r in rows:
        groups.setdefault(r["event_date"], []).append(r)
    return groups


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
st.title("⚙️ admin")
st.caption("思いついたことを雑に書いて放り込むだけ。AIが仕分けして、日付ごとにまとめる。")

tab_input, tab_shift, tab_list, tab_raw = st.tabs(
    ["✍️ 入力", "📸 シフト取込", "📋 タイムライン", "🗂 原文ログ"]
)

# =========================== ①入力タブ ===========================
with tab_input:
    text = st.text_area(
        "思いついたことを、そのまま書いて",
        height=180,
        placeholder="今日12時に起きた\n昨日オルタネーターが壊れた\n18時からバイト\n来週の水曜までにレポート提出\n牛乳買う",
    )

    col_a, _ = st.columns([1, 4])
    with col_a:
        run = st.button("🤖 AIで整理する", type="primary", width="stretch")

    if run:
        if not text.strip():
            st.warning("何か書いてから押してな")
        else:
            with st.spinner("AIが仕分け中..."):
                try:
                    items, used_model = ai.classify(text, provider=provider, model=model)
                    if not items:
                        st.warning("項目を1つも取り出せへんかった。書き方を変えて試してみて。")
                    else:
                        st.session_state.pending = items
                        st.session_state.pending_raw = text
                        st.session_state.pending_model = used_model
                except Exception as e:  # noqa: BLE001
                    st.error(f"AIの呼び出しでエラーが出た: {e}")
                    st.caption("APIキー、ネット接続、モデル名をまず確認してみて。")

    if st.session_state.pending:
        st.divider()
        st.subheader("AIの分類結果（保存前に直せるで）")
        st.caption("日付は Python 側で検算済み。おかしければ直接書き換えてOK。")

        df = pd.DataFrame(st.session_state.pending)
        df["保存する"] = True

        edited = st.data_editor(
            df[["保存する", "category", "title", "date_text", "event_date",
                "start_at", "importance", "confidence"]],
            column_config={
                "保存する": st.column_config.CheckboxColumn(width="small"),
                "category": st.column_config.SelectboxColumn(
                    "カテゴリ", options=db.CATEGORIES, width="small"
                ),
                "title": st.column_config.TextColumn("タイトル", width="medium"),
                "date_text": st.column_config.TextColumn("原文の表現", width="small"),
                "event_date": st.column_config.TextColumn("→ 実際の日付", width="small"),
                "start_at": st.column_config.TextColumn("開始日時", width="small"),
                "importance": st.column_config.NumberColumn(
                    "重要度", min_value=1, max_value=5, step=1, width="small"
                ),
                "confidence": st.column_config.ProgressColumn(
                    "自信度", min_value=0.0, max_value=1.0, format="%.2f"
                ),
            },
            hide_index=True,
            width="stretch",
            key="editor",
        )

        c1, c2 = st.columns(2)
        with c1:
            if st.button("💾 保存する", type="primary", width="stretch"):
                selected = edited[edited["保存する"]]
                if selected.empty:
                    st.warning("保存する行が1つも選ばれてへんで")
                else:
                    to_save = []
                    for idx, row in selected.iterrows():
                        rec = row.to_dict()
                        original = st.session_state.pending[idx]
                        rec["detail"] = original.get("detail", "")
                        rec["tags"] = original.get("tags", [])
                        rec["due_date"] = original.get("due_date")
                        rec["end_at"] = original.get("end_at")
                        rec["all_day"] = original.get("all_day", 1)
                        rec["estimated_minutes"] = original.get("estimated_minutes")
                        # 画面で日付を手書きされた可能性があるので形式を検証する。
                        # 不正な文字列のまま保存すると、一覧の並び替えが壊れる。
                        rec["event_date"] = ai._valid_date(rec.get("event_date"))
                        if not rec["event_date"]:
                            rec["due_date"] = None
                            rec["start_at"] = None
                        if rec.get("event_date") and original.get("start_at"):
                            rec["start_at"] = f"{rec['event_date']}T{original['start_at'][11:16]}"
                        to_save.append(rec)

                    note_id = db.insert_raw_note(st.session_state.pending_raw)
                    n = db.insert_items(to_save, note_id, st.session_state.pending_model)
                    st.session_state.pending = None
                    st.success(f"{n} 件を保存したで！")
                    st.rerun()
        with c2:
            if st.button("🗑 破棄する", width="stretch"):
                st.session_state.pending = None
                st.rerun()

# =========================== ②シフト取込タブ ===========================
with tab_shift:
    st.caption(
        "バイトのシフト表を写真で撮ってアップすると、AIが自分の勤務だけを抜き出して一括登録する。"
    )

    s1, s2 = st.columns(2)
    with s1:
        person = st.text_input(
            "シフト表で探す名前", placeholder="例: 瀧本",
            help="表の中からこの文字列を含む行（列）を探して、その人の勤務だけを拾う",
        )
    with s2:
        workplace = st.text_input("勤務先の名前", value="バイト", placeholder="例: すき家 普天間店")

    uploaded = st.file_uploader(
        "シフト表の画像", type=["png", "jpg", "jpeg", "webp"],
        help="スマホで撮った写真でOK。傾いてても読める。送信前に自動で縮小する。",
    )

    hint = st.text_input(
        "補足（任意）", placeholder="例: 表の左上に2026年10月と書いてある",
        help="年月が写ってない・読みにくい時にここで教えると精度が上がる",
    )

    if uploaded:
        st.image(uploaded, caption="読み取る画像", width=420)

    can_use_ai = provider in ("claude", "gemini")
    if not can_use_ai:
        st.warning(
            "画像の読み取りにはAPIキーが必要やで。"
            ".env に ANTHROPIC_API_KEY か GEMINI_API_KEY を入れてな。"
            "キー無しでも、下の「テキストで貼り付け」なら使える。"
        )

    with st.expander("⌨️ 画像が使えないときはテキストで貼り付け"):
        pasted = st.text_area(
            "1行1シフトで貼り付け",
            height=120,
            placeholder="9/21(月) 18:00〜23:00\n9/23(水) 17時〜22時\n9/25 22:00-2:00",
        )

    if st.button("🔍 シフトを読み取る", type="primary"):
        if not uploaded and not pasted.strip():
            st.warning("画像をアップするか、テキストを貼り付けてな")
        elif uploaded and not person.strip():
            st.warning("シフト表の中から探す名前を入れてな（これが無いと誰の勤務か分からん）")
        else:
            with st.spinner("AIがシフト表を読み取り中..."):
                try:
                    items, used = shift.extract(
                        image_bytes=uploaded.getvalue() if uploaded else None,
                        pasted_text=pasted,
                        person_name=person.strip(),
                        workplace=workplace.strip() or "バイト",
                        provider=provider,
                        model=model,
                        hint=hint.strip(),
                    )
                    if not items:
                        st.warning(
                            "勤務を1件も見つけられへんかった。名前の表記（漢字・カナ）を変えるか、"
                            "写真を明るく撮り直してみて。"
                        )
                    else:
                        st.session_state.shift_pending = items
                        st.session_state.shift_meta = {
                            "model": used,
                            "source": "shift_image" if uploaded else "shift_text",
                            "name": uploaded.name if uploaded else "テキスト貼り付け",
                            "workplace": workplace.strip() or "バイト",
                        }
                except Exception as e:  # noqa: BLE001
                    st.error(f"読み取りでエラーが出た: {e}")

    # --- 読み取り結果の確認 ---
    if st.session_state.shift_pending:
        st.divider()
        items = st.session_state.shift_pending
        st.subheader(f"読み取り結果：{len(items)} 件")

        # すでに登録済みの勤務は、チェックを外した状態で出す（二重登録の防止）
        existing = db.existing_schedule_keys()

        rows = []
        for it in items:
            dup = (it["event_date"], it["start_at"]) in existing
            rows.append(
                {
                    "登録する": not dup,
                    "重複": "⚠️ 登録済" if dup else "",
                    "日付": it["event_date"],
                    "開始": it["start_at"][11:16],
                    "終了": it["end_at"][11:16] if it["end_at"] else "",
                    "時間": f"{(it['estimated_minutes'] or 0) / 60:.1f}h",
                    "読取元": it["date_text"] or "",
                    "自信度": it["confidence"],
                }
            )

        dup_count = sum(1 for r in rows if r["重複"])
        if dup_count:
            st.info(f"{dup_count} 件はすでに登録済みやったから、チェックを外してあるで。")

        edited = st.data_editor(
            pd.DataFrame(rows),
            column_config={
                "登録する": st.column_config.CheckboxColumn(width="small"),
                "重複": st.column_config.TextColumn(width="small", disabled=True),
                "日付": st.column_config.TextColumn(width="small"),
                "開始": st.column_config.TextColumn(width="small"),
                "終了": st.column_config.TextColumn(width="small"),
                "時間": st.column_config.TextColumn(width="small", disabled=True),
                "読取元": st.column_config.TextColumn(width="medium", disabled=True),
                "自信度": st.column_config.ProgressColumn(
                    min_value=0.0, max_value=1.0, format="%.2f"
                ),
            },
            hide_index=True,
            width="stretch",
            key="shift_editor",
        )

        total_h = sum(
            (items[i]["estimated_minutes"] or 0)
            for i in edited[edited["登録する"]].index
        ) / 60
        st.caption(f"登録予定: {int(edited['登録する'].sum())} 件 ／ 合計 {total_h:.1f} 時間")

        b1, b2 = st.columns(2)
        with b1:
            if st.button("📥 カレンダーに一括登録", type="primary", width="stretch"):
                selected = edited[edited["登録する"]]
                if selected.empty:
                    st.warning("登録する行が1つも選ばれてへんで")
                else:
                    # 画面で修正された日付・時刻を、もう一度 to_items に通して検証する。
                    # こうすると深夜またぎの計算などが自動でやり直される。
                    meta = st.session_state.shift_meta
                    raw_rows = [
                        {
                            "date": r["日付"],
                            "start": r["開始"],
                            "end": r["終了"],
                            "raw": r["読取元"],
                            "confidence": r["自信度"],
                        }
                        for _, r in selected.iterrows()
                    ]
                    to_save = shift.to_items(raw_rows, meta.get("workplace", "バイト"))

                    if not to_save:
                        st.error("日付か時刻の形式が正しくないみたいや。書き方を確認してな。")
                    else:
                        body = f"[シフト表取込] {meta.get('name')}\n" + "\n".join(
                            f"{i['event_date']} {i['title']}" for i in to_save
                        )
                        note_id = db.insert_raw_note(body, source=meta.get("source", "shift_image"))
                        n = db.insert_items(to_save, note_id, meta.get("model", "unknown"))
                        st.session_state.shift_pending = None
                        st.success(f"{n} 件のシフトを登録したで！タイムラインと .ics 出力にも反映済み。")
                        st.rerun()
        with b2:
            if st.button("🗑 読み取り結果を破棄", width="stretch"):
                st.session_state.shift_pending = None
                st.rerun()


# =========================== ③タイムラインタブ ===========================
with tab_list:
    # --- カテゴリ絞り込み（タブ風ボタン） ---
    # st.segmented_control は横並びのボタン型セレクタ。
    # ドロップダウンと違って「今どれが選ばれてるか」が一目で分かる。
    tab_options = ["すべて"] + db.CATEGORIES
    picked = st.segmented_control(
        "カテゴリ", tab_options, default="すべて", label_visibility="collapsed"
    )
    if picked is None:          # 選択解除されたら「すべて」に戻す
        picked = "すべて"
    sel_cats = None if picked == "すべて" else [picked]

    c1, c2, c3 = st.columns([3, 2, 2.4])
    with c1:
        keyword = st.text_input("キーワード検索", "", placeholder="🔍 タイトル・詳細から探す")
    with c2:
        hide_done = st.toggle("完了を隠す", value=False)
    with c3:
        order_label = st.selectbox("並び順", ["新しい日付から", "古い日付から", "登録した順"])

    order = "created" if order_label == "登録した順" else "timeline"
    descending = order_label != "古い日付から"
    statuses = [s for s in db.STATUSES if s != "完了"] if hide_done else None

    rows = db.fetch_items(sel_cats, statuses, keyword, order, descending)

    # --- .ics 書き出し ---
    with st.expander("📤 カレンダーに取り込む（.icsファイル出力）"):
        e1, e2 = st.columns([3, 2])
        with e1:
            export_cats = st.multiselect(
                "出力するカテゴリ", db.CATEGORIES, default=["予定"],
                help="日付が入っている項目だけが対象になる",
            )
        with e2:
            include_done = st.checkbox("完了したものも含める", value=False)

        export_rows = db.fetch_items(export_cats or None, None, "", "timeline", False)
        export_rows = calendar_export.exportable(export_rows)
        if not include_done:
            export_rows = [r for r in export_rows if r["status"] != "完了"]

        if not export_rows:
            st.caption("出力できる予定がまだ無いで（日付が入っている項目が対象）")
        else:
            ics_text, export_ids = calendar_export.build_ics(export_rows)
            filename = f"memo_{date.today().strftime('%Y%m%d')}.ics"
            clicked = st.download_button(
                f"📅 {len(export_rows)} 件を .ics でダウンロード",
                data=ics_text.encode("utf-8"),
                file_name=filename,
                mime="text/calendar",
                type="primary",
            )
            if clicked:
                for i in export_ids:
                    db.update_item(i, calendar_synced=1)

            st.caption(
                "**取り込み方** ／ スマホ: ダウンロードしたファイルをタップ → "
                "カレンダーアプリを選ぶ → TimeTreeへ取り込み ／ "
                "PC: Googleカレンダー → 設定 → インポート で読み込み、"
                "TimeTree側で「外部カレンダーを表示」に設定しておくと自動で見えるようになる。"
            )

    st.divider()

    # --- 日付ごとにまとめて表示 ---
    if not rows:
        st.info("まだ何もないで。入力タブから書いてみて。")
    else:
        st.caption(f"{len(rows)} 件")
        today_str = date.today().isoformat()

        # 登録順のときは日付でまとめず、1枚のカードに全部並べる
        if order == "created":
            day_groups = {"__created__": rows}
        else:
            day_groups = group_by_day(rows)

        for day, items in day_groups.items():
            with st.container(border=True):
                st.markdown(day_header_html(day, len(items), today_str),
                            unsafe_allow_html=True)

                for r in items:
                    c_item, c_b1, c_b2 = st.columns([9, 1.1, 0.7])
                    with c_item:
                        render_item(r)
                    with c_b1:
                        if r["status"] == "完了":
                            if st.button("戻す", key=f"undo_{r['id']}", width="stretch"):
                                db.update_item(r["id"], status="未着手")
                                st.rerun()
                        else:
                            if st.button("完了", key=f"done_{r['id']}", width="stretch"):
                                db.update_item(r["id"], status="完了")
                                st.rerun()
                    with c_b2:
                        if st.button("🗑", key=f"del_{r['id']}", width="stretch"):
                            db.delete_item(r["id"])
                            st.rerun()

# =========================== ④原文ログタブ ===========================
with tab_raw:
    st.caption("AIが分類する前の、書いたそのままの文章。分類がおかしい時はここを見返す。")
    notes = db.fetch_raw_notes()
    if not notes:
        st.info("まだ記録なし")
    for n in notes:
        with st.expander(f"#{n['id']}  {n['created_at']}  ／  {n['source']}"):
            st.text(n["body"])
