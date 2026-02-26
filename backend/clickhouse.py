import clickhouse_connect

from shared.config import settings
from shared.logging import get_logger

logger = get_logger(__name__)


def get_client():
    return clickhouse_connect.get_client(
        host=settings.CLICKHOUSE_HOST,
        port=settings.CLICKHOUSE_PORT,
        database=settings.CLICKHOUSE_DB,
    )


def execute_query(query: str, params: dict | None = None) -> list[dict]:
    """
    Executes a ClickHouse query and returns results as a list of dicts.
    """
    client = get_client()
    try:
        result = client.query(query, parameters=params or {})
        columns = result.column_names
        return [dict(zip(columns, row)) for row in result.result_rows]
    except Exception as e:
        logger.error("clickhouse query failed", error=str(e), query=query)
        raise
    finally:
        client.close()
