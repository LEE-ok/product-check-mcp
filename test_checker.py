import sqlite3
from pathlib import Path

import pytest

import checker

CSV = Path(__file__).parent / "data" / "products.csv"


@pytest.fixture
def db(tmp_path):
    db = tmp_path / "t.db"
    checker.load_csv(CSV, db)
    return db


def test_sample_data_buckets(db):
    r = checker.run_checks(db)
    rejected = {x["sku"] for x in r["reject"]}
    review = {x["sku"] for x in r["human_review"]}
    assert rejected == {"P005", "P007", "P009", "P010", "P016", "P019"}
    assert review == {"P004", "P014", "P020"}
    assert r["summary"] == {"auto_pass": 11, "human_review": 3, "reject": 6}


def test_reasons_are_specific(db):
    r = checker.run_checks(db)
    p019 = next(x for x in r["reject"] if x["sku"] == "P019")
    assert p019["issues"][0]["reason"] == "필수 항목 누락: 상품명"


def test_query_is_read_only(db):
    assert checker.read_only_query("SELECT count(*) AS n FROM products", db) == [{"n": 20}]
    with pytest.raises(ValueError):
        checker.read_only_query("DELETE FROM products", db)
    with pytest.raises(sqlite3.OperationalError):  # SELECT로 시작해도 쓰기는 DB가 막는다
        checker.read_only_query("WITH x AS (SELECT 1) INSERT INTO products(sku) SELECT 'X' FROM x", db)
