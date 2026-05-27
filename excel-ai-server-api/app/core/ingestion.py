"""
Ingestion & data loading mixin for HybridAgent.

Extracted from agent.py — handles file parsing, metadata profiling,
date cleaning, DataFrame cleaning, and database ingestion/fetching.
"""
from __future__ import annotations

import os
import re
import json
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from typing import List

import pandas as pd
from psycopg2.extras import execute_values, RealDictCursor

from app.utils.logging import logger, log_full_exception


class IngestionMixin:
    """Mixin providing data ingestion, profiling, and DB fetch methods."""

    def _generate_metadata_profile(self, df):
        logger.info("📊 Generating Rich Metadata Profile...")
        profile = {
            "total_rows": len(df),
            "columns": {}
        }
        
        for col in df.columns:
            col_data = df[col]
            dtype = str(col_data.dtype)
            
            col_profile = {
                "type": dtype,
                "null_count": int(col_data.isna().sum()),
                "unique_count": int(col_data.nunique())
            }
            
            if pd.api.types.is_numeric_dtype(col_data):
                col_profile["min"] = float(col_data.min()) if not pd.isna(col_data.min()) else None
                col_profile["max"] = float(col_data.max()) if not pd.isna(col_data.max()) else None
                col_profile["mean"] = float(col_data.mean()) if not pd.isna(col_data.mean()) else None
                # NEW: Add Median and Standard Deviation for better salary/age insights
                col_profile["median"] = float(col_data.median()) if not pd.isna(col_data.median()) else None
                col_profile["std_dev"] = float(col_data.std()) if not pd.isna(col_data.std()) else None
            
            # NEW: Extract the top/majority value for categorical columns
            if dtype == 'object' or str(dtype) == 'category':
                try:
                    if not col_data.dropna().empty:
                        top_val = col_data.mode()[0]
                        top_freq = int(col_data.value_counts().iloc[0])
                        col_profile["most_frequent"] = f"{top_val} ({top_freq} rows)"
                except Exception:
                    pass

            try:
                top_vals = col_data.value_counts().head(10).index.tolist()
                col_profile["samples"] = [str(x) for x in top_vals]
            except:
                col_profile["samples"] = []

            profile["columns"][col] = col_profile
            
        return profile

    def _smart_parse_dates(self, series):
        """
        An absolute bulletproof date parser that explicitly overrides Pandas' strict ISO parsing 
        to fix the Excel Mixed Date Bug (YYYY-DD-MM) while safely handling standard formats.
        """
        import pandas as pd
        import re
        
        def force_parse(d):
            if pd.isna(d): return pd.NaT
            d_str = str(d).strip()
            
            # 1. Check for Excel's corrupted ISO: YYYY-XX-XX
            m1 = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})', d_str)
            if m1:
                y, p1, p2 = m1.groups()
                # If the last number is > 12, it must be the day. (True ISO: YYYY-MM-DD)
                if int(p2) > 12:
                    return pd.to_datetime(f"{y}-{p1}-{p2}", format='%Y-%m-%d', errors='coerce')
                # Otherwise, it's the Excel bug (YYYY-DD-MM). We forcefully make p2 the month!
                else:
                    return pd.to_datetime(f"{y}-{p2}-{p1}", format='%Y-%m-%d', errors='coerce')
            
            # 2. Check for Slashed/Dashed Dates: XX/XX/YYYY
            m2 = re.match(r'^(\d{1,2})[-/](\d{1,2})[-/](\d{4})', d_str)
            if m2:
                p1, p2, y = m2.groups()
                # If the first number is > 12, it's DD/MM/YYYY (UK/India)
                if int(p1) > 12:
                    return pd.to_datetime(f"{y}-{p2}-{p1}", format='%Y-%m-%d', errors='coerce')
                # If the middle number is > 12, it's MM/DD/YYYY (US)
                elif int(p2) > 12:
                    return pd.to_datetime(f"{y}-{p1}-{p2}", format='%Y-%m-%d', errors='coerce')
                # If ambiguous (e.g. 02/03/2026), default to DD/MM/YYYY for India/UK
                else:
                    return pd.to_datetime(f"{y}-{p2}-{p1}", format='%Y-%m-%d', errors='coerce')
            
            # 3. Fallback for completely standard dates
            return pd.to_datetime(d_str, dayfirst=True, errors='coerce')

        return series.apply(force_parse)


    def _clean_dataframe(self, df):
        new_columns = []
        for col in df.columns:
            clean_col = re.sub(r'[^\w\s]', '', str(col)).strip().replace(' ', '_').lower()
            if not clean_col: clean_col = f"col_{len(new_columns)}"
            new_columns.append(clean_col)
        df.columns = new_columns

        sql_types = {}
        for col in df.columns:
            if pd.api.types.is_numeric_dtype(df[col]) or pd.api.types.is_datetime64_any_dtype(df[col]):
                pass
            
            elif df[col].dtype == 'object':
                try:
                    cleaned = df[col].astype(str).str.replace(r'[$,%€]', '', regex=True).str.strip()
                    numeric = pd.to_numeric(cleaned, errors='coerce')
                    if numeric.notna().sum() > (len(df) * 0.6) and numeric.notna().sum() > 0:
                        df[col] = numeric
                except: pass

            if df[col].dtype == 'object':
                try:
                    original_col = df[col].copy()
                    original_non_nulls = original_col.notna().sum()
                    converted = self._smart_parse_dates(original_col)
                    new_non_nulls = converted.notna().sum()
                    
                    if original_non_nulls > 0:
                        if (new_non_nulls / original_non_nulls) < 0.8:
                            df[col] = original_col
                        else:
                            df[col] = converted
                    else:
                         df[col] = converted
                except: pass

            if pd.api.types.is_integer_dtype(df[col]): sql_types[col] = "BIGINT"
            elif pd.api.types.is_float_dtype(df[col]): sql_types[col] = "DOUBLE PRECISION"
            elif pd.api.types.is_datetime64_any_dtype(df[col]): sql_types[col] = "TIMESTAMP"
            else: 
                df[col] = df[col].astype(str).replace('nan', None)
                sql_types[col] = "TEXT"
            
        return df, sql_types

    def _ingest_file(self, progress_callback=None):
        
        logger.info(f"🚀 Starting Hybrid Ingestion: {self.filename}")
        
        # Report: Reading file
        if progress_callback:
            progress_callback("reading", 12, 100, "Reading file...")
        
        ext = os.path.splitext(self.file_path)[1].lower()
        if ext == '.csv':
            df = pd.read_csv(self.file_path)
        else:
            # Support multi-sheet: read specific sheet if provided
            read_kwargs = {}
            if self.sheet_name:
                read_kwargs['sheet_name'] = self.sheet_name
            df = pd.read_excel(self.file_path, **read_kwargs)
        
        df, sql_types = self._clean_dataframe(df)
        self.columns = df.columns.tolist()

        # 1. Rich Metadata
        if progress_callback:
            progress_callback("reading", 18, 100, "File read successfully, cleaning data...")
        
        if progress_callback:
            progress_callback("metadata", 20, 100, "Generating metadata profile...")
        
        self.column_stats = self._generate_metadata_profile(df)
        stats_json = json.dumps(self.column_stats, default=str)

        # 2. Build row texts (fast list comprehension — no iterrows overhead)
        logger.info("🧠 Preparing row texts for embedding...")
        if progress_callback:
            progress_callback("metadata", 25, 100, "Metadata ready, preparing embeddings...")

        if progress_callback:
            progress_callback("embedding", 28, 100, "Preparing embeddings...")

        texts: List[str] = [
            (", ".join(
                f"{c}:{v}" for c, v in row.items()
                if pd.notna(v) and str(v).strip() != "" and str(v).lower() != "nan"
            ) or "empty_row")
            for _, row in df.iterrows()
        ]

        total_rows    = len(texts)
        batch_size    = 100
        MAX_WORKERS   = 4   # concurrent embedding API calls
        batches: List[List[str]] = [texts[i:i+batch_size] for i in range(0, total_rows, batch_size)]
        total_batches = len(batches)
        cols_str      = ', '.join([f'"{c}"' for c in self.columns] + ['row_embedding'])

        logger.info(f"📊 {total_rows} rows | {total_batches} batches | {MAX_WORKERS} concurrent workers")

        # 3. Create table BEFORE embedding so we can stream-insert each batch immediately
        logger.info("💾 Creating table...")
        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                col_defs = [f'"{col}" {sql_types[col]}' for col in self.columns]
                dim = self._get_embedding_dim()
                col_defs.append(f"row_embedding vector({dim})")
                cur.execute(f"CREATE TABLE {self.table_name} ({', '.join(col_defs)});")
            conn.commit()

        # 4. Concurrent embedding + streaming insert
        # ThreadPoolExecutor.map() submits ALL batches to the pool at once (MAX_WORKERS run
        # in parallel). Results are yielded in submission order, so row alignment is
        # guaranteed and we can insert each batch the moment it arrives.
        logger.info(f"⚡ Starting concurrent embedding (workers={MAX_WORKERS})...")
        embed_start   = time.time()
        total_inserted = 0

        def _embed_batch(args: tuple) -> tuple:
            """Embed one batch; returns (batch_idx, vectors_or_nones)."""
            batch_idx, batch = args
            try:
                result = self.embed_model.embed_documents(batch)
                logger.info(f"✅ Batch {batch_idx+1}/{total_batches} embedded ({len(batch)} rows)")
                return batch_idx, result
            except Exception as exc:
                log_full_exception(exc, f"Embedding batch {batch_idx+1}/{total_batches} failed")
                return batch_idx, [None] * len(batch)

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            for batch_idx, batch_vectors in pool.map(_embed_batch, enumerate(batches)):
                batch      = batches[batch_idx]
                row_start  = batch_idx * batch_size
                df_batch   = df.iloc[row_start: row_start + len(batch)]

                # Build typed row tuples for this batch
                db_rows: List[tuple] = []
                for i, row in enumerate(df_batch.itertuples(index=False)):
                    val_list = []
                    for v in row:
                        try:
                            val_list.append(None if (pd.isna(v) or str(v).lower() == 'nan') else v)
                        except Exception:
                            val_list.append(v)
                    val_list.append(batch_vectors[i])
                    db_rows.append(tuple(val_list))

                # Stream-insert this batch immediately — no full-file accumulation
                with self.db.get_connection() as conn:
                    with conn.cursor() as cur:
                        execute_values(cur, f'INSERT INTO {self.table_name} ({cols_str}) VALUES %s', db_rows)
                    conn.commit()

                total_inserted += len(db_rows)
                elapsed = time.time() - embed_start
                rate    = total_inserted / elapsed if elapsed > 0 else 0
                batch_progress = int(30 + ((batch_idx + 1) / total_batches) * 60)
                if progress_callback:
                    progress_callback("embedding", batch_progress, 100,
                                      f"Embedded & saved {total_inserted}/{total_rows} rows ({rate:.0f} rows/s)...")
                logger.info(f"📥 Batch {batch_idx+1}/{total_batches} inserted — "
                            f"{total_inserted}/{total_rows} rows @ {rate:.0f} rows/s")

        elapsed_total = time.time() - embed_start
        logger.info(f"🎉 Concurrent embedding done! {total_inserted}/{total_rows} rows "
                    f"in {elapsed_total:.1f}s ({total_inserted/elapsed_total:.0f} rows/s)")

        # 5. Register file + commit (HNSW index intentionally excluded —
        #    build it manually after upload with CREATE INDEX ... USING hnsw)
        logger.info("💾 Registering file in registry...")
        if progress_callback:
            progress_callback("saving", 92, 100, "Saving to database...")

        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO file_registry (file_uuid, filename, table_name, column_stats, created_by, project_id, subproject_id, file_group_id, sheet_name) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (self.file_uuid, self.filename, self.table_name, stats_json, self.user_id, self.project_id, self.subproject_id, self.file_group_id, self.sheet_name)
                )
            conn.commit()
        
        # Complete!
        if progress_callback:
            progress_callback("complete", 100, 100, "Upload complete!")
        
        logger.info("✅ Hybrid Ingestion Complete!")
        return df

    def _load_existing_metadata(self, filename: str = None, file_uuid: str = None):
        """Load metadata by either filename or file_uuid (UUID takes priority)"""
        with self.db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if file_uuid:
                    cur.execute(
                        "SELECT connection_id, name, created_by FROM etl_system.etl_connections WHERE connection_id = %s",
                        (file_uuid,),
                    )
                    connection_row = cur.fetchone()
                    if connection_row:
                        self.file_uuid = connection_row['connection_id']
                        self.filename = connection_row['name']
                        self.table_name = "__DATABASE_CONNECTION__"
                        self.column_stats = {}
                        self.columns = []
                        self.sql_table_names = self._get_sql_table_names_for_connection(file_uuid)
                        self._sql_connection_mode = True
                        self.df = None
                        return

                # Try UUID first, then fallback to filename
                for field, value in [("file_uuid", file_uuid), ("filename", filename)]:
                    if not value:
                        continue
                    cur.execute(f"SELECT file_uuid, filename, table_name, column_stats FROM file_registry WHERE {field} = %s", (value,))
                    res = cur.fetchone()
                    if res:
                        self.file_uuid = res['file_uuid']
                        self.filename = res['filename']
                        self.table_name = res['table_name']
                        self.column_stats = res['column_stats'] if res['column_stats'] else {}
                        self._sql_connection_mode = False
                        self.sql_table_names = None
                        if 'columns' in self.column_stats and isinstance(self.column_stats['columns'], dict):
                            self.columns = list(self.column_stats['columns'].keys())
                        else:
                            self.columns = self._get_columns_from_db_schema()
                        return
                    
                    if field == "file_uuid":
                        # Try ETL table fallback
                        cur.execute("SELECT table_id as file_uuid, table_name as filename, table_name, column_stats FROM etl_system.etl_tables WHERE table_id = %s", (value,))
                        res = cur.fetchone()
                        if res:
                            self.file_uuid = res['file_uuid']
                            self.filename = res['filename']
                            self.table_name = res['table_name']
                            self.column_stats = res['column_stats'] if res['column_stats'] else {}
                            self._sql_connection_mode = True
                            if getattr(self, "mode", None) == "table":
                                self._sql_connection_mode = False
                            self.sql_table_names = [self.table_name] if self.table_name else []
                            
                            if 'columns' in self.column_stats and isinstance(self.column_stats['columns'], dict):
                                self.columns = list(self.column_stats['columns'].keys())
                            else:
                                self.columns = self._get_columns_from_db_schema()

                            if getattr(self, "mode", None) == "table":
                                self.df = self._fetch_df_from_db()
                            else:
                                self.df = None
                            return
                        
                        # Try board_files fallback
                        cur.execute("SELECT file_uuid, filename, table_name, column_stats FROM board_files WHERE file_uuid = %s", (value,))
                        res = cur.fetchone()
                        if res:
                            self.file_uuid = res['file_uuid']
                            self.filename = res['filename']
                            self.table_name = res['table_name']
                            self.column_stats = res['column_stats'] if res['column_stats'] else {}
                            self._sql_connection_mode = False
                            self.sql_table_names = None
                            if 'columns' in self.column_stats and isinstance(self.column_stats['columns'], dict):
                                self.columns = list(self.column_stats['columns'].keys())
                            else:
                                self.columns = self._get_columns_from_db_schema()
                            return
        
        raise ValueError(f"File not found with UUID {file_uuid} or filename {filename}")

    def _get_sql_table_names_for_connection(self, connection_id: str):
        """Return ETL destination table names available for a saved connection."""
        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT t.table_name
                    FROM etl_system.etl_connections c
                    JOIN etl_system.etl_jobs j ON j.connection_id = c.connection_id
                    JOIN etl_system.etl_tables t ON t.job_id = j.job_id
                    WHERE c.connection_id = %s
                    ORDER BY t.table_name ASC
                    """,
                    (connection_id,),
                )
                return [row[0] for row in cur.fetchall()]

    def _fetch_df_from_db(self):
        with self.db.get_connection() as conn:
            if not self.columns:
                 self.columns = self._get_columns_from_db_schema()
                 
            cols = [c for c in self.columns if c != 'row_embedding']
            cols_join = ", ".join(f'"{c}"' for c in cols)
            query = f"SELECT {cols_join} FROM {self.table_name}"
            if getattr(self, "mode", None) == "table":
                query += " LIMIT 10000"
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                try:
                    return pd.read_sql(query, conn)
                except Exception as e:
                    msg = str(e)
                    lowered = msg.lower()
                    if "relation" in lowered and "does not exist" in lowered:
                        raise ValueError(
                            f"Data table '{self.table_name}' was not found. "
                            "This file metadata exists, but the underlying table is missing. "
                            "Please re-upload the file or choose another source."
                        ) from e
                    raise

    def _get_columns_from_db_schema(self):
        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                table_name = self.table_name
                schema_name = "public"
                if "." in table_name:
                    parts = table_name.split(".")
                    schema_name = parts[0].strip('"').strip("'")
                    table_name = parts[1].strip('"').strip("'")
                
                cur.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s",
                    (schema_name, table_name)
                )
                return [r[0] for r in cur.fetchall()]
