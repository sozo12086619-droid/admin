import os
import sys
from pathlib import Path
import psycopg2

# ルートディレクトリの config を読み込めるようにパスを追加
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
import config

DATABASE_URL = config.DATABASE_URL or os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL が設定されていません")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

DATA = [
    # --- 2025年07月 ---
    {"date": "2025-07-31", "type": "income", "category": "給与", "amount": 102419, "memo": "7月給与合計"},
    {"date": "2025-07-31", "type": "expense", "category": "食費", "amount": 33988, "memo": "食費"},
    {"date": "2025-07-31", "type": "expense", "category": "趣味", "amount": 37900, "memo": "趣味"},
    {"date": "2025-07-31", "type": "expense", "category": "衣服", "amount": 4200, "memo": "衣服"},
    {"date": "2025-07-31", "type": "expense", "category": "交通費", "amount": 3100, "memo": "交通費"},
    {"date": "2025-07-31", "type": "expense", "category": "日用品", "amount": 880, "memo": "日用品"},
    {"date": "2025-07-31", "type": "expense", "category": "その他", "amount": 560, "memo": "その他"},
    # --- 2025年08月 ---
    {"date": "2025-08-31", "type": "income", "category": "給与", "amount": 236937, "memo": "8月給与合計"},
    {"date": "2025-08-31", "type": "expense", "category": "趣味", "amount": 144656, "memo": "趣味"},
    {"date": "2025-08-31", "type": "expense", "category": "食費", "amount": 47474, "memo": "食費"},
    {"date": "2025-08-31", "type": "expense", "category": "交際費", "amount": 6080, "memo": "交際費"},
    {"date": "2025-08-31", "type": "expense", "category": "日用品", "amount": 3077, "memo": "日用品"},
    {"date": "2025-08-31", "type": "expense", "category": "その他", "amount": 2884, "memo": "その他"},
    {"date": "2025-08-31", "type": "expense", "category": "交通費", "amount": 2800, "memo": "交通費"},
    # --- 2025年09月 ---
    {"date": "2025-09-30", "type": "income", "category": "給与", "amount": 139957, "memo": "9月給与合計"},
    {"date": "2025-09-30", "type": "expense", "category": "趣味", "amount": 90679, "memo": "趣味"},
    {"date": "2025-09-30", "type": "expense", "category": "食費", "amount": 27374, "memo": "食費"},
    {"date": "2025-09-30", "type": "expense", "category": "日用品", "amount": 12800, "memo": "日用品"},
    {"date": "2025-09-30", "type": "expense", "category": "外食費", "amount": 3834, "memo": "外食費"},
    {"date": "2025-09-30", "type": "expense", "category": "自分磨き", "amount": 400, "memo": "自分磨き"},
    # --- 2025年10月 ---
    {"date": "2025-10-31", "type": "income", "category": "給与", "amount": 261215, "memo": "10月給与合計"},
    {"date": "2025-10-31", "type": "expense", "category": "自分磨き", "amount": 143578, "memo": "自分磨き"},
    {"date": "2025-10-31", "type": "expense", "category": "趣味", "amount": 34438, "memo": "趣味"},
    {"date": "2025-10-31", "type": "expense", "category": "食費", "amount": 14201, "memo": "食費"},
    {"date": "2025-10-31", "type": "expense", "category": "日用品", "amount": 12777, "memo": "日用品"},
    # --- 2025年11月 ---
    {"date": "2025-11-30", "type": "income", "category": "給与", "amount": 107482, "memo": "11月給与合計"},
    {"date": "2025-11-30", "type": "expense", "category": "趣味", "amount": 55694, "memo": "趣味"},
    {"date": "2025-11-30", "type": "expense", "category": "自分磨き", "amount": 55398, "memo": "自分磨き"},
    {"date": "2025-11-30", "type": "expense", "category": "その他", "amount": 50000, "memo": "その他"},
    {"date": "2025-11-30", "type": "expense", "category": "日用品", "amount": 21950, "memo": "日用品"},
    {"date": "2025-11-30", "type": "expense", "category": "食費", "amount": 10010, "memo": "食費"},
    {"date": "2025-11-30", "type": "expense", "category": "交際費", "amount": 570, "memo": "交際費"},
    # --- 2025年12月 ---
    {"date": "2025-12-31", "type": "income", "category": "給与", "amount": 143189, "memo": "12月給与合計"},
    {"date": "2025-12-31", "type": "expense", "category": "自分磨き", "amount": 80791, "memo": "自分磨き"},
    {"date": "2025-12-31", "type": "expense", "category": "趣味", "amount": 28093, "memo": "趣味"},
    {"date": "2025-12-31", "type": "expense", "category": "食費", "amount": 6799, "memo": "食費"},
    {"date": "2025-12-31", "type": "expense", "category": "交際費", "amount": 4310, "memo": "交際費"},
    {"date": "2025-12-31", "type": "expense", "category": "日用品", "amount": 1288, "memo": "日用品"},
    # --- 2026年01月 ---
    {"date": "2026-01-31", "type": "income", "category": "給与", "amount": 52313, "memo": "1月給与合計"},
    {"date": "2026-01-31", "type": "expense", "category": "趣味", "amount": 122890, "memo": "趣味"},
    {"date": "2026-01-31", "type": "expense", "category": "食費", "amount": 63458, "memo": "食費"},
    {"date": "2026-01-31", "type": "expense", "category": "日用品", "amount": 6229, "memo": "日用品"},
    {"date": "2026-01-31", "type": "expense", "category": "交際費", "amount": 700, "memo": "交際費"},
    {"date": "2026-01-31", "type": "expense", "category": "その他", "amount": 50, "memo": "その他"},
    # --- 2026年02月 ---
    {"date": "2026-02-28", "type": "income", "category": "給与", "amount": 94947, "memo": "2月給与合計"},
    {"date": "2026-02-28", "type": "expense", "category": "趣味", "amount": 34789, "memo": "趣味"},
    {"date": "2026-02-28", "type": "expense", "category": "自分磨き", "amount": 30800, "memo": "自分磨き"},
    {"date": "2026-02-28", "type": "expense", "category": "食費", "amount": 14517, "memo": "食費"},
    {"date": "2026-02-28", "type": "expense", "category": "日用品", "amount": 6328, "memo": "日用品"},
    {"date": "2026-02-28", "type": "expense", "category": "交際費", "amount": 2234, "memo": "交際費"},
    {"date": "2026-02-28", "type": "expense", "category": "外食費", "amount": 1419, "memo": "外食費"},
    {"date": "2026-02-28", "type": "expense", "category": "その他", "amount": 510, "memo": "その他"},
    # --- 2026年03月 ---
    {"date": "2026-03-31", "type": "income", "category": "給与", "amount": 119087, "memo": "3月給与合計"},
    {"date": "2026-03-31", "type": "expense", "category": "趣味", "amount": 71000, "memo": "趣味"},
    {"date": "2026-03-31", "type": "expense", "category": "食費", "amount": 19161, "memo": "食費"},
    {"date": "2026-03-31", "type": "expense", "category": "交際費", "amount": 10650, "memo": "交際費"},
    {"date": "2026-03-31", "type": "expense", "category": "その他", "amount": 9765, "memo": "その他"},
    {"date": "2026-03-31", "type": "expense", "category": "日用品", "amount": 7574, "memo": "日用品"},
    # --- 2026年04月 ---
    {"date": "2026-04-30", "type": "income", "category": "給与", "amount": 60557, "memo": "4月給与合計"},
    {"date": "2026-04-30", "type": "expense", "category": "自分磨き", "amount": 34920, "memo": "自分磨き"},
    {"date": "2026-04-30", "type": "expense", "category": "食費", "amount": 17317, "memo": "食費"},
    {"date": "2026-04-30", "type": "expense", "category": "その他", "amount": 16483, "memo": "その他"},
    {"date": "2026-04-30", "type": "expense", "category": "日用品", "amount": 8999, "memo": "日用品"},
    {"date": "2026-04-30", "type": "expense", "category": "趣味", "amount": 2500, "memo": "趣味"},
    # --- 2026年05月 ---
    {"date": "2026-05-31", "type": "income", "category": "給与", "amount": 147402, "memo": "5月給与合計"},
    {"date": "2026-05-31", "type": "expense", "category": "趣味", "amount": 41748, "memo": "趣味"},
    {"date": "2026-05-31", "type": "expense", "category": "食費", "amount": 27075, "memo": "食費"},
    {"date": "2026-05-31", "type": "expense", "category": "自分磨き", "amount": 24902, "memo": "自分磨き"},
    {"date": "2026-05-31", "type": "expense", "category": "日用品", "amount": 15019, "memo": "日用品"},
    {"date": "2026-05-31", "type": "expense", "category": "その他", "amount": 14580, "memo": "その他"},
    {"date": "2026-05-31", "type": "expense", "category": "交際費", "amount": 3168, "memo": "交際費"},
    {"date": "2026-05-31", "type": "expense", "category": "交通費", "amount": 3100, "memo": "交通費"},
    # --- 2026年06月 ---
    {"date": "2026-06-30", "type": "income", "category": "給与", "amount": 170708, "memo": "6月給与合計"},
    {"date": "2026-06-30", "type": "expense", "category": "自分磨き", "amount": 79780, "memo": "自分磨き"},
    {"date": "2026-06-30", "type": "expense", "category": "交際費", "amount": 34590, "memo": "交際費"},
    {"date": "2026-06-30", "type": "expense", "category": "食費", "amount": 27098, "memo": "食費"},
    {"date": "2026-06-30", "type": "expense", "category": "日用品", "amount": 19159, "memo": "日用品"},
    {"date": "2026-06-30", "type": "expense", "category": "ガソリン", "amount": 3500, "memo": "ガソリン"},
    {"date": "2026-06-30", "type": "expense", "category": "趣味", "amount": 3030, "memo": "趣味"},
    {"date": "2026-06-30", "type": "expense", "category": "その他", "amount": 2970, "memo": "その他"},
    # --- 2026年07月 ---
    {"date": "2026-07-31", "type": "income", "category": "給与", "amount": 78204, "memo": "7月給与合計"},
    {"date": "2026-07-31", "type": "expense", "category": "自分磨き", "amount": 34078, "memo": "自分磨き"},
    {"date": "2026-07-31", "type": "expense", "category": "食費", "amount": 33401, "memo": "食費"},
    {"date": "2026-07-31", "type": "expense", "category": "日用品", "amount": 12000, "memo": "日用品"},
    {"date": "2026-07-31", "type": "expense", "category": "趣味", "amount": 9079, "memo": "趣味"},
    {"date": "2026-07-31", "type": "expense", "category": "交際費", "amount": 7925, "memo": "交際費"},
    {"date": "2026-07-31", "type": "expense", "category": "Amazon", "amount": 5312, "memo": "Amazon"},
    {"date": "2026-07-31", "type": "expense", "category": "ガソリン", "amount": 4800, "memo": "ガソリン"},
    # --- 2026年08月 ---
    {"date": "2026-08-31", "type": "income", "category": "給与", "amount": 117308, "memo": "8月給与合計"},
    {"date": "2026-08-31", "type": "expense", "category": "趣味", "amount": 69119, "memo": "趣味"},
    {"date": "2026-08-31", "type": "expense", "category": "食費", "amount": 22352, "memo": "食費"},
    {"date": "2026-08-31", "type": "expense", "category": "日用品", "amount": 13028, "memo": "日用品"},
    {"date": "2026-08-31", "type": "expense", "category": "ガソリン", "amount": 4033, "memo": "ガソリン"},
    {"date": "2026-08-31", "type": "expense", "category": "交際費", "amount": 3276, "memo": "交際費"},
    {"date": "2026-08-31", "type": "expense", "category": "その他", "amount": 160, "memo": "その他"},

    # --- 2026年09月 ---
    {"date": "2026-09-01", "type": "expense", "category": "趣味", "amount": 1180, "memo": "Appleサービス(PayPay)"},
    {"date": "2026-09-01", "type": "income", "category": "臨時収入", "amount": 900, "memo": "217さん受取(PayPay)"},
    {"date": "2026-09-02", "type": "expense", "category": "食費", "amount": 935, "memo": "VISAデビット"},
    {"date": "2026-09-02", "type": "expense", "category": "食費", "amount": 280, "memo": "すき家(PayPay)"},
    {"date": "2026-09-02", "type": "expense", "category": "食費", "amount": 677, "memo": "サンエー(PayPay)"},
    {"date": "2026-09-03", "type": "expense", "category": "食費", "amount": 210, "memo": "すき家(PayPay)"},
    {"date": "2026-09-04", "type": "expense", "category": "食費", "amount": 146, "memo": "VISAデビット"},
    {"date": "2026-09-04", "type": "expense", "category": "食費", "amount": 890, "memo": "VISAデビット"},
    {"date": "2026-09-04", "type": "expense", "category": "食費", "amount": 1825, "memo": "VISAデビット"},
    {"date": "2026-09-05", "type": "expense", "category": "食費", "amount": 151, "memo": "ファミリーマート(PayPay)"},
    {"date": "2026-09-07", "type": "expense", "category": "趣味", "amount": 50, "memo": "Appleサービス(PayPay)"},
    {"date": "2026-09-07", "type": "expense", "category": "趣味", "amount": 1900, "memo": "Appleサービス(PayPay)"},
    {"date": "2026-09-07", "type": "expense", "category": "日用品", "amount": 990, "memo": "Amazon(PayPay)"},
    {"date": "2026-09-07", "type": "expense", "category": "食費", "amount": 862, "memo": "セブン-イレブン(PayPay)"},
    {"date": "2026-09-07", "type": "expense", "category": "日用品", "amount": 1782, "memo": "Amazon(PayPay)"},
    {"date": "2026-09-08", "type": "expense", "category": "日用品", "amount": 2692, "memo": "VISAデビット"},
    {"date": "2026-09-08", "type": "expense", "category": "食費", "amount": 270, "memo": "すき家(PayPay)"},
    {"date": "2026-09-08", "type": "expense", "category": "食費", "amount": 108, "memo": "セブン-イレブン(PayPay)"},
    {"date": "2026-09-09", "type": "expense", "category": "食費", "amount": 2912, "memo": "ユニオン(レシート)"},
    {"date": "2026-09-09", "type": "expense", "category": "食費", "amount": 7314, "memo": "ユニオン(レシート)"},
    {"date": "2026-09-09", "type": "expense", "category": "その他", "amount": 5336, "memo": "口座出金"},
    {"date": "2026-09-09", "type": "income", "category": "臨時収入", "amount": 1000, "memo": "217さん受取(PayPay)"},
    {"date": "2026-09-10", "type": "income", "category": "臨時収入", "amount": 1000, "memo": "217さん受取(PayPay)"},
    {"date": "2026-09-11", "type": "expense", "category": "趣味", "amount": 600, "memo": "Amazonプライム(PayPay)"},
    {"date": "2026-09-11", "type": "expense", "category": "日用品", "amount": 1210, "memo": "ダイソー(PayPay)"},
    {"date": "2026-09-14", "type": "expense", "category": "食費", "amount": 210, "memo": "すき家(PayPay)"},
    {"date": "2026-09-14", "type": "expense", "category": "食費", "amount": 108, "memo": "セブン-イレブン(PayPay)"},
    {"date": "2026-09-15", "type": "expense", "category": "食費", "amount": 210, "memo": "VISAデビット"},
    {"date": "2026-09-16", "type": "expense", "category": "日用品", "amount": 3657, "memo": "VISAデビット"},
    {"date": "2026-09-16", "type": "expense", "category": "食費", "amount": 108, "memo": "セブン-イレブン(PayPay)"},
    {"date": "2026-09-16", "type": "expense", "category": "日用品", "amount": 3727, "memo": "Amazon(PayPay)"},
    {"date": "2026-09-17", "type": "expense", "category": "食費", "amount": 344, "memo": "ユニオン(レシート)"},
    {"date": "2026-09-17", "type": "expense", "category": "食費", "amount": 640, "memo": "すき家(PayPay)"},
    {"date": "2026-09-17", "type": "income", "category": "臨時収入", "amount": 300, "memo": "217さん受取(PayPay)"},
    {"date": "2026-09-19", "type": "expense", "category": "自分磨き", "amount": 77220, "memo": "VISAデビット(クリニック等)"},
    {"date": "2026-09-21", "type": "expense", "category": "食費", "amount": 280, "memo": "VISAデビット"},
    {"date": "2026-09-21", "type": "expense", "category": "食費", "amount": 135, "memo": "VISAデビット"},
    {"date": "2026-09-22", "type": "expense", "category": "食費", "amount": 210, "memo": "VISAデビット"},
    {"date": "2026-09-23", "type": "expense", "category": "食費", "amount": 4853, "memo": "ユニオン(レシート)"},
    {"date": "2026-09-23", "type": "expense", "category": "日用品", "amount": 2296, "memo": "VISAデビット"},
    {"date": "2026-09-23", "type": "expense", "category": "趣味", "amount": 470, "memo": "Appleサービス(PayPay)"},
    {"date": "2026-09-23", "type": "expense", "category": "趣味", "amount": 50, "memo": "Appleサービス(PayPay)"},
    {"date": "2026-09-23", "type": "expense", "category": "食費", "amount": 108, "memo": "セブン-イレブン(PayPay)"},
    {"date": "2026-09-23", "type": "expense", "category": "食費", "amount": 267, "memo": "サンエー(PayPay)"},
    {"date": "2026-09-25", "type": "expense", "category": "食費", "amount": 210, "memo": "すき家(PayPay)"},
    {"date": "2026-09-25", "type": "expense", "category": "食費", "amount": 108, "memo": "セブン-イレブン(PayPay)"},
    {"date": "2026-09-25", "type": "expense", "category": "食費", "amount": 320, "memo": "すき家(PayPay)"},
    {"date": "2026-09-25", "type": "expense", "category": "日用品", "amount": 682, "memo": "マツモトキヨシ(PayPay)"},
    {"date": "2026-09-25", "type": "expense", "category": "日用品", "amount": 2095, "memo": "Amazon(PayPay)"},
    {"date": "2026-09-25", "type": "income", "category": "臨時収入", "amount": 1000, "memo": "217さん受取(PayPay)"},
    {"date": "2026-09-26", "type": "expense", "category": "食費", "amount": 210, "memo": "すき家(PayPay)"},
    {"date": "2026-09-27", "type": "expense", "category": "食費", "amount": 1065, "memo": "ミスタードーナツ(PayPay)"},
    {"date": "2026-09-28", "type": "expense", "category": "趣味", "amount": 5478, "memo": "カイカツFIT(ジム会費)"},
    {"date": "2026-09-28", "type": "expense", "category": "日用品", "amount": 6610, "memo": "VISAデビット"},
    {"date": "2026-09-28", "type": "expense", "category": "日用品", "amount": 1700, "memo": "VISAデビット"},
]

def run():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    user_id = config.APP_USER_ID
    print(f"Target user_id: {user_id}")

    # テーブル初期化
    cur.execute("TRUNCATE TABLE money_records RESTART IDENTITY CASCADE;")

    count = 0
    sql = """
        INSERT INTO money_records (user_id, record_date, record_type, category, title, amount, status, detail)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
    """
    for row in DATA:
        cur.execute(sql, (
            user_id,
            row["date"],
            row["type"],
            row["category"],
            row["memo"],
            row["amount"],
            "confirmed",
            ""
        ))
        count += 1

    conn.commit()
    cur.close()
    conn.close()
    print(f"Successfully inserted {count} records into money_records for user '{user_id}'!")

if __name__ == "__main__":
    run()
