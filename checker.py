"""상품 등록 검수: CSV를 SQLite에 올리고, SQL 규칙으로 자동 통과 / 사람 확인 / 반려를 나눈다."""
import csv
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "products.db"

ALLOWED_CATEGORIES = ("식품", "가전", "반려동물", "유아")
KC_REQUIRED = ("가전", "유아")  # KC 인증 번호가 있어야 등록 가능한 카테고리
BANNED_WORDS = ("최고", "100%", "최저가")  # 과장 광고 표현

# 규칙 이름 -> (결과, 위반 상품 sku와 사유를 돌려주는 SQL)
# reject: 등록 불가(필수 정보 누락 등), review: 사람이 판단해야 하는 의심 건
RULES = {
    "missing_required": ("reject", """
        SELECT sku, '필수 항목 누락: ' ||
               trim(iif(name = '', '상품명 ', '') || iif(image_url = '', '이미지 ', '') ||
                    iif(price IS NULL OR price <= 0, '가격', ''))
        FROM products
        WHERE name = '' OR image_url = '' OR price IS NULL OR price <= 0"""),
    "kc_cert_missing": ("reject", f"""
        SELECT sku, category || ' 카테고리는 KC 인증 번호 필요'
        FROM products
        WHERE category IN ({",".join("?" * len(KC_REQUIRED))}) AND kc_cert = ''"""),
    "duplicate_barcode": ("reject", """
        SELECT sku, '바코드 중복: ' || barcode
        FROM products
        WHERE barcode IN (SELECT barcode FROM products GROUP BY barcode HAVING count(*) > 1)"""),
    "price_outlier": ("review", """
        SELECT p.sku, '카테고리 평균(' || CAST(round(c.avg_price) AS INT) || '원) 대비 가격 이상'
        FROM products p
        JOIN (SELECT category, avg(price) AS avg_price FROM products WHERE price > 0 GROUP BY category) c
          ON p.category = c.category
        WHERE p.price > 0 AND (p.price < c.avg_price / 5 OR p.price > c.avg_price * 5)"""),
    "banned_words": ("review", f"""
        SELECT sku, '과장 표현 포함'
        FROM products
        WHERE {" OR ".join("instr(name, ?) > 0" for _ in BANNED_WORDS)}"""),
    "unknown_category": ("review", f"""
        SELECT sku, '등록되지 않은 카테고리: ' || category
        FROM products
        WHERE category NOT IN ({",".join("?" * len(ALLOWED_CATEGORIES))})"""),
}
PARAMS = {
    "kc_cert_missing": KC_REQUIRED,
    "banned_words": BANNED_WORDS,
    "unknown_category": ALLOWED_CATEGORIES,
}


def load_csv(csv_path, db_path=DB_PATH):
    """CSV를 products 테이블로 덮어쓴다. 올린 행 수를 돌려준다."""
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        rows = [{k: (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]
    con = sqlite3.connect(db_path)
    with con:
        con.execute("DROP TABLE IF EXISTS products")
        con.execute("""CREATE TABLE products (
            sku TEXT PRIMARY KEY, name TEXT, category TEXT, price INTEGER,
            barcode TEXT, image_url TEXT, kc_cert TEXT)""")
        con.executemany(
            "INSERT INTO products VALUES (?,?,?,?,?,?,?)",
            [(r["sku"], r["name"], r["category"],
              int(r["price"]) if r["price"].lstrip("-").isdigit() else None,
              r["barcode"], r["image_url"], r["kc_cert"]) for r in rows])
    con.close()
    return len(rows)


def run_checks(db_path=DB_PATH):
    """모든 규칙을 돌려 상품별 판정을 만든다. reject가 하나라도 있으면 반려, review만 있으면 사람 확인."""
    con = sqlite3.connect(db_path)
    skus = [s for (s,) in con.execute("SELECT sku FROM products ORDER BY sku")]
    issues = {s: [] for s in skus}
    for rule, (level, sql) in RULES.items():
        for sku, reason in con.execute(sql, PARAMS.get(rule, ())):
            issues[sku].append({"rule": rule, "level": level, "reason": reason})
    con.close()

    result = {"auto_pass": [], "human_review": [], "reject": []}
    for sku, found in issues.items():
        levels = {i["level"] for i in found}
        bucket = "reject" if "reject" in levels else "human_review" if levels else "auto_pass"
        result[bucket].append({"sku": sku, "issues": found} if found else sku)
    result["summary"] = {k: len(v) for k, v in result.items()}
    return result


def read_only_query(sql, db_path=DB_PATH, limit=200):
    """SELECT만 허용하는 조회. 읽기 전용으로 열어서 쓰기 쿼리는 DB가 막는다."""
    if not sql.lstrip().lower().startswith(("select", "with")):
        raise ValueError("SELECT 조회만 허용합니다")
    con = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)
    try:
        cur = con.execute(sql)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchmany(limit)]
    finally:
        con.close()
