"""
ETL Loader — Reads transformed Parquet files and loads them into internal PostgreSQL.

Takes the output of the sandbox_runner.py (Parquet files) and:
  1. Reads each Parquet into a DataFrame
  2. Maps pandas dtypes → PostgreSQL column types
  3. Creates tables with safe, namespaced names
  4. Bulk-inserts data via psycopg2.extras.execute_values
  5. Registers loaded tables in the etl_tables metadata table
"""
from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from psycopg2.extras import execute_values

from app.core.schema_utils import get_tenant_schema_name, get_workspace_schema_name

logger = logging.getLogger("HybridSystem")


class ETLLoader:
    """
    Loads transformed Parquet files into internal PostgreSQL.

    Usage:
        from app.core.database import DatabaseManager
        db = DatabaseManager()
        loader = ETLLoader(db)
        loaded = loader.load_to_postgres(
            parquet_dir="/tmp/etl/output",
            user_id="user123",
            job_id="job-abc",
        )
    """

    def __init__(self, db):
        """
        Parameters
        ----------
        db : DatabaseManager
            The singleton database manager with get_connection() context manager.
        """
        self.db = db

    def get_max_value(self, table_name: str, column_name: str, schema_name: str = "public") -> Optional[Any]:
        """Fetch the max value from an existing table to use as a high-water mark."""
        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(f'SELECT MAX("{column_name}") FROM "{schema_name}"."{table_name}"')
                    result = cur.fetchone()
                    return result[0] if result else None
                except Exception as e:
                    logger.warning(f"Could not get MAX from {schema_name}.{table_name}: {e}")
                    conn.rollback()
                    return None

    def load_to_postgres(
        self,
        parquet_dir: str,
        user_id: str,
        job_id: str,
        replace: bool = True,
        target_table_name: Optional[str] = None,
        schema_name: str | None = None,
        workspace_id: str | None = None,
        primary_keys: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Load all Parquet files from parquet_dir into PostgreSQL tables.

        Parameters
        ----------
        parquet_dir : str
            Directory containing .parquet files output by sandbox_runner.
        user_id : str
            User ID — used for namespacing table names.
        job_id : str
            ETL job ID — used for metadata tracking.
        replace : bool
            If True, DROP existing table before creating. Default True.

        Returns
        -------
        list[dict]
            List of loaded table metadata:
            [{"table_name": str, "source_name": str, "row_count": int, "columns": list, "table_id": str}]
        """
        parquet_path = Path(parquet_dir)
        if not parquet_path.is_dir():
            raise FileNotFoundError(f"Parquet output directory not found: {parquet_dir}")

        parquet_files = sorted(parquet_path.glob("*.parquet"))
        if not parquet_files:
            raise FileNotFoundError(f"No .parquet files found in: {parquet_dir}")

        loaded_tables: List[Dict[str, Any]] = []
        # If workspace_id is provided, use workspace schema; else fallback to tenant schema
        if workspace_id and not schema_name:
            schema_name = get_workspace_schema_name(workspace_id)
        else:
            schema_name = schema_name or get_tenant_schema_name(user_id)

        for pq_file in parquet_files:
            source_name = pq_file.stem
            table_name = target_table_name or self._generate_table_name(user_id, source_name)

            logger.info("[ETLLoader] Loading '%s' → table '%s'... (Replace mode: %s)", source_name, table_name, replace)

            # 1. Read Parquet
            df = pd.read_parquet(pq_file, engine="pyarrow")

            if df.empty:
                logger.warning("[ETLLoader] Skipping empty table '%s'", source_name)
                continue

            # 2. Clean column names (same pattern as IngestionMixin._clean_dataframe)
            df = self._clean_column_names(df)

            # 3. Map dtypes
            sql_types = self._map_sql_types(df)

            # 4. Create table
            self._create_table(schema_name, table_name, df.columns.tolist(), sql_types, replace=replace, primary_keys=primary_keys)

            # 5. Bulk insert (UPSERT if primary_keys)
            row_count = self._bulk_insert(schema_name, table_name, df, primary_keys=primary_keys)

            # 6. Generate column stats (light profiling)
            column_stats = self._generate_column_stats(df)

            # 7. Register in etl_tables metadata (we combine schema and table here for compatibility)
            table_id = str(uuid.uuid4())
            full_table_name = f'"{schema_name}"."{table_name}"'
            
            self._register_etl_table(
                table_id=table_id,
                job_id=job_id,
                table_name=full_table_name,
                source_name=source_name,
                row_count=row_count,
                column_stats=column_stats,
            )

            # 8. Register table + column metadata in etl_system (Semantic Catalog)
            if workspace_id:
                self._register_table_metadata(
                    workspace_id=workspace_id,
                    schema_name=schema_name,
                    table_name=table_name,
                    row_count=row_count,
                    column_stats=column_stats,
                )
                self._register_columns_metadata(
                    workspace_id=workspace_id,
                    table_name=table_name,
                    df=df,
                    sql_types=sql_types,
                )

            loaded_tables.append({
                "table_id": table_id,
                "schema_name": schema_name,
                "table_name": table_name,
                "full_table_name": full_table_name,
                "source_name": source_name,
                "row_count": row_count,
                "columns": df.columns.tolist(),
                "workspace_id": workspace_id,
            })

            logger.info(
                "[ETLLoader] ✅ '%s' → '%s'.'%s' (%d rows, %d cols)",
                source_name, schema_name, table_name, row_count, len(df.columns),
            )

        return loaded_tables

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _generate_table_name(user_id: str, source_name: str) -> str:
        """Generate a safe PostgreSQL table name.

        PostgreSQL limits table names to 63 characters.
        """
        # Sanitize source name
        safe_source = re.sub(r"[^a-zA-Z0-9_]", "_", source_name).lower().strip("_")
        
        # Tables are isolated by PostgreSQL schemas, so no user-prefixes are needed
        return safe_source[:63]

    @staticmethod
    def _clean_column_names(df: pd.DataFrame) -> pd.DataFrame:
        """Sanitize column names for PostgreSQL compatibility."""
        new_columns = []
        for col in df.columns:
            clean = re.sub(r"[^\w\s]", "", str(col)).strip().replace(" ", "_").lower()
            if not clean:
                clean = f"col_{len(new_columns)}"
            new_columns.append(clean)
        df.columns = new_columns
        return df

    @staticmethod
    def _map_sql_types(df: pd.DataFrame) -> Dict[str, str]:
        """Map pandas dtypes to PostgreSQL column types."""
        sql_types: Dict[str, str] = {}
        for col in df.columns:
            dtype = df[col].dtype
            if pd.api.types.is_integer_dtype(dtype):
                sql_types[col] = "BIGINT"
            elif pd.api.types.is_float_dtype(dtype):
                sql_types[col] = "DOUBLE PRECISION"
            elif pd.api.types.is_bool_dtype(dtype):
                sql_types[col] = "BOOLEAN"
            elif pd.api.types.is_datetime64_any_dtype(dtype):
                sql_types[col] = "TIMESTAMP"
            else:
                sql_types[col] = "TEXT"
        return sql_types

    def _create_table(
        self,
        schema_name: str,
        table_name: str,
        columns: List[str],
        sql_types: Dict[str, str],
        replace: bool = True,
        primary_keys: Optional[List[str]] = None,
    ) -> None:
        """Create the PostgreSQL table."""
        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                # Ensure the schema exists
                cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}";')
                
                if replace:
                    cur.execute(f'DROP TABLE IF EXISTS "{schema_name}"."{table_name}" CASCADE;')

                col_defs = [f'"{col}" {sql_types[col]}' for col in columns]
                if primary_keys:
                    pk_str = ", ".join([f'"{pk}"' for pk in primary_keys])
                    col_defs.append(f'PRIMARY KEY ({pk_str})')
                    
                # If table already exists and we are not supposed to replace it, 
                # we don't want to re-create it, we just append.
                create_sql = f'CREATE TABLE IF NOT EXISTS "{schema_name}"."{table_name}" ({", ".join(col_defs)});'
                cur.execute(create_sql)
                
                # If we are appending but the table didn't have the primary key (e.g. legacy table),
                # we might need to add it. But for now we rely on user dropping/recreating the pipeline.
                
                self._grant_readonly_access(cur, schema_name, table_name)
            conn.commit()

    def _bulk_insert(self, schema_name: str, table_name: str, df: pd.DataFrame, primary_keys: Optional[List[str]] = None) -> int:
        """Bulk insert DataFrame rows into PostgreSQL table, with UPSERT support."""
        if df.empty:
            return 0

        columns = df.columns.tolist()
        cols_str = ", ".join(f'"{c}"' for c in columns)

        # Build row tuples — handle NaN/None
        rows: List[tuple] = []
        for _, row in df.iterrows():
            vals = []
            for v in row:
                try:
                    if pd.isna(v) or str(v).lower() == "nan":
                        vals.append(None)
                    else:
                        vals.append(v)
                except (TypeError, ValueError):
                    vals.append(None)
            rows.append(tuple(vals))

        # Insert in batches to avoid memory issues
        batch_size = 5000
        total_inserted = 0
        
        conflict_clause = ""
        if primary_keys:
            valid_pks = [pk for pk in primary_keys if pk in columns]
            if valid_pks:
                pk_str = ", ".join([f'"{pk}"' for pk in valid_pks])
                update_cols = [c for c in columns if c not in valid_pks]
                if update_cols:
                    set_clause = ", ".join([f'"{c}" = EXCLUDED."{c}"' for c in update_cols])
                    conflict_clause = f" ON CONFLICT ({pk_str}) DO UPDATE SET {set_clause}"
                else:
                    conflict_clause = f" ON CONFLICT ({pk_str}) DO NOTHING"

        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                for i in range(0, len(rows), batch_size):
                    batch = rows[i : i + batch_size]
                    execute_values(
                        cur,
                        f'INSERT INTO "{schema_name}"."{table_name}" ({cols_str}) VALUES %s{conflict_clause}',
                        batch,
                    )
                    total_inserted += len(batch)
            conn.commit()

        return total_inserted

    @staticmethod
    def _generate_column_stats(df: pd.DataFrame) -> Dict[str, Any]:
        """Generate lightweight column statistics for metadata."""
        stats: Dict[str, Any] = {
            "total_rows": len(df),
            "columns": {},
        }

        for col in df.columns:
            col_data = df[col]
            col_stats: Dict[str, Any] = {
                "type": str(col_data.dtype),
                "null_count": int(col_data.isna().sum()),
                "unique_count": int(col_data.nunique()),
            }

            if pd.api.types.is_numeric_dtype(col_data):
                col_stats["min"] = float(col_data.min()) if not pd.isna(col_data.min()) else None
                col_stats["max"] = float(col_data.max()) if not pd.isna(col_data.max()) else None
                col_stats["mean"] = float(col_data.mean()) if not pd.isna(col_data.mean()) else None

            stats["columns"][col] = col_stats

        return stats

    def _register_etl_table(
        self,
        table_id: str,
        job_id: str,
        table_name: str,
        source_name: str,
        row_count: int,
        column_stats: Dict[str, Any],
    ) -> None:
        """Register a loaded ETL table in the etl_tables metadata table."""
        import json

        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO etl_system.etl_tables (table_id, job_id, table_name, source_name, row_count, column_stats)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (table_id) DO UPDATE SET
                        table_name = EXCLUDED.table_name,
                        row_count = EXCLUDED.row_count,
                        column_stats = EXCLUDED.column_stats
                    """,
                    (table_id, job_id, table_name, source_name, row_count, json.dumps(column_stats, default=str)),
                )
            conn.commit()

    @staticmethod
    def _grant_readonly_access(cur, schema_name: str, table_name: str) -> None:
        readonly_user = __import__("os").getenv("ETL_READONLY_USER", "ai_readonly")
        try:
            cur.execute(f'GRANT USAGE ON SCHEMA "{schema_name}" TO "{readonly_user}";')
        except Exception:
            pass
        try:
            cur.execute(f'GRANT SELECT ON TABLE "{schema_name}"."{table_name}" TO "{readonly_user}";')
        except Exception:
            pass

    # ── Semantic Catalog Registration ─────────────────────────────────

    def _register_table_metadata(
        self,
        workspace_id: str,
        schema_name: str,
        table_name: str,
        row_count: int,
        column_stats: Dict[str, Any],
    ) -> None:
        """Register or update a table's metadata in etl_system.tables_metadata."""
        import json

        metadata_id = f"{workspace_id}_{table_name}"

        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO etl_system.tables_metadata
                        (metadata_id, workspace_id, table_name, schema_name, row_count, auto_profile, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (metadata_id) DO UPDATE SET
                        row_count = EXCLUDED.row_count,
                        auto_profile = EXCLUDED.auto_profile,
                        schema_name = EXCLUDED.schema_name,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        metadata_id,
                        workspace_id,
                        table_name,
                        schema_name,
                        row_count,
                        json.dumps(column_stats, default=str),
                    ),
                )
            conn.commit()

        logger.info(
            "[ETLLoader] 📋 Registered table metadata: %s.%s (workspace=%s)",
            schema_name, table_name, workspace_id,
        )

    def _register_columns_metadata(
        self,
        workspace_id: str,
        table_name: str,
        df: pd.DataFrame,
        sql_types: Dict[str, str],
    ) -> None:
        """Register column-level metadata in etl_system.columns_metadata."""
        import json

        metadata_id = f"{workspace_id}_{table_name}"

        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                # Clear old columns for this table to avoid stale data
                cur.execute(
                    "DELETE FROM etl_system.columns_metadata WHERE workspace_id = %s AND table_name = %s",
                    (workspace_id, table_name),
                )

                for col in df.columns:
                    column_id = f"{workspace_id}_{table_name}_{col}"

                    # Sample values (top 5 non-null unique)
                    try:
                        samples = df[col].dropna().unique()[:5].tolist()
                        sample_json = json.dumps([str(s) for s in samples], default=str)
                    except Exception:
                        sample_json = "[]"

                    # Column-level stats
                    col_stats: Dict[str, Any] = {
                        "null_count": int(df[col].isna().sum()),
                        "unique_count": int(df[col].nunique()),
                    }
                    if pd.api.types.is_numeric_dtype(df[col]):
                        col_stats["min"] = float(df[col].min()) if not pd.isna(df[col].min()) else None
                        col_stats["max"] = float(df[col].max()) if not pd.isna(df[col].max()) else None
                        col_stats["mean"] = float(df[col].mean()) if not pd.isna(df[col].mean()) else None

                    cur.execute(
                        """
                        INSERT INTO etl_system.columns_metadata
                            (column_id, metadata_id, workspace_id, table_name, column_name, data_type, sample_values, stats)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (column_id) DO UPDATE SET
                            data_type = EXCLUDED.data_type,
                            sample_values = EXCLUDED.sample_values,
                            stats = EXCLUDED.stats
                        """,
                        (
                            column_id,
                            metadata_id,
                            workspace_id,
                            table_name,
                            col,
                            sql_types.get(col, "TEXT"),
                            sample_json,
                            json.dumps(col_stats, default=str),
                        ),
                    )
            conn.commit()

        logger.info(
            "[ETLLoader] 📋 Registered %d column metadata entries for %s (workspace=%s)",
            len(df.columns), table_name, workspace_id,
        )
