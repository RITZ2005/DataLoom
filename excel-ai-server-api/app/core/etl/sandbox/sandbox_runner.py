"""
Sandbox Runner — Isolated ETL Transform Execution.

This script runs as a SEPARATE Python process, outside of the FastAPI
event loop. It is spawned by executor.py via subprocess.run().

Input:  CLI args pointing to input Parquet directory + user script path.
Output: Transformed DataFrames written as Parquet files to output directory.

If the user script crashes (SyntaxError, logic error, etc.), this process
exits with a non-zero code and the stack trace is captured via stderr.

Usage:
    python sandbox_runner.py --input-dir /tmp/etl/input \
                             --output-dir /tmp/etl/output \
                             --script /tmp/etl/transform.py
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import traceback
from pathlib import Path

import pandas as pd


def _load_input_tables(input_dir: str) -> dict[str, pd.DataFrame]:
    """Load all .parquet files from input_dir into a name→DataFrame dict.

    File stems become the table keys:
        /tmp/etl/input/users.parquet  →  tables["users"]
        /tmp/etl/input/orders.parquet →  tables["orders"]
    """
    tables: dict[str, pd.DataFrame] = {}
    input_path = Path(input_dir)

    if not input_path.is_dir():
        raise FileNotFoundError(f"Input directory does not exist: {input_dir}")

    parquet_files = sorted(input_path.glob("*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(f"No .parquet files found in: {input_dir}")

    for pq_file in parquet_files:
        table_name = pq_file.stem  # filename without extension
        df = pd.read_parquet(pq_file, engine="pyarrow")
        tables[table_name] = df
        print(f"[sandbox] Loaded table '{table_name}': {len(df)} rows, {len(df.columns)} cols", flush=True)

    return tables


def _load_user_script(script_path: str):
    """Dynamically import the user's transform script.

    The script MUST define a callable:
        def transform(tables: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """
    script_file = Path(script_path)

    if not script_file.is_file():
        raise FileNotFoundError(f"Transform script not found: {script_path}")

    if not script_file.suffix == ".py":
        raise ValueError(f"Transform script must be a .py file, got: {script_file.suffix}")

    spec = importlib.util.spec_from_file_location("user_transform", str(script_file))
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module spec from: {script_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, "transform"):
        raise AttributeError(
            f"User script '{script_file.name}' must define a 'transform' function. "
            f"Expected signature: def transform(tables: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]"
        )

    if not callable(module.transform):
        raise TypeError(
            f"'transform' in '{script_file.name}' is not callable (type: {type(module.transform).__name__})"
        )

    return module


def _validate_output(result: object) -> dict[str, pd.DataFrame]:
    """Validate that the transform() return value is a dict of DataFrames."""
    if not isinstance(result, dict):
        raise TypeError(
            f"transform() must return dict[str, pd.DataFrame], got {type(result).__name__}. "
            f"Example: return {{'users': cleaned_users_df, 'orders': cleaned_orders_df}}"
        )

    for key, value in result.items():
        if not isinstance(key, str):
            raise TypeError(
                f"All keys in the returned dict must be strings, got key of type {type(key).__name__}"
            )
        if not isinstance(value, pd.DataFrame):
            raise TypeError(
                f"Value for key '{key}' must be a pandas DataFrame, got {type(value).__name__}"
            )

    return result


def _write_output_tables(tables: dict[str, pd.DataFrame], output_dir: str) -> list[str]:
    """Write each output DataFrame to a .parquet file in output_dir."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    written_files: list[str] = []

    for table_name, df in tables.items():
        # Sanitize table name for filesystem safety
        safe_name = "".join(c if c.isalnum() or c == "_" else "_" for c in table_name)
        out_file = output_path / f"{safe_name}.parquet"
        
        # Prevent PyArrow crashes by sanitizing "object" columns with mixed types 
        # (e.g. from user doing a blanket .fillna(0) on Timestamps)
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', category=FutureWarning)
            # Catch Pandas4Warning which inherits from FutureWarning or similar
            warnings.filterwarnings('ignore', category=UserWarning)
            try:
                from pandas.errors import Pandas4Warning # type: ignore
                warnings.simplefilter('ignore', category=Pandas4Warning)
            except ImportError:
                pass
            object_cols = df.select_dtypes(include=["object"]).columns

        for col in object_cols:
            # Check the underlying data type composition using pandas fast inference
            inferred = pd.api.types.infer_dtype(df[col], skipna=True)
            if inferred in ("mixed", "mixed-integer"):
                print(f"[sandbox] Auto-fixing mixed types in column '{col}' -> cast to str")
                df[col] = df[col].astype(str)

        try:
            df.to_parquet(out_file, index=False, engine="pyarrow")
        except Exception as e:
            # Provide a beautiful trace rather than an ugly raw engine error
            raise ValueError(
                f"Failed to save table '{table_name}' to Parquet due to a schema or type error.\n"
                f"Original PyArrow Error: {e}"
            ) from e
            
        written_files.append(str(out_file))
        print(
            f"[sandbox] Wrote table '{table_name}': {len(df)} rows, {len(df.columns)} cols -> {out_file}",
            flush=True,
        )

    return written_files


def main() -> int:
    """Entry point for the sandbox runner subprocess."""
    parser = argparse.ArgumentParser(
        description="ETL Sandbox Runner — executes user transform scripts in isolation."
    )
    parser.add_argument(
        "--input-dir",
        required=True,
        help="Directory containing input .parquet files (one per table).",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory where transformed .parquet files will be written.",
    )
    parser.add_argument(
        "--script",
        required=True,
        help="Path to the user's .py transform script.",
    )

    args = parser.parse_args()

    print(f"[sandbox] Starting transform...", flush=True)
    print(f"[sandbox]   Input dir:  {args.input_dir}", flush=True)
    print(f"[sandbox]   Output dir: {args.output_dir}", flush=True)
    print(f"[sandbox]   Script:     {args.script}", flush=True)

    # 1. Load input parquet files
    tables = _load_input_tables(args.input_dir)
    print(f"[sandbox] Loaded {len(tables)} table(s): {list(tables.keys())}", flush=True)

    # 2. Load and validate user script
    user_module = _load_user_script(args.script)
    print(f"[sandbox] User script loaded successfully", flush=True)

    # 3. Execute transform(tables)
    print(f"[sandbox] Executing transform()...", flush=True)
    result = user_module.transform(tables)

    # 4. Validate output
    validated_result = _validate_output(result)
    print(f"[sandbox] Transform returned {len(validated_result)} table(s): {list(validated_result.keys())}", flush=True)

    # 5. Write output parquet files
    written = _write_output_tables(validated_result, args.output_dir)
    print(f"[sandbox] Transform complete! Wrote {len(written)} file(s)", flush=True)

    return 0


if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except Exception as exc:
        # Print full traceback to stderr — executor.py captures this
        print(f"\n[sandbox] Transform FAILED:", file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
