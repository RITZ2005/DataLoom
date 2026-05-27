"""
Connector factory — instantiates the correct connector based on db_type.
"""
from __future__ import annotations

from app.core.etl.connectors.base_connector import BaseConnector, ConnectionConfig


def create_connector(config: ConnectionConfig) -> BaseConnector:
    """
    Factory function: return the appropriate connector for the given config.

    Supported db_type values: "mysql", "postgresql", "mongodb"
    """
    if config.db_type in ("mysql", "postgresql"):
        from app.core.etl.connectors.sql_connector import SQLConnector
        return SQLConnector(config)
    elif config.db_type == "mongodb":
        from app.core.etl.connectors.mongo_connector import MongoConnector
        return MongoConnector(config)
    else:
        raise ValueError(
            f"Unsupported database type: '{config.db_type}'. "
            f"Supported types: mysql, postgresql, mongodb"
        )
