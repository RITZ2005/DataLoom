"""
ETL Executor — Main app wrapper for sandbox subprocess execution.

Spawns sandbox_runner.py as a separate Python process with strict timeout.
Handles:
  - Full transform execution
  - Dry-run mode (limited rows for preview)
  - Timeout enforcement (kills infinite loops)
  - Capturing stdout/stderr from the subprocess
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import pandas as pd

logger = logging.getLogger("HybridSystem")

# Absolute path to sandbox_runner.py — resolved relative to this file
_SANDBOX_RUNNER = str(Path(__file__).parent / "sandbox_runner.py")


@dataclass
class ExecutionResult:
    """Result of a sandbox transform execution."""
    success: bool
    stdout: str = ""
    stderr: str = ""
    output_files: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    timed_out: bool = False


class ETLExecutor:
    """
    Wraps subprocess execution of user transform scripts.

    Security:
      - User code NEVER runs in the main FastAPI process
      - Strict timeout prevents infinite loops
      - All IPC is via Parquet files on disk

    Usage:
        executor = ETLExecutor(timeout=120)
        result = executor.run_transform(
            input_dir="/tmp/etl/abc123/input",
            output_dir="/tmp/etl/abc123/output",
            script_path="/tmp/etl/abc123/transform.py",
        )
        if result.success:
            print(result.output_files)
        else:
            print(result.stderr)
    """

    def __init__(self, timeout: Optional[int] = None):
        self.timeout = timeout or int(os.getenv("ETL_SANDBOX_TIMEOUT", "120"))

    def run_transform(
        self,
        input_dir: str,
        output_dir: str,
        script_path: str,
        row_limit: Optional[int] = None,
    ) -> ExecutionResult:
        """
        Execute a user transform script in an isolated subprocess.

        Parameters
        ----------
        input_dir : str
            Directory containing input .parquet files.
        output_dir : str
            Directory where output .parquet files will be written.
        script_path : str
            Path to the user's .py transform script.
        row_limit : int, optional
            If set, only process the first N rows per table (dry-run mode).
            Creates temporary trimmed parquets for the subprocess.

        Returns
        -------
        ExecutionResult
            Contains success status, stdout/stderr, output file paths, etc.
        """
        start_time = time.time()
        actual_input_dir = input_dir

        # ── Dry-run: trim input parquets to row_limit ────────────────────
        temp_dir = None
        if row_limit is not None and row_limit > 0:
            try:
                temp_dir = tempfile.mkdtemp(prefix="etl_dryrun_")
                actual_input_dir = temp_dir
                self._create_trimmed_parquets(input_dir, temp_dir, row_limit)
            except Exception as exc:
                return ExecutionResult(
                    success=False,
                    stderr=f"Failed to create dry-run input: {exc}",
                    duration_seconds=time.time() - start_time,
                )

        # ── Ensure output directory exists ───────────────────────────────
        os.makedirs(output_dir, exist_ok=True)

        # ── Build subprocess command ─────────────────────────────────────
        cmd = [
            sys.executable,  # Same Python interpreter as the main app
            "-u",            # Unbuffered output
            _SANDBOX_RUNNER,
            "--input-dir", actual_input_dir,
            "--output-dir", output_dir,
            "--script", script_path,
        ]

        logger.info(
            "[ETLExecutor] Spawning sandbox: timeout=%ds, dry_run=%s, cmd=%s",
            self.timeout,
            row_limit is not None,
            " ".join(cmd),
        )

        # ── Execute subprocess ───────────────────────────────────────────
        try:
            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=str(Path(__file__).parents[4]),  # project root (excel-ai-server-api/)
            )

            duration = time.time() - start_time

            if process.returncode == 0:
                # Collect output files
                output_files = [
                    str(f) for f in Path(output_dir).glob("*.parquet")
                ]
                logger.info(
                    "[ETLExecutor] ✅ Transform succeeded in %.1fs — %d output files",
                    duration,
                    len(output_files),
                )
                return ExecutionResult(
                    success=True,
                    stdout=process.stdout,
                    stderr=process.stderr,
                    output_files=output_files,
                    duration_seconds=duration,
                )
            else:
                logger.error(
                    "[ETLExecutor] ❌ Transform failed (exit code %d) in %.1fs",
                    process.returncode,
                    duration,
                )
                return ExecutionResult(
                    success=False,
                    stdout=process.stdout,
                    stderr=process.stderr,
                    duration_seconds=duration,
                )

        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            logger.error(
                "[ETLExecutor] ⏰ Transform TIMED OUT after %ds", self.timeout
            )
            return ExecutionResult(
                success=False,
                stderr=(
                    f"Transform script timed out after {self.timeout} seconds. "
                    f"This usually means the script contains an infinite loop "
                    f"or is processing too much data. Try simplifying your "
                    f"transform logic or reducing the dataset size."
                ),
                duration_seconds=duration,
                timed_out=True,
            )

        except Exception as exc:
            duration = time.time() - start_time
            logger.error(
                "[ETLExecutor] ❌ Subprocess error: %s", exc
            )
            return ExecutionResult(
                success=False,
                stderr=f"Internal error spawning transform subprocess: {exc}",
                duration_seconds=duration,
            )

        finally:
            # Clean up dry-run temp directory
            if temp_dir is not None:
                try:
                    import shutil
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except Exception:
                    pass

    @staticmethod
    def _create_trimmed_parquets(
        source_dir: str, dest_dir: str, row_limit: int
    ) -> None:
        """Create trimmed copies of input parquets with only the first N rows."""
        source_path = Path(source_dir)
        dest_path = Path(dest_dir)
        dest_path.mkdir(parents=True, exist_ok=True)

        for pq_file in source_path.glob("*.parquet"):
            df = pd.read_parquet(pq_file, engine="pyarrow")
            trimmed = df.head(row_limit)
            trimmed.to_parquet(dest_path / pq_file.name, index=False, engine="pyarrow")
            logger.info(
                "[ETLExecutor] Trimmed %s: %d → %d rows (dry-run)",
                pq_file.name, len(df), len(trimmed),
            )
