"""Claude에서 상품 검수를 부를 수 있게 checker.py를 MCP 도구로 노출한다."""
import sqlite3
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

import checker

DATA_DIR = (Path(__file__).parent / "data").resolve()

mcp = MCPServer("product-check")


@mcp.tool()
def load_products(csv_name: str = "products.csv") -> dict:
    """data 폴더의 상품 CSV를 검수용 DB에 올린다."""
    path = (DATA_DIR / csv_name).resolve()
    if path.parent != DATA_DIR or path.suffix != ".csv":  # data 폴더 밖 파일은 읽지 않는다
        raise ToolError("data 폴더 안의 .csv 파일만 올릴 수 있습니다")
    return {"loaded": checker.load_csv(path)}


@mcp.tool()
def run_checks() -> dict:
    """검수 규칙을 모두 돌려 자동 통과 / 사람 확인 / 반려로 나눈다."""
    return checker.run_checks()


@mcp.tool()
def list_rules() -> list[dict]:
    """적용 중인 검수 규칙과 SQL을 보여준다."""
    return [{"rule": k, "level": lv, "sql": " ".join(sql.split())} for k, (lv, sql) in checker.RULES.items()]


@mcp.tool()
def query(sql: str) -> list[dict]:
    """products 테이블을 SELECT로 조회한다(읽기 전용, 최대 200행)."""
    try:
        return checker.read_only_query(sql)
    except (ValueError, sqlite3.Error) as e:  # 거절 사유를 Claude가 읽을 수 있게 돌려준다
        raise ToolError(str(e)) from e


if __name__ == "__main__":
    mcp.run()
