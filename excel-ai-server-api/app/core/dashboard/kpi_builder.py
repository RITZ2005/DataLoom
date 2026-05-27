"""
Dashboard mixin for HybridAgent.

Extracted from agent.py — contains ALL dashboard generation, KPI building,
chart generation, comparison logic, insights, and persistence methods.
"""
from __future__ import annotations

import os
import re
import json
import logging
import uuid
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import numpy as np
import pandas as pd

from app.utils.logging import logger, log_full_exception
from app.core.llm import invoke_llm_with_retry
from app.config import observe, langfuse_context, _LANGFUSE_CALLBACK_AVAILABLE

if TYPE_CHECKING:
    from app.core.agent import HybridAgent


class DashboardMixin:
    """Mixin providing all dashboard generation, KPI, chart, comparison, and insights methods."""

    def _parse_user_requirements(self, text: str) -> dict:
        """
        Parse free-text user requirements into column override hints.
        NO LLM — pure regex/string matching + intent keyword detection.

        Supported patterns (examples):
          • “consider Mobile as dimension”  → force_dimension
          • “use Salary as key metric”       → force_measure
          • “ignore Aadhaar”                → force_exclude
          • “focus on Revenue”             → focus_on  (boost priority)

        Returns dict with keys:
          force_measure, force_dimension, force_exclude, focus_on, raw
        """
        result: dict = {"force_measure": [], "force_dimension": [], "force_exclude": [], "focus_on": [], "raw": ""}
        if not text or not text.strip():
            return result
        result["raw"] = text.strip()

        if self.df is None:
            return result

        all_columns = list(self.df.columns)
        text_lower = text.lower()

        # Intent keyword groups — checked in matched clause
        measure_patterns  = [r'\bconsider\b', r'\binclude\b', r'\buse\b', r'\badd\b',
                             r'\bas (a )?kpi\b', r'\bas (a )?metric\b', r'\bas (a )?measure\b',
                             r'\bkey (metric|column|kpi)\b', r'\bimportant\b', r'\bshow\b']
        dim_patterns      = [r'\bdimension\b', r'\bcategory\b', r'\bgroup\s+by\b',
                             r'\bsegment\b', r'\bbreakdown\b', r'\bslice\b', r'\bfilter\b']
        exclude_patterns  = [r'\bignore\b', r'\bexclude\b', r'\bskip\b', r'\bremove\b',
                             r"\bdon'?t\s+include\b", r'\bdo\s+not\s+include\b', r'\bhide\b', r'\bnot\s+include\b']
        focus_patterns    = [r'\bfocus\b', r'\bhighlight\b', r'\bprimary\b',
                             r'\bmain\b', r'\bpriority\b', r'\bkey\b']

        # Split text into clauses for localised intent detection
        clauses = re.split(r'[,;.\n]', text_lower)

        for col_orig in all_columns:
            col_l    = col_orig.lower()
            # Words in the column name that are long enough to uniquely identify it
            col_words = [w for w in re.split(r'[\s_\-]', col_l) if len(w) >= 3]

            # Find clauses that mention this column (full name OR any distinguishing word)
            relevant = [
                c for c in clauses
                if col_l in c or any(w in c for w in col_words)
            ]
            if not relevant:
                continue

            classified = False
            for clause in relevant:
                if any(re.search(p, clause) for p in exclude_patterns):
                    result["force_exclude"].append(col_orig)
                    classified = True
                    break
                if any(re.search(p, clause) for p in dim_patterns):
                    result["force_dimension"].append(col_orig)
                    classified = True
                    break
                if any(re.search(p, clause) for p in measure_patterns):
                    result["force_measure"].append(col_orig)
                    classified = True
                    break
            if not classified:
                # Column mentioned but no specific intent — treat as focus/priority boost
                if any(re.search(p, clause) for clause in relevant for p in focus_patterns):
                    result["focus_on"].append(col_orig)
                else:
                    result["focus_on"].append(col_orig)  # Mentioned = user cares about it

        # Deduplicate
        for k in ("force_measure", "force_dimension", "force_exclude", "focus_on"):
            result[k] = list(dict.fromkeys(result[k]))

        logger.info(f"[ParseRequirements] force_measure={result['force_measure']}, "
                    f"force_dimension={result['force_dimension']}, "
                    f"force_exclude={result['force_exclude']}, focus_on={result['focus_on']}")
        return result

    def _build_file_fingerprint(self, user_hints: dict | None = None) -> dict:
        """
        Build a semantic 'File Fingerprint' before generating any dashboard.
        Classifies every column as a Measure, Dimension, or Time column,
        assigns priority scores, and detects time-intelligence opportunities.

        Returns a dict:
        {
            "measures": [{"col": "sales", "agg": "sum", "priority": 95, ...}, ...],
            "dimensions": [{"col": "region", "cardinality": 5, "priority": 80, ...}, ...],
            "time_columns": [{"col": "order_date", "range": "2024-01 to 2025-12", "freq": "M", ...}],
            "time_intelligence": {"primary_date": "order_date", "has_yoy": True, "has_mom": True, ...},
            "layout_priority": [{"rank": 1, "widget_type": "summary", ...}, ...],
            "data_quality": {"completeness": 0.95, "total_nulls": 120, ...},
            "row_count": 5000,
            "col_count": 15
        }
        """
        import numpy as np

        fingerprint = {
            "measures": [],
            "dimensions": [],
            "time_columns": [],
            "time_intelligence": {},
            "layout_priority": [],
            "data_quality": {},
            "row_count": len(self.df) if self.df is not None else 0,
            "col_count": len(self.df.columns) if self.df is not None else 0,
        }

        if self.df is None:
            return fingerprint

        numeric_cols, categorical_cols, datetime_cols = self._get_column_types()

        # ── 1. CLASSIFY MEASURES (numeric columns suitable for aggregation) ──
        # Multi-layer detection to filter out identifier/non-aggregatable columns:
        #   Layer 1: Expanded keyword matching (catches names like "Mobile No", "Aadhaar")
        #   Layer 2: Statistical heuristics (catches ANY identifier regardless of name)
        #   Layer 3: LLM classification for ambiguous cases
        #
        # KEY PRINCIPLE: A "measure" is a column where SUM or MEAN is semantically
        # meaningful. Phone numbers summed = nonsense. Salary summed = meaningful.

        # ── Layer 1: Keyword-based ID detection ──
        id_keywords = [
            'id', 'uuid', 'index', 'key', 'pk', 'fk',          # Database keys
            'code', 'zip', 'pin', 'pincode', 'postal',          # Codes & postal
            'phone', 'mobile', 'cell', 'contact', 'tel',        # Phone numbers
            'fax', 'whatsapp',
            'aadhaar', 'aadhar', 'adhaar', 'pan', 'ssn',        # Government IDs
            'passport', 'license', 'licence', 'voter',
            'gst', 'gstin', 'tin', 'uan', 'esi',
            'account', 'acct', 'ifsc', 'swift', 'iban',         # Banking
            'roll', 'enrollment', 'enrolment', 'registration',  # Registration nos
            'serial', 'sr no', 'srno', 'sl no', 'slno',         # Serial numbers
            'ticket', 'token', 'ref', 'reference',               # Reference numbers
            'barcode', 'sku', 'upc', 'ean', 'isbn',             # Product codes
            'ip', 'mac', 'imei', 'sim',                          # Device identifiers
            'latitude', 'longitude', 'lat', 'lon', 'lng',       # Coordinates
            'employee no', 'emp no', 'empno', 'staff no',       # Employee identifiers
            'prn', 'seat no', 'seatno', 'seat_no',              # Exam/seat identifiers
            'founded','year',                                             # Founding year (not aggregatable)
        ]

        def _is_identifier_by_stats(col: str) -> tuple:
            """
            Layer 2: Statistical heuristics to detect identifier columns.
            Returns (is_identifier: bool, reason: str).

            Heuristics:
            1. High uniqueness ratio (>85% unique) + large integers → ID
            2. Fixed digit length (>80% values same # of digits) → phone/PIN
            3. Sequential pattern (sorted diffs mostly constant) → auto-increment ID
            4. Very large integers (mean > 1e6) + high uniqueness → ID/phone
            5. All integers + no meaningful spread pattern → likely code
            """
            try:
                series = self.df[col].dropna()
                if len(series) < 10:
                    return False, ""

                n = len(series)
                nunique = series.nunique()
                uniqueness_ratio = nunique / n

                col_min = float(series.min())
                col_max = float(series.max())
                col_mean = float(series.mean())
                col_std = float(series.std()) if n > 1 else 0

                # Check 1: All integers? (no decimals)
                is_all_int = (series == series.astype(int)).all() if series.dtype in ['float64', 'int64'] else False

                # Check 2: High uniqueness + large values → likely ID
                if uniqueness_ratio > 0.85 and is_all_int and col_mean > 1000:
                    return True, f"high_uniqueness({uniqueness_ratio:.2f})+large_int(mean={col_mean:.0f})"

                # Check 3: Fixed digit length (phone numbers, PINs, Aadhaar)
                if is_all_int and col_min > 0:
                    digit_lengths = series.astype(int).astype(str).str.len()
                    mode_len = digit_lengths.mode()
                    if len(mode_len) > 0:
                        mode_pct = (digit_lengths == mode_len.iloc[0]).mean()
                        dominant_len = int(mode_len.iloc[0])
                        # Phone: 10 digits, Aadhaar: 12, PIN: 6, etc.
                        if mode_pct > 0.80 and dominant_len >= 4 and uniqueness_ratio > 0.5:
                            return True, f"fixed_length({dominant_len}digits,{mode_pct:.0%}uniform)"

                # Check 4: Sequential/near-sequential pattern (auto-increment IDs)
                if is_all_int and uniqueness_ratio > 0.9 and n >= 20:
                    sorted_vals = series.sort_values().values
                    diffs = np.diff(sorted_vals)
                    if len(diffs) > 0:
                        # If >70% of diffs are the same value → sequential
                        mode_diff = float(pd.Series(diffs).mode().iloc[0]) if len(pd.Series(diffs).mode()) > 0 else 0
                        sequential_pct = (diffs == mode_diff).mean() if mode_diff > 0 else 0
                        if sequential_pct > 0.7:
                            return True, f"sequential(gap={mode_diff:.0f},{sequential_pct:.0%}consistent)"

                # Check 5: Very large integers with low coefficient of variation
                # IDs cluster in a narrow range (e.g., 9800000000-9899999999 for phones)
                if is_all_int and col_mean > 1e6 and uniqueness_ratio > 0.5:
                    cv = col_std / col_mean if col_mean > 0 else 0
                    if cv < 0.3:
                        return True, f"large_int_narrow_range(mean={col_mean:.0f},cv={cv:.3f})"

                # Check 6: Uniqueness > 95% for any integer column with > 50 rows
                if is_all_int and uniqueness_ratio > 0.95 and n > 50:
                    return True, f"near_unique_int({uniqueness_ratio:.2f})"

            except Exception:
                pass
            return False, ""

        # Precompute user override sets for O(1) lookup
        _uh_exclude  = set(user_hints.get("force_exclude",  [])) if user_hints else set()
        _uh_measure  = set(user_hints.get("force_measure",  [])) if user_hints else set()
        _uh_dim      = set(user_hints.get("force_dimension",[])) if user_hints else set()

        # Track columns rejected as identifiers for logging
        rejected_as_id = []

        for col in numeric_cols:
            # ── User override: force-exclude beats everything ──
            if col in _uh_exclude:
                logger.info(f"[Fingerprint] User excluded '{col}' → skipping")
                continue

            # ── User override: force-include as measure (bypasses ALL ID detection) ──
            if col in _uh_measure:
                logger.info(f"[Fingerprint] User forced '{col}' as measure → priority=100")
                try:
                    stats = self.df[col].describe()
                    non_null_pct = 1 - (self.df[col].isna().sum() / len(self.df))
                    fingerprint["measures"].append({
                        "col": col, "agg": "sum", "priority": 100,
                        "sum":  round(float(self.df[col].sum()), 2),
                        "mean": round(float(stats.get('mean', 0)), 2),
                        "std":  round(float(stats.get('std',  0)), 2),
                        "min":  round(float(stats.get('min',  0)), 2),
                        "max":  round(float(stats.get('max',  0)), 2),
                        "non_null_pct": round(non_null_pct, 3),
                        "format_hint": "number", "user_forced": True,
                    })
                except Exception as e:
                    logger.debug(f"[Fingerprint] User-forced measure stats failed for '{col}': {e}")
                continue

            col_lower = col.lower().replace('_', ' ').replace('-', ' ')
            is_id_like = any(kw in col_lower for kw in id_keywords)
            
            # Exemption: columns with explicit measure keywords should NOT be treated as IDs
            # (e.g., "tax_rate", "percentage_code" if used for the actual value)
            if is_id_like:
                measure_exponents = ['percent', 'percentage', 'pct', 'rate', 'ratio', 'growth', 'amount', 'total']
                if any(mw in col_lower for mw in measure_exponents):
                    is_id_like = False

            # Extra word-boundary check for short keywords that could appear
            # inside legitimate measure names (e.g., "year" inside "yearly_revenue")
            if not is_id_like:
                _year_like = re.search(r'\byear\b', col_lower)
                if _year_like:
                    # Only treat as ID if it's the WHOLE column or combined with
                    # non-aggregatable words (e.g. "join year", "birth year")
                    # but NOT if paired with aggregation words ("yearly revenue")
                    agg_check = ['revenue', 'sales', 'amount', 'price', 'cost', 'income',
                                 'profit', 'budget', 'expense', 'count', 'total']
                    if not any(ac in col_lower for ac in agg_check):
                        is_id_like = True

            # Layer 2: Statistical heuristics (regardless of column name)
            if not is_id_like:
                is_id_like, id_reason = _is_identifier_by_stats(col)
                if is_id_like:
                    # Exception: columns with aggregation-friendly names should NOT be excluded
                    # even if stats look ID-like (e.g., "Total Applications" with all unique big values)
                    agg_friendly = ['revenue', 'sales', 'amount', 'price', 'cost', 'profit',
                                    'income', 'payment', 'total', 'fee', 'salary', 'wage',
                                    'budget', 'expense', 'count', 'quantity', 'qty',
                                    'score', 'rating', 'mark', 'marks', 'grade', 'points',
                                    'bonus', 'discount', 'tax', 'interest', 'commission',
                                    'application', 'applications', 'order', 'orders',
                                    'units', 'items', 'weight', 'volume', 'area', 'population',
                                    'balance', 'deposit', 'withdrawal', 'transaction',
                                    'pending', 'approved', 'rejected', 'installment',
                                    'percent', 'percentage', 'pct', 'rate', 'ratio', 'growth']
                    if any(af in col_lower for af in agg_friendly):
                        is_id_like = False  # Override: this IS a valid measure
                        logger.debug(f"[Fingerprint] '{col}' looks like ID ({id_reason}) but has agg-friendly name → keeping as measure")
                    else:
                        rejected_as_id.append((col, id_reason))

            if is_id_like:
                logger.debug(f"[Fingerprint] Excluded '{col}' as identifier: {rejected_as_id[-1][1] if rejected_as_id and rejected_as_id[-1][0] == col else 'keyword match'}")
                continue

            try:
                stats = self.df[col].describe()
                col_sum = float(self.df[col].sum()) if not pd.isna(self.df[col].sum()) else 0
                col_mean = float(stats.get('mean', 0)) if not pd.isna(stats.get('mean', 0)) else 0
                col_std = float(stats.get('std', 0)) if not pd.isna(stats.get('std', 0)) else 0
                non_null_pct = 1 - (self.df[col].isna().sum() / len(self.df))

                # Detect best aggregation method
                # Currency/revenue-like → sum; rates/scores → mean; counts → sum
                currency_hints = ['revenue', 'sales', 'amount', 'price', 'cost', 'profit', 'income',
                                  'payment', 'total', 'fee', 'salary', 'wage', 'budget', 'expense']
                rate_hints = ['rate', 'ratio', 'percent', 'pct', 'score', 'rating', 'avg', 'average',
                              'index', 'coefficient', 'density', 'efficiency']
                count_hints = ['count', 'quantity', 'qty', 'num', 'number', 'units', 'items', 'orders']
                # Per-record attributes: these describe individual entities → always mean
                attribute_hints = ['age', 'height', 'weight', 'experience', 'tenure', 'years',
                                   'bonus', 'discount', 'margin', 'mark', 'marks', 'grade',
                                   'distance', 'duration', 'hours', 'days', 'months',
                                   'level', 'rank', 'size', 'length', 'width', 'area',
                                   'temperature', 'temp']

                if any(h in col_lower for h in currency_hints):
                    agg = 'sum'
                    priority = 90
                elif any(h in col_lower for h in rate_hints):
                    agg = 'mean'
                    priority = 70
                elif any(h in col_lower for h in count_hints):
                    agg = 'sum'
                    priority = 80
                elif any(h in col_lower for h in attribute_hints):
                    agg = 'mean'
                    priority = 55
                else:
                    # Smart default: use statistical properties to decide
                    col_min = float(stats.get('min', 0))
                    col_max = float(stats.get('max', 0))
                    value_range = col_max - col_min
                    nunique_ratio = self.df[col].nunique() / max(len(self.df), 1)

                    # If values are bounded in a small range (0-100, 0-10) → likely a per-record attribute → mean
                    # If many repeated values and large sum → likely a transactional amount → sum
                    if value_range <= 150 and col_max <= 200:
                        agg = 'mean'  # Bounded range: age, score, grade, rating
                        priority = 55
                    elif nunique_ratio < 0.05 and col_sum > col_mean * 50:
                        agg = 'sum'   # Few unique values with large totals: likely categories of amounts
                        priority = 60
                    elif col_sum > col_mean * 20:
                        agg = 'sum'   # Large multiplier suggests transactional/summable
                        priority = 60
                    else:
                        agg = 'mean'  # Default to mean — safer for unknown columns
                        priority = 50

                # Boost priority for columns with good data quality
                priority = int(priority * non_null_pct)

                # Format hint
                format_hint = 'number'
                if any(h in col_lower for h in ['revenue', 'sales', 'price', 'cost', 'profit',
                                                  'amount', 'salary', 'income', 'budget', 'fee',
                                                  'payment', 'expense', 'wage']):
                    format_hint = 'currency'
                elif any(h in col_lower for h in ['rate', 'percent', 'pct', 'ratio']):
                    format_hint = 'percentage'
                elif any(h in col_lower for h in ['bonus', 'discount', 'margin', 'commission', 'tip']):
                    format_hint = 'currency'

                fingerprint["measures"].append({
                    "col": col,
                    "agg": agg,
                    "priority": priority,
                    "sum": round(col_sum, 2),
                    "mean": round(col_mean, 2),
                    "std": round(col_std, 2),
                    "min": round(float(stats.get('min', 0)), 2) if not pd.isna(stats.get('min', 0)) else 0,
                    "max": round(float(stats.get('max', 0)), 2) if not pd.isna(stats.get('max', 0)) else 0,
                    "non_null_pct": round(non_null_pct, 3),
                    "format_hint": format_hint,
                })
            except Exception as e:
                logger.debug(f"[Fingerprint] Skipped measure '{col}': {e}")

        # Sort measures by priority (highest first)
        fingerprint["measures"].sort(key=lambda m: m["priority"], reverse=True)

        # ── Layer 3: LLM classification for borderline measures ──
        # If we have measures that have no keyword match (priority <= 60) and look
        # statistically ambiguous, ask the LLM once for all of them in a single call
        if fingerprint["measures"] and hasattr(self, 'llm') and self.llm:
            ambiguous_measures = [
                m for m in fingerprint["measures"]
                if m["priority"] <= 60  # No strong keyword match
                and m["mean"] > 100     # Not a small bounded value
                and (self.df[m["col"]].nunique() / max(len(self.df), 1)) > 0.4  # Fairly unique
            ]
            if ambiguous_measures:
                try:
                    col_descriptions = []
                    for m in ambiguous_measures:
                        sample = self.df[m["col"]].dropna().head(5).tolist()
                        sample_str = ", ".join(str(v) for v in sample)
                        col_descriptions.append(f"- {m['col']}: sample values=[{sample_str}], mean={m['mean']:.1f}, min={m['min']}, max={m['max']}")

                    prompt = (
                        "You are a data classification expert. For each column below, determine if it is:\n"
                        "  MEASURE — a numeric value where SUM or AVERAGE is meaningful "
                        "(e.g., revenue, salary, count, score, applications)\n"
                        "  IDENTIFIER — a numeric code/ID where SUM/AVERAGE is meaningless "
                        "(e.g., phone number, roll number, account number, PIN code, serial number)\n\n"
                        "Columns to classify:\n" + "\n".join(col_descriptions) + "\n\n"
                        "Reply with ONLY a JSON object: {\"column_name\": \"MEASURE\" or \"IDENTIFIER\", ...}\n"
                        "Do not add any explanation."
                    )
                    llm_result = invoke_llm_with_retry(self.llm, prompt, max_retries=1, context_name="Column classification")
                    llm_result = self._clean_llm_json(llm_result)
                    classification = json.loads(llm_result)

                    for m in ambiguous_measures:
                        verdict = classification.get(m["col"], "MEASURE").upper()
                        if verdict == "IDENTIFIER":
                            fingerprint["measures"] = [x for x in fingerprint["measures"] if x["col"] != m["col"]]
                            rejected_as_id.append((m["col"], "llm_classified_as_identifier"))
                            logger.info(f"[Fingerprint] LLM classified '{m['col']}' as IDENTIFIER → excluded")
                except Exception as llm_err:
                    logger.debug(f"[Fingerprint] LLM column classification failed: {llm_err}")

        # Log summary of identifier filtering
        if rejected_as_id:
            logger.info(f"[Fingerprint] 🚫 Excluded {len(rejected_as_id)} identifier columns: "
                        f"{', '.join(f'{col}({reason})' for col, reason in rejected_as_id)}")

        # ── 2. CLASSIFY DIMENSIONS (categorical columns for grouping) ──
        for col in categorical_cols:
            # ── User override: force-exclude ──
            if col in _uh_exclude:
                logger.info(f"[Fingerprint] User excluded dimension '{col}' → skipping")
                continue

            col_lower = col.lower()
            # Skip ID-like, email, URL columns (unless user explicitly forced as dimension)
            skip_keywords = ['id', 'uuid', 'email', 'phone', 'url', 'path', 'address', 'description',
                             'comment', 'note', 'notes', 'body', 'content', 'text', 'message']
            if any(kw in col_lower for kw in skip_keywords) and col not in _uh_dim:
                continue

            try:
                nunique = self.df[col].nunique()
                total = len(self.df)

                # Only useful as dimension if cardinality is between 2 and 200
                # (raised to allow filters with up to 200 unique values)
                if nunique < 2 or nunique > 200:
                    continue

                non_null_pct = 1 - (self.df[col].isna().sum() / total)
                # Store ALL unique values so filters can show every option
                top_values = self.df[col].value_counts().to_dict()

                # Priority scoring for dimensions
                geo_hints = ['region', 'country', 'state', 'city', 'location', 'area', 'zone', 'territory']
                product_hints = ['category', 'type', 'product', 'brand', 'segment', 'class', 'group', 'department']
                time_dim_hints = ['month', 'quarter', 'year', 'day', 'week', 'period', 'season']

                priority = 50
                dim_type = 'categorical'
                if any(h in col_lower for h in geo_hints):
                    priority = 85
                    dim_type = 'geographic'
                elif any(h in col_lower for h in product_hints):
                    priority = 80
                    dim_type = 'product'
                elif any(h in col_lower for h in time_dim_hints):
                    priority = 75
                    dim_type = 'time_dimension'
                else:
                    # Boost medium-cardinality dimensions (3-15 values are ideal for charts)
                    if 3 <= nunique <= 15:
                        priority = 65

                priority = int(priority * non_null_pct)

                fingerprint["dimensions"].append({
                    "col": col,
                    "cardinality": nunique,
                    "priority": priority,
                    "dim_type": dim_type,
                    "non_null_pct": round(non_null_pct, 3),
                    "top_values": {str(k): int(v) for k, v in top_values.items()},
                })
            except Exception as e:
                logger.debug(f"[Fingerprint] Skipped dimension '{col}': {e}")

        fingerprint["dimensions"].sort(key=lambda d: d["priority"], reverse=True)

        # ── User hints: boost priority of explicitly mentioned/focused columns ──
        if user_hints:
            focus_cols = set(user_hints.get("focus_on", []) + user_hints.get("force_measure", []))
            for m in fingerprint["measures"]:
                if m["col"] in focus_cols:
                    m["priority"] = max(m["priority"], 95)
            for d in fingerprint["dimensions"]:
                if d["col"] in set(user_hints.get("focus_on", []) + user_hints.get("force_dimension", [])):
                    d["priority"] = max(d["priority"], 95)
            # Re-sort after boosting
            fingerprint["measures"].sort(key=lambda m: m["priority"], reverse=True)
            fingerprint["dimensions"].sort(key=lambda d: d["priority"], reverse=True)

            # Store the raw requirements text for use in executive summary prompt
            if user_hints.get("raw"):
                fingerprint["user_notes"] = user_hints["raw"]

        # ── 3. DETECT TIME COLUMNS & TIME INTELLIGENCE ──
        primary_date = None
        for col in datetime_cols:
            try:
                date_series = self.df[col].dropna()
                if len(date_series) < 3:
                    continue

                date_min = date_series.min()
                date_max = date_series.max()
                date_range_days = (date_max - date_min).days

                # Detect frequency (daily, monthly, etc.)
                if date_range_days > 365 * 2:
                    freq = 'Y'
                elif date_range_days > 180:
                    freq = 'Q'
                elif date_range_days > 30:
                    freq = 'M'
                elif date_range_days > 7:
                    freq = 'W'
                else:
                    freq = 'D'

                tc = {
                    "col": col,
                    "min": str(date_min.date()) if hasattr(date_min, 'date') else str(date_min),
                    "max": str(date_max.date()) if hasattr(date_max, 'date') else str(date_max),
                    "range_days": date_range_days,
                    "freq": freq,
                    "non_null_count": len(date_series),
                }
                fingerprint["time_columns"].append(tc)

                # Select primary date (longest range, most non-nulls)
                if primary_date is None or date_range_days > primary_date.get("range_days", 0):
                    primary_date = tc
            except Exception as e:
                logger.debug(f"[Fingerprint] Skipped time col '{col}': {e}")

        # Build time intelligence hints
        if primary_date:
            date_col = primary_date["col"]
            range_days = primary_date["range_days"]
            fingerprint["time_intelligence"] = {
                "primary_date": date_col,
                "has_yoy": range_days > 365,         # Year-over-Year possible
                "has_mom": range_days > 60,           # Month-over-Month possible
                "has_qoq": range_days > 180,          # Quarter-over-Quarter possible
                "has_ytd": range_days > 30,           # Year-to-Date possible
                "suggested_grain": primary_date["freq"],
                "date_range": f"{primary_date['min']} to {primary_date['max']}",
            }

            # Compute time-based growth metrics for the top measure
            if fingerprint["measures"]:
                top_measure = fingerprint["measures"][0]["col"]
                try:
                    ts = self.df.set_index(date_col)[top_measure].resample('ME').sum().dropna()
                    if len(ts) >= 2:
                        latest = float(ts.iloc[-1])
                        prev = float(ts.iloc[-2])
                        if prev > 0:
                            mom_growth = round(((latest - prev) / prev) * 100, 1)
                            fingerprint["time_intelligence"]["mom_growth"] = mom_growth
                            fingerprint["time_intelligence"]["mom_measure"] = top_measure
                            fingerprint["time_intelligence"]["latest_period"] = str(ts.index[-1].strftime('%Y-%m'))
                            fingerprint["time_intelligence"]["latest_value"] = round(latest, 2)
                            fingerprint["time_intelligence"]["prev_value"] = round(prev, 2)

                    if len(ts) >= 13:
                        latest_12 = float(ts.iloc[-12:].sum())
                        prev_12 = float(ts.iloc[-24:-12].sum()) if len(ts) >= 24 else None
                        if prev_12 and prev_12 > 0:
                            yoy_growth = round(((latest_12 - prev_12) / prev_12) * 100, 1)
                            fingerprint["time_intelligence"]["yoy_growth"] = yoy_growth
                except Exception as e:
                    logger.debug(f"[Fingerprint] Time intelligence calc failed: {e}")

        # ── 4. DATA QUALITY SUMMARY ──
        total_cells = len(self.df) * len(self.df.columns)
        total_nulls = int(self.df.isna().sum().sum())
        fingerprint["data_quality"] = {
            "completeness": round(1 - (total_nulls / total_cells), 4) if total_cells > 0 else 1.0,
            "total_nulls": total_nulls,
            "total_cells": total_cells,
            "duplicate_rows": int(self.df.duplicated().sum()),
        }

        # ── 5. LAYOUT PRIORITY (which widgets to generate and in what order) ──
        rank = 0

        # Rank 0: AI Summary Banner (always first, full-width)
        rank += 1
        fingerprint["layout_priority"].append({
            "rank": rank, "widget_type": "summary", "gridW": 12, "gridH": 2,
            "reason": "AI narrative overview of the dataset"
        })

        # Rank 1: Top KPIs from highest-priority measures
        for m in fingerprint["measures"][:4]:
            rank += 1
            fingerprint["layout_priority"].append({
                "rank": rank, "widget_type": "kpi", "gridW": 3, "gridH": 2,
                "source_col": m["col"], "agg": m["agg"],
                "reason": f"Top metric: {m['col']} ({m['agg']})"
            })

        # Rank 2: Time-intelligence KPI (MoM growth) if available
        ti = fingerprint.get("time_intelligence", {})
        if ti.get("mom_growth") is not None:
            rank += 1
            fingerprint["layout_priority"].append({
                "rank": rank, "widget_type": "kpi", "gridW": 3, "gridH": 2,
                "reason": f"MoM growth for {ti.get('mom_measure', 'top metric')}",
                "metric": "mom_growth"
            })

        # Rank 3: Trend chart (time series) if date exists
        if primary_date and fingerprint["measures"]:
            rank += 1
            fingerprint["layout_priority"].append({
                "rank": rank, "widget_type": "chart", "chartType": "area",
                "gridW": 12, "gridH": 3,
                "source_col": fingerprint["measures"][0]["col"],
                "group_by": primary_date["col"],
                "reason": f"Time trend of {fingerprint['measures'][0]['col']}"
            })

        # Rank 4: Distribution charts for top dimensions
        for d in fingerprint["dimensions"][:2]:
            rank += 1
            chart_type = "pie" if d["cardinality"] <= 6 else "bar"
            fingerprint["layout_priority"].append({
                "rank": rank, "widget_type": "chart", "chartType": chart_type,
                "gridW": 6, "gridH": 3,
                "source_col": d["col"],
                "reason": f"Distribution of {d['col']} ({d['dim_type']})"
            })

        # Rank 5: Insight widget
        rank += 1
        fingerprint["layout_priority"].append({
            "rank": rank, "widget_type": "insight", "gridW": 4, "gridH": 2,
            "reason": "AI-generated data insight"
        })

        # Rank 6: Top-N list from first high-priority dimension + measure
        if fingerprint["dimensions"] and fingerprint["measures"]:
            rank += 1
            fingerprint["layout_priority"].append({
                "rank": rank, "widget_type": "list", "gridW": 4, "gridH": 3,
                "source_col": fingerprint["dimensions"][0]["col"],
                "measure_col": fingerprint["measures"][0]["col"],
                "reason": f"Top {fingerprint['dimensions'][0]['col']} by {fingerprint['measures'][0]['col']}"
            })

        logger.info(f"[Fingerprint] Built fingerprint: {len(fingerprint['measures'])} measures, "
                     f"{len(fingerprint['dimensions'])} dimensions, {len(fingerprint['time_columns'])} time cols, "
                     f"{len(fingerprint['layout_priority'])} layout items")

        return fingerprint

    def save_dashboard(self, widgets: list, fingerprint: dict | None = None) -> bool:
        """
        Save dashboard widgets (and fingerprint) to database for persistence.
        Returns True if successful, False otherwise.
        Skips saving for board files (not in file_registry).
        """
        try:
            # Board files live in board_files, not file_registry — skip dashboards table
            with self.db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 FROM file_registry WHERE file_uuid = %s", (self.file_uuid,))
                    if not cur.fetchone():
                        logger.debug(f"[save_dashboard] Skipping — {self.file_uuid} is a board file")
                        return True

            dashboard_data = {
                "status": "success",
                "filename": self.filename,
                "file_uuid": self.file_uuid,
                "total_rows": len(self.df),
                "total_columns": len(self.df.columns),
                "widgets": widgets,
                "fingerprint": fingerprint or {}
            }
            
            with self.db.get_connection() as conn:
                with conn.cursor() as cur:
                    # Upsert: insert or update if already exists (keyed on dashboard_id PK)
                    cur.execute("""
                        INSERT INTO dashboards (dashboard_id, file_uuid, widgets_json, created_at, updated_at)
                        VALUES (%s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                        ON CONFLICT (dashboard_id) DO UPDATE
                        SET widgets_json = EXCLUDED.widgets_json, updated_at = CURRENT_TIMESTAMP;
                    """, (
                        f"dash-{self.file_uuid}",
                        self.file_uuid,
                        json.dumps(dashboard_data, default=str)
                    ))
                    conn.commit()
            
            logger.info(f"✅ Dashboard saved for file {self.file_uuid}")
            return True
        except Exception as e:
            log_full_exception(e, "Dashboard save error")
            return False
    
    def load_dashboard(self) -> dict:
        """
        Load cached dashboard from database.
        Returns dashboard data if found, None otherwise.
        """
        try:
            with self.db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT widgets_json, updated_at
                        FROM dashboards
                        WHERE file_uuid = %s
                        LIMIT 1;
                    """, (self.file_uuid,))
                    
                    result = cur.fetchone()
                    if result:
                        # psycopg2 auto-deserializes JSONB to dict, no need for json.loads()
                        dashboard_data = result[0] if isinstance(result[0], dict) else json.loads(result[0])
                        updated_at = result[1]
                        logger.info(f"✅ Loaded cached dashboard for file {self.file_uuid} (updated: {updated_at})")
                        return dashboard_data
            
            logger.info(f"ℹ️ No cached dashboard found for file {self.file_uuid}")
            return None
        except Exception as e:
            log_full_exception(e, "Dashboard load error")
            return None
    
    def delete_dashboard(self) -> bool:
        """
        Delete cached dashboard from database (useful when regenerating).
        """
        try:
            with self.db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM dashboards WHERE file_uuid = %s;", (self.file_uuid,))
                    conn.commit()
            
            logger.info(f"✅ Dashboard deleted for file {self.file_uuid}")
            return True
        except Exception as e:
            log_full_exception(e, "Dashboard delete error")
            return False

    def save_project_dashboard(self, project_id: str, widgets: list, fingerprint: dict | None = None) -> bool:
        """Save a project-level dashboard (keyed by project_id, not file_uuid)."""
        try:
            dashboard_data = self._build_response_envelope(widgets, fingerprint)
            with self.db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO dashboards (dashboard_id, project_id, file_uuid, widgets_json, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                        ON CONFLICT (dashboard_id) DO UPDATE
                        SET widgets_json = EXCLUDED.widgets_json, file_uuid = EXCLUDED.file_uuid, updated_at = CURRENT_TIMESTAMP;
                    """, (
                        f"proj-{project_id}",
                        project_id,
                        self.file_uuid,
                        json.dumps(dashboard_data, default=str)
                    ))
                    conn.commit()
            logger.info(f"✅ Project dashboard saved for project {project_id}")
            return True
        except Exception as e:
            log_full_exception(e, "Project dashboard save error")
            return False

    # ── NEW DATA-DRIVEN HELPERS ────────────────────────────────────

    @observe(name="dashboard.executive_summary", as_type="span")
    def _generate_executive_summary(self, fingerprint: dict) -> str:
        """
        Generate an executive summary narrative using LLM but with
        pre-computed real values from fingerprint to ensure accuracy.
        Falls back to a deterministic summary if LLM fails.
        """
        measures = fingerprint.get("measures", [])
        dims = fingerprint.get("dimensions", [])
        ti = fingerprint.get("time_intelligence", {})
        dq = fingerprint.get("data_quality", {})
        row_count = fingerprint.get("row_count", len(self.df))
        col_count = fingerprint.get("col_count", len(self.df.columns))
        completeness = dq.get("completeness", 1.0)

        # Build a facts block from pre-computed data for the LLM
        facts = [f"Dataset: {self.filename}, {row_count:,} rows, {col_count} columns."]
        for m in measures[:6]:
            val = m.get("sum") if m.get("agg") == "sum" else m.get("mean", 0)
            fmt_val = self._format_kpi_value(val, m.get("format_hint", "number"), m.get("agg", "sum"))
            facts.append(f"{self._title_case(m['col'])} ({m['agg']}): {fmt_val} (range {m['min']}–{m['max']})")
        for d in dims[:4]:
            top_vals = list(d["top_values"].keys())[:3]
            facts.append(f"{self._title_case(d['col'])}: {d['cardinality']} unique values, top: {', '.join(top_vals)}")
        if ti.get("mom_growth") is not None:
            direction = "up" if ti["mom_growth"] > 0 else "down"
            facts.append(f"MoM growth: {direction} {abs(ti['mom_growth'])}% for {self._title_case(ti.get('mom_measure', ''))}")
        if ti.get("yoy_growth") is not None:
            direction = "up" if ti["yoy_growth"] > 0 else "down"
            facts.append(f"YoY growth: {direction} {abs(ti['yoy_growth'])}%")
        facts.append(f"Data completeness: {round(completeness * 100, 1)}%")

        # If user provided custom requirements, append as a focus hint
        user_notes = fingerprint.get("user_notes", "")
        user_note_line = f"\nUser focus areas: {user_notes}" if user_notes else ""

        langfuse_context.update_current_observation(
            input={
                "row_count": row_count,
                "col_count": col_count,
                "facts_count": len(facts),
            },
            metadata={
                "file_uuid": self.file_uuid,
                "filename": self.filename,
                "measure_count": len(measures),
                "dimension_count": len(dims),
            },
            tags=["dashboard", "executive-summary"],
        )

        try:
            prompt = f"""Write a 2-3 sentence executive summary for a data dashboard.
Use ONLY the pre-computed facts below — do NOT invent or hallucinate any numbers.
Be data-dense: mention the top metric value, any growth trend, the dominant dimension value, and data quality.
Do not use markdown. Do not add bullet points. Write in plain sentences.{user_note_line}

PRE-COMPUTED FACTS:
{chr(10).join('- ' + f for f in facts)}

Write the summary now (2-3 sentences only):"""

            _summary_cbs = None
            if _LANGFUSE_CALLBACK_AVAILABLE:
                try:
                    lf_cb = langfuse_context.get_current_langchain_handler()
                    _summary_cbs = [lf_cb] if lf_cb else None
                except Exception:
                    _summary_cbs = None

            summary = invoke_llm_with_retry(
                self.llm,
                prompt,
                max_retries=2,
                context_name="Executive summary",
                callbacks=_summary_cbs,
            )
            summary = summary.strip().strip('"').strip("'")
            if len(summary) > 30:
                langfuse_context.update_current_observation(
                    output={
                        "status": "success",
                        "used_llm": True,
                        "llm_callbacks_attached": bool(_summary_cbs),
                        "summary_preview": summary[:300],
                        "summary_length": len(summary),
                    }
                )
                return summary
        except Exception as e:
            logger.warning(f"[_generate_executive_summary] LLM failed: {e}, using deterministic fallback")

        # Deterministic fallback
        parts = [f"This dataset contains {row_count:,} records across {col_count} columns."]
        if measures:
            top = measures[0]
            val = top.get("sum") if top.get("agg") == "sum" else top.get("mean", 0)
            fmt = self._format_kpi_value(val, top.get("format_hint", "number"), top.get("agg", "sum"))
            parts.append(f"Primary metric: {self._title_case(top['col'])} ({top['agg']}) is {fmt}.")
        if ti.get("mom_growth") is not None:
            direction = "up" if ti["mom_growth"] > 0 else "down"
            parts.append(f"{self._title_case(ti.get('mom_measure', ''))} is {direction} {abs(ti['mom_growth'])}% MoM.")
        if dims:
            top_dim = dims[0]
            top_val = list(top_dim.get("top_values", {}).keys())[:1]
            parts.append(f"Leading {self._title_case(top_dim['col'])}: {top_val[0] if top_val else 'N/A'}.")
        parts.append(f"Data is {round(completeness * 100, 1)}% complete.")
        fallback = " ".join(parts)
        langfuse_context.update_current_observation(
            output={
                "status": "fallback",
                "used_llm": False,
                "summary_preview": fallback[:300],
                "summary_length": len(fallback),
            }
        )
        return fallback

    @observe(name="dashboard.insight_enrichment", as_type="span")
    def _enrich_insight_with_llm(self, raw_fact_block: str, title: str) -> str:
        """
        Use LLM to turn a raw statistical fact block into a clear, descriptive,
        non-technical insight paragraph that a business user can immediately
        understand and act on.  Falls back to the raw block on failure.
        """
        langfuse_context.update_current_observation(
            input={"title": title, "raw_fact_preview": raw_fact_block[:400]},
            metadata={"file_uuid": self.file_uuid, "filename": self.filename},
            tags=["dashboard", "insight-enrichment"],
        )
        try:
            prompt = (
                "You are a senior data analyst writing insights for a business dashboard.\n"
                "Rewrite the statistical finding below into a clear, descriptive, informative\n"
                "paragraph (3-5 sentences) that a non-technical business user can understand.\n\n"
                "Rules:\n"
                "- Focus on answering the user's question if one is provided in the raw finding.\n"
                "- Explain WHAT the finding means in plain language first.\n"
                "- Explain WHY it matters and what potential business implication it has.\n"
                "- If the finding references a statistical term (outliers, IQR, skewness, correlation, etc.),\n"
                "  briefly explain that term in parentheses so the user is not confused.\n"
                "- Use ONLY the numbers provided — do NOT invent any numbers.\n"
                "- Do NOT use markdown, bullet points, or headers. Write flowing sentences.\n"
                "- Keep it under 80 words.\n\n"
                f"TITLE: {title}\n\n"
                f"RAW FINDING:\n{raw_fact_block}\n\n"
                "Rewrite now:"
            )
            _insight_cbs = None
            if _LANGFUSE_CALLBACK_AVAILABLE:
                try:
                    lf_cb = langfuse_context.get_current_langchain_handler()
                    _insight_cbs = [lf_cb] if lf_cb else None
                except Exception:
                    _insight_cbs = None
            enriched = invoke_llm_with_retry(
                self.llm,
                prompt,
                max_retries=1,
                context_name=f"Insight: {title}",
                callbacks=_insight_cbs,
            )
            enriched = enriched.strip().strip('"').strip("'")
            if len(enriched) > 40:
                langfuse_context.update_current_observation(
                    output={
                        "status": "success",
                        "used_llm": True,
                        "llm_callbacks_attached": bool(_insight_cbs),
                        "enriched_preview": enriched[:300],
                    }
                )
                return enriched
        except Exception as e:
            logger.debug(f"[_enrich_insight_with_llm] LLM failed for '{title}': {e}")
        langfuse_context.update_current_observation(
            output={
                "status": "fallback",
                "used_llm": False,
                "enriched_preview": raw_fact_block[:300],
            }
        )
        return raw_fact_block

    def _generate_data_insights(self, fingerprint: dict) -> list:
        """
        Generate data-driven insight widgets by analyzing actual data patterns.
        All values are computed from pandas — never hallucinated.
        Each insight's text is enriched via LLM for clarity; falls back to
        deterministic text if LLM is unavailable.
        Returns a list of insight widget dicts.
        """
        insights = []
        measures = fingerprint.get("measures", [])
        dims = fingerprint.get("dimensions", [])
        ti = fingerprint.get("time_intelligence", {})
        dq = fingerprint.get("data_quality", {})
        completeness = dq.get("completeness", 1.0)

        # ── Insight 1: Concentration analysis for top dimension × measure ──
        if dims and measures:
            d_col = dims[0]["col"]
            m_col = measures[0]["col"]
            agg = measures[0].get("agg", "sum")
            try:
                if agg == "sum":
                    grouped = self.df.groupby(d_col)[m_col].sum().sort_values(ascending=False)
                else:
                    grouped = self.df.groupby(d_col)[m_col].mean().sort_values(ascending=False)
                total = grouped.sum()
                if total > 0 and len(grouped) >= 3:
                    top3_share = round((grouped.head(3).sum() / total) * 100, 1)
                    top1_name = str(grouped.index[0])
                    top1_share = round((grouped.iloc[0] / total) * 100, 1)
                    top3_names = [str(n) for n in grouped.head(3).index.tolist()]
                    agg_label = "total" if agg == "sum" else "average"
                    risk_level = "high" if top3_share > 70 else ("moderate" if top3_share > 50 else "healthy")

                    raw_text = (
                        f"Top 3 {self._title_case(d_col)} values ({', '.join(top3_names)}) "
                        f"contribute {top3_share}% of {agg_label} {self._title_case(m_col)}. "
                        f"'{top1_name}' alone accounts for {top1_share}%. "
                        f"There are {len(grouped)} distinct {self._title_case(d_col)} categories in total. "
                        f"Concentration level: {risk_level}."
                    )
                    title = f"{self._title_case(m_col)} Concentration by {self._title_case(d_col)}"
                    text = self._enrich_insight_with_llm(raw_text, title)

                    insights.append({
                        "type": "insight",
                        "title": title,
                        "text": text,
                        "highlight": f"{top3_share}% in top 3",
                        "icon": "alert-triangle" if risk_level == "high" else "lightbulb",
                        "gridW": 4, "gridH": 2,
                        "origin_query": f"Concentration analysis of {m_col} by {d_col}",
                        "filter_context": {"column": d_col}
                    })
            except Exception as e:
                logger.debug(f"[_generate_data_insights] Concentration analysis failed: {e}")

        # ── Insight 2: Correlation between measures ──
        if len(measures) >= 2:
            try:
                m1 = measures[0]["col"]
                m2 = measures[1]["col"]
                corr = float(self.df[[m1, m2]].corr().iloc[0, 1])
                if not np.isnan(corr) and abs(corr) > 0.3:
                    direction = "positive" if corr > 0 else "negative"
                    strength = "strong" if abs(corr) > 0.7 else "moderate"
                    m1_mean = float(self.df[m1].mean())
                    m2_mean = float(self.df[m2].mean())

                    raw_text = (
                        f"{self._title_case(m1)} (avg {m1_mean:,.2f}) and {self._title_case(m2)} (avg {m2_mean:,.2f}) "
                        f"have a {strength} {direction} correlation with a Pearson coefficient of r = {corr:.2f}. "
                        f"Correlation measures how closely two variables move together — "
                        f"r = 1.0 means perfect positive, r = -1.0 means perfect negative, and r = 0 means no relationship. "
                    )
                    if corr > 0.7:
                        raw_text += f"Since r = {corr:.2f} is close to 1.0, when {self._title_case(m1)} increases, {self._title_case(m2)} almost always increases too."
                    elif corr < -0.7:
                        raw_text += f"Since r = {corr:.2f} is close to -1.0, when {self._title_case(m1)} increases, {self._title_case(m2)} tends to decrease."
                    else:
                        raw_text += "This moderate relationship warrants monitoring but is not deterministic."

                    title = f"Correlation: {self._title_case(m1)} vs {self._title_case(m2)}"
                    text = self._enrich_insight_with_llm(raw_text, title)

                    insights.append({
                        "type": "insight",
                        "title": title,
                        "text": text,
                        "highlight": f"r = {corr:.2f}",
                        "icon": "activity",
                        "gridW": 4, "gridH": 2,
                        "origin_query": f"Correlation between {m1} and {m2}",
                        "filter_context": {}
                    })
            except Exception as e:
                logger.debug(f"[_generate_data_insights] Correlation analysis failed: {e}")

        # ── Insight 3: Data quality ──
        nulls = dq.get("total_nulls", 0)
        dupes = dq.get("duplicate_rows", 0)
        total_cells = fingerprint.get("row_count", len(self.df)) * fingerprint.get("col_count", len(self.df.columns))
        raw_text = (
            f"Data completeness is {round(completeness * 100, 1)}% — meaning {round((1 - completeness) * 100, 1)}% of cells are empty or null. "
            f"Out of {total_cells:,} total cells, {nulls:,} are null. "
            f"{dupes:,} duplicate rows were detected in the dataset. "
        )
        if completeness >= 0.95:
            raw_text += "This is excellent data quality — analysis results should be highly reliable."
        elif completeness >= 0.80:
            raw_text += "Some data gaps exist — consider data imputation or checking source systems for the missing values before drawing critical conclusions."
        else:
            raw_text += "Significant data gaps — results may be unreliable. Prioritize data collection improvements."

        title = "Data Quality Assessment"
        quality_text = self._enrich_insight_with_llm(raw_text, title)

        insights.append({
            "type": "insight",
            "title": title,
            "text": quality_text,
            "highlight": f"{round(completeness * 100, 1)}% complete",
            "icon": "shield-check" if completeness >= 0.95 else "alert-triangle",
            "gridW": 4, "gridH": 2,
            "origin_query": "Data quality overview",
            "filter_context": {}
        })

        # ── Insight 4: Distribution skewness for measures ──
        for m in measures[:3]:
            col = m["col"]
            try:
                skew = float(self.df[col].skew())
                if abs(skew) > 1.5:
                    direction = "right (positive)" if skew > 0 else "left (negative)"
                    median_val = float(self.df[col].median())
                    mean_val = m.get("mean", 0)
                    diff_pct = round(abs(mean_val - median_val) / max(abs(median_val), 0.01) * 100, 1)

                    raw_text = (
                        f"{self._title_case(col)} has a heavily skewed distribution leaning {direction} (skewness = {skew:.2f}). "
                        f"Skewness measures how lopsided data is — a perfectly symmetric distribution has skewness = 0, "
                        f"while values above 1.5 or below -1.5 indicate strong asymmetry. "
                        f"The median (middle value) is {self._format_kpi_value(median_val, m.get('format_hint', 'number'), 'mean')}, "
                        f"but the mean (average) is {self._format_kpi_value(mean_val, m.get('format_hint', 'number'), 'mean')} — "
                        f"a {diff_pct}% difference. "
                        f"This means a few {'very high' if skew > 0 else 'very low'} values are pulling the average {'up' if skew > 0 else 'down'}. "
                        f"The median is a more representative measure of the typical value in this column."
                    )
                    title = f"{self._title_case(col)} Distribution Skew"
                    text = self._enrich_insight_with_llm(raw_text, title)

                    insights.append({
                        "type": "insight",
                        "title": title,
                        "text": text,
                        "highlight": f"Skew: {skew:.2f}",
                        "icon": "bar-chart-2",
                        "gridW": 4, "gridH": 2,
                        "origin_query": f"Distribution analysis of {col}",
                        "filter_context": {"column": col}
                    })
                    break  # Only one skew insight
            except Exception:
                pass

        return insights

    def _generate_connection_dashboard(self, user_requirements: str | None = None) -> dict:
        """Build a lightweight dashboard from ETL metadata for full-database chat mode."""
        connection_id = getattr(self, "file_uuid", None)
        connection_name = getattr(self, "filename", None) or "Database Connection"
        db_type = "database"
        database_name = None

        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT name, db_type, database_name FROM etl_system.etl_connections WHERE connection_id = %s",
                    (connection_id,),
                )
                connection_row = cur.fetchone()
                if connection_row:
                    connection_name = connection_row[0] or connection_name
                    db_type = connection_row[1] or db_type
                    database_name = connection_row[2]

                cur.execute(
                    """
                    SELECT t.table_name, COALESCE(t.row_count, 0), t.column_stats, t.source_name, t.created_at
                    FROM etl_system.etl_tables t
                    JOIN etl_system.etl_jobs j ON t.job_id = j.job_id
                    WHERE j.connection_id = %s
                    ORDER BY t.created_at DESC
                    """,
                    (connection_id,),
                )
                table_rows = cur.fetchall()

        tables: dict[str, dict[str, Any]] = {}
        for table_name, row_count, column_stats, source_name, created_at in table_rows:
            columns_count = 0
            if isinstance(column_stats, dict):
                columns_value = column_stats.get("columns")
                if isinstance(columns_value, dict):
                    columns_count = len(columns_value)
                elif isinstance(columns_value, list):
                    columns_count = len(columns_value)
            tables[str(table_name)] = {
                "table_name": str(table_name),
                "row_count": int(row_count or 0),
                "column_count": columns_count,
                "source_name": source_name,
                "created_at": str(created_at) if created_at else None,
            }

        table_list = list(tables.values())
        table_count = len(table_list)
        total_rows = sum(item["row_count"] for item in table_list)
        total_columns = sum(item["column_count"] for item in table_list)
        largest_table = max(table_list, key=lambda item: item["row_count"], default=None)
        most_recent_table = table_list[0] if table_list else None

        top_tables = sorted(table_list, key=lambda item: item["row_count"], reverse=True)[:8]
        summary_text = (
            f"{connection_name} is connected as a {db_type} database"
            + (f" ({database_name})" if database_name else "")
            + f" with {table_count} loaded table(s) and {total_rows:,} total rows across the ETL cache."
        )
        if largest_table:
            summary_text += f" The largest table is {largest_table['table_name']} with {largest_table['row_count']:,} rows."
        if user_requirements:
            summary_text += f" Focus hint: {user_requirements.strip()}"

        widgets = [
            {
                "id": "widget-1",
                "type": "summary",
                "title": "Connection Overview",
                "text": summary_text,
                "icon": "database",
                "gridW": 12,
                "gridH": 2,
                "origin_query": "Connection overview",
                "filter_context": {},
            },
            {
                "id": "widget-2",
                "type": "kpi",
                "title": "Loaded Tables",
                "value": f"{table_count:,}",
                "subtitle": f"{db_type} · {database_name or 'default database'}",
                "trend": "neutral",
                "icon": "table-2",
                "gridW": 3,
                "gridH": 2,
                "origin_query": "Table count",
                "filter_context": {},
            },
            {
                "id": "widget-3",
                "type": "kpi",
                "title": "Total Rows",
                "value": f"{total_rows:,}",
                "subtitle": "Across all loaded ETL tables",
                "trend": "neutral",
                "icon": "hash",
                "gridW": 3,
                "gridH": 2,
                "origin_query": "Total rows across database tables",
                "filter_context": {},
            },
            {
                "id": "widget-4",
                "type": "kpi",
                "title": "Total Columns",
                "value": f"{total_columns:,}",
                "subtitle": "Across all loaded ETL tables",
                "trend": "neutral",
                "icon": "columns-3",
                "gridW": 3,
                "gridH": 2,
                "origin_query": "Total column count across database tables",
                "filter_context": {},
            },
        ]

        if largest_table:
            widgets.append(
                {
                    "id": "widget-5",
                    "type": "kpi",
                    "title": "Largest Table",
                    "value": f"{largest_table['row_count']:,}",
                    "subtitle": largest_table["table_name"],
                    "trend": "neutral",
                    "icon": "bar-chart-2",
                    "gridW": 3,
                    "gridH": 2,
                    "origin_query": "Largest loaded table",
                    "filter_context": {},
                }
            )

        if table_count > 0:
            avg_rows = total_rows // table_count if table_count else 0
            widgets.append(
                {
                    "id": f"widget-{len(widgets) + 1}",
                    "type": "kpi",
                    "title": "Avg Rows Per Table",
                    "value": f"{avg_rows:,}",
                    "subtitle": f"Mean across {table_count} tables",
                    "trend": "neutral",
                    "icon": "divide",
                    "gridW": 3,
                    "gridH": 2,
                    "origin_query": "Average rows per table",
                    "filter_context": {},
                }
            )

        if table_list:
            widgets.append(
                {
                    "id": f"widget-{len(widgets) + 1}",
                    "type": "chart",
                    "title": "Rows by Table",
                    "chartType": "bar",
                    "chartData": {
                        "labels": [item["table_name"] for item in top_tables],
                        "series": [{"name": "Rows", "data": [item["row_count"] for item in top_tables]}],
                    },
                    "description": "Loaded row counts for the most recent ETL tables in this connection.",
                    "colorTheme": "indigo",
                    "gridW": 12,
                    "gridH": 3,
                    "origin_query": "Row counts by table",
                    "filter_context": {},
                }
            )

            widgets.append(
                {
                    "id": f"widget-{len(widgets) + 1}",
                    "type": "list",
                    "title": "Top Tables by Rows",
                    "items": [
                        {
                            "label": item["table_name"],
                            "value": f"{item['row_count']:,} rows",
                        }
                        for item in top_tables
                    ],
                    "icon": "layers-3",
                    "gridW": 6,
                    "gridH": 3,
                    "origin_query": "Top tables by row count",
                    "filter_context": {},
                }
            )

            # ── Data Catalog Widget — detailed table × column breakdown ──
            catalog_items = []
            for tbl in table_list[:10]:
                tbl_name = tbl["table_name"]
                col_names = []
                # Try to extract column names from column_stats stored in etl_tables
                for _raw_table_name, _raw_row_count, _raw_col_stats, _raw_source, _raw_created in table_rows:
                    if str(_raw_table_name) == tbl_name and isinstance(_raw_col_stats, dict):
                        cols_val = _raw_col_stats.get("columns")
                        if isinstance(cols_val, dict):
                            col_names = list(cols_val.keys())[:8]
                        elif isinstance(cols_val, list):
                            col_names = [str(c.get("name", c) if isinstance(c, dict) else c) for c in cols_val[:8]]
                        break
                col_preview = ", ".join(col_names[:6]) if col_names else "—"
                if len(col_names) > 6:
                    col_preview += f" (+{len(col_names) - 6} more)"
                catalog_items.append({
                    "label": tbl_name,
                    "value": f"{tbl['row_count']:,} rows · {tbl['column_count']} cols",
                    "sublabel": col_preview,
                })

            if catalog_items:
                widgets.append(
                    {
                        "id": f"widget-{len(widgets) + 1}",
                        "type": "data_catalog",
                        "title": "Data Catalog",
                        "items": catalog_items,
                        "icon": "book-open",
                        "gridW": 6,
                        "gridH": 4,
                        "origin_query": "Data catalog overview",
                        "filter_context": {},
                    }
                )

        # ERD generation
        erd_relations = []
        raw_table_names = [t["table_name"] for t in table_list]
        
        # Strip schemas/quotes for PostgreSQL metadata queries
        parsed_tables = {}
        for raw in raw_table_names:
            clean = raw
            if "." in raw:
                clean = raw.split(".")[-1].strip('"').strip("'")
            parsed_tables[clean] = raw
            
        clean_table_names = list(parsed_tables.keys())

        if clean_table_names:
            try:
                with self.db.get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            SELECT
                                tc.table_name,
                                kcu.column_name,
                                ccu.table_name AS foreign_table_name,
                                ccu.column_name AS foreign_column_name
                            FROM information_schema.table_constraints AS tc
                            JOIN information_schema.key_column_usage AS kcu
                              ON tc.constraint_name = kcu.constraint_name
                              AND tc.table_schema = kcu.table_schema
                            JOIN information_schema.constraint_column_usage AS ccu
                              ON ccu.constraint_name = tc.constraint_name
                              AND ccu.table_schema = tc.table_schema
                            WHERE tc.constraint_type = 'FOREIGN KEY'
                              AND tc.table_name = ANY(%s)
                        """, (clean_table_names,))
                        fks = cur.fetchall()
                        for r in fks:
                            if r[2] in clean_table_names:
                                # Map back to original names for Mermaid
                                orig_table = parsed_tables[r[0]]
                                orig_foreign_table = parsed_tables[r[2]]
                                erd_relations.append((orig_table, r[1], orig_foreign_table, r[3]))
            except Exception:
                pass
            
            # Simple naming fallback if no physical FKs constraints found (e.g. system db doesn't enforce)
            if not erd_relations:
                # Naive matching based on clean table names
                for c1 in clean_table_names:
                    for c2 in clean_table_names:
                        if c1 == c2:
                            continue
                        if c1.endswith(f"_{c2}") or c1.startswith(f"{c2}_") or f"{c2}_id" in c1:
                            erd_relations.append((parsed_tables[c1], f"{c2}_id", parsed_tables[c2], "id"))

            mermaid_lines = ["erDiagram"]
            for raw_t in raw_table_names:
                safe_name = raw_t.replace('"', '').replace('.', '_')
                mermaid_lines.append(f"    {safe_name} {{}}")
            for f_table, f_col, p_table, p_col in erd_relations:
                f_safe = f_table.replace('"', '').replace('.', '_')
                p_safe = p_table.replace('"', '').replace('.', '_')
                mermaid_lines.append(f"    {p_safe} ||--o{{ {f_safe} : \"{p_col}={f_col}\"")
                
            mermaid_str = "\n".join(mermaid_lines)
            
            widgets.append({
                "id": f"widget-{len(widgets) + 1}",
                "type": "erd",
                "title": "Database ERD Structure",
                "mermaid": mermaid_str,
                "gridW": 12,
                "gridH": 4,
                "origin_query": "ERD diagram generation",
                "filter_context": {}
            })

        widgets = [dict(widget, id=f"widget-{index + 1}") for index, widget in enumerate(widgets)]
        component_details = self._trace_dashboard_components(widgets)

        fingerprint = {
            "mode": "connection",
            "connection_id": connection_id,
            "db_type": db_type,
            "database_name": database_name,
            "table_count": table_count,
            "total_rows": total_rows,
            "total_columns": total_columns,
            "largest_table": largest_table,
            "most_recent_table": most_recent_table,
        }

        _response = self._build_response_envelope(widgets, fingerprint)
        _response["cache_hit"] = False

        self._last_dashboard_trace_info = {
            "status": "success",
            "mode": "connection",
            "table_count": table_count,
            "total_rows": total_rows,
            "component_titles": [c.get("title", "Untitled") for c in component_details],
        }

        langfuse_context.update_current_observation(
            output={
                "status": "success",
                "mode": "connection",
                "table_count": table_count,
                "total_rows": total_rows,
                "widget_count": len(widgets),
            }
        )
        return _response

    @staticmethod
    def _format_kpi_title(m: dict) -> str:
        """Generate a clear, descriptive KPI title from a measure dict.
        Returns full human-readable title — truncation handled by frontend CSS."""
        col = m.get("col", "")
        agg = m.get("agg", "sum")
        col_title = col.replace('_', ' ').replace('-', ' ').title()
        col_lower = col_title.lower()
        if agg == "sum":
            # Avoid "Total Total Applications" when column already starts with "Total"
            if col_lower.startswith("total"):
                return col_title
            return f"Total {col_title}"
        elif agg == "mean":
            if col_lower.startswith("average") or col_lower.startswith("avg"):
                return col_title
            return f"Average {col_title}"
        elif agg == "count":
            if col_lower.endswith("count"):
                return col_title
            return f"{col_title} Count"
        return col_title

    def _format_list_value(self, val: float, format_hint: str = "number") -> str:
        """Format a value for display inside a list item — full numbers, no abbreviation."""
        if format_hint == "currency":
            if abs(val) >= 1e6:
                return f"₹{val:,.0f}"
            return f"₹{val:,.2f}"
        if format_hint == "percentage":
            return f"{val:.1f}%"
        if val == int(val) and abs(val) < 1e12:
            return f"{int(val):,}"
        if abs(val) >= 1e6:
            return f"{val:,.0f}"
        return f"{val:,.1f}"

    @staticmethod
    def _build_dashboard_component_detail(widget: dict) -> dict:
        """Flatten one widget into a trace-friendly component record."""
        def _strip_none(v):
            if isinstance(v, dict):
                return {k: _strip_none(x) for k, x in v.items() if x is not None}
            if isinstance(v, list):
                return [_strip_none(x) for x in v if x is not None]
            return v

        w_type = widget.get("type", "unknown")
        detail = {
            "id": widget.get("id"),
            "type": w_type,
            "title": widget.get("title"),
            "grid": {
                "w": widget.get("gridW"),
                "h": widget.get("gridH"),
            },
            "origin_query": widget.get("origin_query"),
            "filter_context": widget.get("filter_context", {}),
        }

        if w_type == "summary":
            detail["content"] = {
                "text": widget.get("text"),
            }
        elif w_type == "kpi":
            detail["content"] = {
                "value": widget.get("value"),
                "subtitle": widget.get("subtitle"),
                "trend": widget.get("trend"),
                "icon": widget.get("icon"),
            }
        elif w_type == "list":
            detail["content"] = {
                "items": widget.get("items", []),
                "item_count": len(widget.get("items", [])),
                "icon": widget.get("icon"),
            }
        elif w_type == "insight":
            detail["content"] = {
                "text": widget.get("text"),
                "highlight": widget.get("highlight"),
                "icon": widget.get("icon"),
            }
        elif w_type == "erd":
            detail["content"] = {
                "mermaid_preview": (widget.get("mermaid") or "")[:500],
                "has_mermaid": bool(widget.get("mermaid")),
            }
        elif w_type == "data_catalog":
            detail["content"] = {
                "items": widget.get("items", []),
                "item_count": len(widget.get("items", [])),
                "icon": widget.get("icon"),
            }
        elif w_type == "chart":
            chart_data = widget.get("chartData", {}) if isinstance(widget.get("chartData"), dict) else {}
            labels = chart_data.get("labels", []) if isinstance(chart_data.get("labels"), list) else []
            series = chart_data.get("series", [])
            detail["content"] = {
                "chart_type": widget.get("chartType"),
                "description": widget.get("description"),
                "horizontal": bool(widget.get("horizontal", False)),
                "color_theme": widget.get("colorTheme"),
                "labels": labels,
                "series": series,
                "label_count": len(labels),
            }
        else:
            detail["content"] = widget

        return _strip_none(detail)

    @observe(name="dashboard.components", as_type="span")
    def _trace_dashboard_components(self, widgets: list) -> list:
        """Record detailed component payloads as a child dashboard span."""
        components = [self._build_dashboard_component_detail(w) for w in widgets if isinstance(w, dict)]
        langfuse_context.update_current_observation(
            input={
                "component_count": len(components),
                "component_types": [c.get("type", "?") for c in components],
            },
            metadata={
                "file_uuid": self.file_uuid,
                "filename": self.filename,
            },
            output={
                "components": components,
            },
            tags=["dashboard", "components"],
        )
        return components

    @staticmethod
    def _strip_trace_none(v):
        if isinstance(v, dict):
            return {k: DashboardMixin._strip_trace_none(x) for k, x in v.items() if x is not None}
        if isinstance(v, list):
            return [DashboardMixin._strip_trace_none(x) for x in v if x is not None]
        return v

    @staticmethod
    def _widget_type_counts(widgets: list) -> dict:
        types = [w.get("type", "unknown") for w in widgets if isinstance(w, dict)]
        return {
            "total": len(types),
            "summary": sum(1 for t in types if t == "summary"),
            "kpi": sum(1 for t in types if t == "kpi"),
            "list": sum(1 for t in types if t == "list"),
            "insight": sum(1 for t in types if t == "insight"),
            "chart": sum(1 for t in types if t == "chart"),
            "other": sum(1 for t in types if t not in {"summary", "kpi", "list", "insight", "chart"}),
        }

    @staticmethod
    def _detect_compare_left_out(widgets: list, mode: str) -> list:
        """Detect where compare data is missing/partial so traces explain what got left out."""
        left_out: list = []
        for w in widgets:
            if not isinstance(w, dict):
                continue
            w_type = w.get("type", "unknown")
            title = w.get("title", "Untitled")
            wid = w.get("id")

            if w_type == "kpi":
                compare_value = w.get("compare_value")
                if mode == "unified" and compare_value in (None, "N/A", "—"):
                    left_out.append({
                        "widget_id": wid,
                        "widget_type": w_type,
                        "title": title,
                        "reason": "compare_value_unavailable",
                    })
                subtitle = str(w.get("subtitle", "")).lower()
                if "no matching" in subtitle:
                    left_out.append({
                        "widget_id": wid,
                        "widget_type": w_type,
                        "title": title,
                        "reason": "matching_metric_not_found",
                    })

            elif w_type == "list":
                items = w.get("items", []) if isinstance(w.get("items"), list) else []
                if not items:
                    left_out.append({
                        "widget_id": wid,
                        "widget_type": w_type,
                        "title": title,
                        "reason": "list_items_empty",
                    })
                elif mode == "unified":
                    missing_compare = sum(1 for item in items if isinstance(item, dict) and item.get("compare_value") in (None, "—", "N/A"))
                    if missing_compare > 0:
                        left_out.append({
                            "widget_id": wid,
                            "widget_type": w_type,
                            "title": title,
                            "reason": "compare_values_missing_for_some_items",
                            "missing_compare_items": missing_compare,
                            "total_items": len(items),
                        })

            elif w_type == "chart":
                chart_data = w.get("chartData", {}) if isinstance(w.get("chartData"), dict) else {}
                labels = chart_data.get("labels", []) if isinstance(chart_data.get("labels"), list) else []
                series = chart_data.get("series", []) if isinstance(chart_data.get("series"), list) else []
                if len(labels) == 0:
                    left_out.append({
                        "widget_id": wid,
                        "widget_type": w_type,
                        "title": title,
                        "reason": "chart_labels_empty",
                    })
                if mode == "unified" and len(series) < 2:
                    left_out.append({
                        "widget_id": wid,
                        "widget_type": w_type,
                        "title": title,
                        "reason": "compare_series_missing",
                        "series_count": len(series),
                    })

            elif w_type == "insight":
                text = str(w.get("text", "")).lower()
                if "could not generate" in text or "no matching insight" in text:
                    left_out.append({
                        "widget_id": wid,
                        "widget_type": w_type,
                        "title": title,
                        "reason": "insight_fallback_used",
                    })

        return DashboardMixin._strip_trace_none(left_out)

    @observe(name="dashboard.compare_split.components", as_type="span")
    def _trace_compare_split_components(self, base_widgets: list, cloned_widgets: list, diagnostics: dict | None = None) -> dict:
        """Trace split compare components for both files, plus what was left out."""
        base_components = [self._build_dashboard_component_detail(w) for w in base_widgets if isinstance(w, dict)]
        cloned_components = [self._build_dashboard_component_detail(w) for w in cloned_widgets if isinstance(w, dict)]
        base_ids = {str(c.get("id")) for c in base_components if c.get("id") is not None}
        cloned_ids = {str(c.get("id")) for c in cloned_components if c.get("id") is not None}
        left_out = (diagnostics or {}).get("left_out", [])

        payload = self._strip_trace_none({
            "mode": "split",
            "counts": {
                "base": self._widget_type_counts(base_widgets),
                "compare": self._widget_type_counts(cloned_widgets),
            },
            "coverage": {
                "base_count": len(base_components),
                "compare_count": len(cloned_components),
                "mapped_by_id": len(base_ids & cloned_ids),
                "missing_on_compare": sorted(list(base_ids - cloned_ids)),
                "extra_on_compare": sorted(list(cloned_ids - base_ids)),
                "left_out_count": len(left_out),
            },
            "left_out": left_out,
            "base_components": base_components,
            "compare_components": cloned_components,
            "diagnostics": diagnostics or {},
        })

        langfuse_context.update_current_observation(
            input={
                "mode": "split",
                "base_widget_count": len(base_components),
                "compare_widget_count": len(cloned_components),
            },
            metadata={
                "file_uuid": self.file_uuid,
                "filename": self.filename,
            },
            output=payload,
            tags=["dashboard", "compare", "split", "components"],
        )
        return payload

    @observe(name="dashboard.compare_unified.components", as_type="span")
    def _trace_compare_unified_components(self, base_widgets: list, unified_widgets: list, diagnostics: dict | None = None) -> dict:
        """Trace unified compare components plus left-out/partial-compare information."""
        base_components = [self._build_dashboard_component_detail(w) for w in base_widgets if isinstance(w, dict)]
        unified_components = [self._build_dashboard_component_detail(w) for w in unified_widgets if isinstance(w, dict)]
        base_ids = {str(c.get("id")) for c in base_components if c.get("id") is not None}
        unified_ids = {str(c.get("id")) for c in unified_components if c.get("id") is not None}
        left_out = (diagnostics or {}).get("left_out", [])

        payload = self._strip_trace_none({
            "mode": "unified",
            "counts": {
                "base": self._widget_type_counts(base_widgets),
                "unified": self._widget_type_counts(unified_widgets),
            },
            "coverage": {
                "base_count": len(base_components),
                "unified_count": len(unified_components),
                "mapped_by_id": len(base_ids & unified_ids),
                "missing_in_unified": sorted(list(base_ids - unified_ids)),
                "extra_in_unified": sorted(list(unified_ids - base_ids)),
                "left_out_count": len(left_out),
            },
            "left_out": left_out,
            "base_components": base_components,
            "unified_components": unified_components,
            "diagnostics": diagnostics or {},
        })

        langfuse_context.update_current_observation(
            input={
                "mode": "unified",
                "base_widget_count": len(base_components),
                "unified_widget_count": len(unified_components),
            },
            metadata={
                "file_uuid": self.file_uuid,
                "filename": self.filename,
            },
            output=payload,
            tags=["dashboard", "compare", "unified", "components"],
        )
        return payload

    @observe(name="dashboard.build", as_type="span")
    def generate_kpi_dashboard(self, user_requirements: str | None = None) -> dict:
        """
        Analyze the loaded DataFrame and generate a full KPI dashboard layout.
        Uses purely DATA-DRIVEN computation for accurate, consistent values.
        All widget values are computed from pandas — LLM is only used for the
        executive summary narrative text.

        user_requirements: optional free-text hint from the user, e.g.:
          "consider Salary as key metric, ignore Mobile Number, focus on Region"
          Parsed WITHOUT an LLM — pure string matching.
        
        Widget count scales dynamically:
          - Small files (≤10 cols): 7-8 widgets
          - Medium files (11-20 cols): 10-12 widgets
          - Large files (>20 cols): 15-16 widgets
        """
        import time

        if getattr(self, "_sql_connection_mode", False):
            return self._generate_connection_dashboard(user_requirements=user_requirements)

        def _strip_none(v):
            if isinstance(v, dict):
                return {k: _strip_none(x) for k, x in v.items() if x is not None}
            if isinstance(v, list):
                return [_strip_none(x) for x in v if x is not None]
            return v

        _t0 = time.perf_counter()
        _stage_t = {"start": _t0}
        try:
            logger.info("📊 Generating KPI dashboard (data-driven, no LLM for values)...")
            langfuse_context.update_current_observation(
                input={
                    "file_uuid": self.file_uuid,
                    "filename": self.filename,
                    "user_requirements": user_requirements,
                },
                metadata={
                    "data_shape": {
                        "rows": len(self.df) if self.df is not None else 0,
                        "columns": len(self.df.columns) if self.df is not None else 0,
                    }
                },
                tags=["dashboard", "build"],
            )

            # Parse user requirements into column hints (no LLM call)
            user_hints = self._parse_user_requirements(user_requirements) if user_requirements else None
            if user_hints:
                logger.info(f"[📊 Dashboard] User requirements parsed: {user_hints}")
            
            # ── STEP 1: Build File Fingerprint (Data Model) ──
            fingerprint = self._build_file_fingerprint(user_hints=user_hints)
            _stage_t["fingerprint_done"] = time.perf_counter()
            measures = fingerprint["measures"]
            dims = fingerprint["dimensions"]
            ti = fingerprint.get("time_intelligence", {})
            dq = fingerprint.get("data_quality", {})
            completeness = dq.get("completeness", 1.0)
            row_count = len(self.df)
            col_count = len(self.df.columns)

            logger.info(f"[generate_kpi_dashboard] 🧬 Fingerprint: {len(measures)} measures, "
                         f"{len(dims)} dimensions, {len(fingerprint['time_columns'])} time cols")

            # ── STEP 2: Determine dynamic widget limits based on data complexity ──
            n_measures = len(measures)
            n_dims = len(dims)

            if col_count <= 10:
                max_kpis = min(n_measures, 8)
                max_lists = min(n_dims, 5)
                max_insights = 4
                max_charts = 8
            elif col_count <= 20:
                max_kpis = min(n_measures, 12)
                max_lists = min(n_dims, 8)
                max_insights = 6
                max_charts = 12
            else:
                max_kpis = min(n_measures, 16)
                max_lists = min(n_dims, 12)
                max_insights = 8
                max_charts = 16

            logger.info(f"[generate_kpi_dashboard] 📐 Dynamic limits: kpis={max_kpis}, lists={max_lists}, "
                         f"insights={max_insights}, charts={max_charts} (cols={col_count})")

            widgets = []

            # ── STEP 3: Executive Summary (LLM narrative with pre-computed values) ──
            summary_text = self._generate_executive_summary(fingerprint)
            _stage_t["summary_done"] = time.perf_counter()
            widgets.append({
                "id": "widget-0", "type": "summary",
                "title": "Executive Summary",
                "text": summary_text,
                "icon": "file-text", "gridW": 12, "gridH": 2,
                "origin_query": "Executive summary overview",
                "filter_context": {}
            })

            # ── STEP 4: KPIs from measures (computed from actual data) ──
            for i, m in enumerate(measures[:max_kpis]):
                col = m["col"]
                agg = m.get("agg", "sum")
                # Compute value from actual DataFrame for precision
                if agg == "sum":
                    val = float(self.df[col].sum())
                else:
                    val = float(self.df[col].mean())
                display = self._format_kpi_value(val, m.get("format_hint", "number"), agg)
                subtitle = self._format_kpi_subtitle(m)

                trend = "neutral"
                if i == 0 and ti.get("mom_growth") is not None:
                    trend = "positive" if ti["mom_growth"] > 0 else "negative"

                icon = self._pick_kpi_icon(m)

                widgets.append({
                    "id": f"widget-{len(widgets)}", "type": "kpi",
                    "title": self._format_kpi_title(m),
                    "value": display,
                    "subtitle": subtitle,
                    "trend": trend,
                    "icon": icon,
                    "gridW": 3, "gridH": 2,
                    "origin_query": f"{agg} of {col}",
                    "filter_context": {"column": col, "agg": agg}
                })

            # ── STEP 4b: Record Count KPI (always useful) ──
            widgets.append({
                "id": f"widget-{len(widgets)}", "type": "kpi",
                "title": "Total Records",
                "value": f"{row_count:,}",
                "subtitle": f"Across {col_count} columns",
                "trend": "neutral",
                "icon": "hash",
                "gridW": 3, "gridH": 2,
                "origin_query": "Total record count",
                "filter_context": {}
            })

            # ── STEP 4c: MoM Growth KPI ──
            if ti.get("mom_growth") is not None:
                widgets.append({
                    "id": f"widget-{len(widgets)}", "type": "kpi",
                    "title": "Month-over-Month Growth",
                    "value": f"{ti['mom_growth']:+.1f}%",
                    "subtitle": f"{self._title_case(ti.get('mom_measure', ''))} ({ti.get('latest_period', '')})",
                    "trend": "positive" if ti["mom_growth"] > 0 else "negative",
                    "icon": "trending-up" if ti["mom_growth"] > 0 else "trending-down",
                    "gridW": 3, "gridH": 2,
                    "origin_query": "Month-over-month growth",
                    "filter_context": {}
                })

            # ── STEP 5: Lists — each tied to ONE specific dim × measure × agg ──
            # Ensures NO contradictions: each list has a unique, clear title and
            # values computed from the same pandas groupby operation.
            used_combos = set()  # Track (dim, measure) to avoid duplicates
            list_count = 0

            for dim in dims:
                if list_count >= max_lists:
                    break
                for meas in measures[:3]:  # Try top 3 measures per dimension
                    if list_count >= max_lists:
                        break
                    combo_key = (dim["col"], meas["col"])
                    if combo_key in used_combos:
                        continue
                    used_combos.add(combo_key)

                    d_col = dim["col"]
                    m_col = meas["col"]
                    agg = meas.get("agg", "sum")

                    try:
                        # Compute from actual data
                        if agg == "sum":
                            grouped = self.df.groupby(d_col)[m_col].sum()
                        else:
                            grouped = self.df.groupby(d_col)[m_col].mean()

                        top5 = grouped.sort_values(ascending=False).head(5)
                        if len(top5) < 2:
                            continue

                        fmt_hint = meas.get("format_hint", "number")
                        items = []
                        for k, v in top5.items():
                            items.append({
                                "label": str(k),
                                "value": self._format_list_value(float(v), fmt_hint)
                            })

                        agg_label = "Total" if agg == "sum" else "Avg"
                        m_title = self._title_case(m_col)
                        # Avoid "Total Total Applications" duplication
                        if agg_label == "Total" and m_title.lower().startswith("total"):
                            title = f"Top {self._title_case(d_col)} by {m_title}"
                        elif agg_label == "Avg" and (m_title.lower().startswith("average") or m_title.lower().startswith("avg")):
                            title = f"Top {self._title_case(d_col)} by {m_title}"
                        else:
                            title = f"Top {self._title_case(d_col)} by {agg_label} {m_title}"

                        widgets.append({
                            "id": f"widget-{len(widgets)}", "type": "list",
                            "title": title,
                            "items": items,
                            "icon": "trophy",
                            "gridW": 4, "gridH": 3,
                            "origin_query": f"Top {d_col} by {agg} of {m_col}",
                            "filter_context": {"column": d_col, "measure": m_col, "agg": agg}
                        })
                        list_count += 1
                    except Exception as e:
                        logger.debug(f"[generate_kpi_dashboard] List generation failed for {d_col}×{m_col}: {e}")
            _stage_t["kpis_lists_done"] = time.perf_counter()

            # ── STEP 5b: Count-based lists for dimensions without measures ──
            for dim in dims:
                if list_count >= max_lists:
                    break
                d_col = dim["col"]
                # Skip if we already have a list for this dimension
                if any(d_col == c[0] for c in used_combos):
                    continue
                try:
                    counts = self.df[d_col].value_counts().head(5)
                    if len(counts) < 2:
                        continue
                    items = [{"label": str(k), "value": f"{int(v):,}"} for k, v in counts.items()]
                    title = f"Top {self._title_case(d_col)} by Count"
                    widgets.append({
                        "id": f"widget-{len(widgets)}", "type": "list",
                        "title": title,
                        "items": items,
                        "icon": "bar-chart-3",
                        "gridW": 4, "gridH": 3,
                        "origin_query": f"Top {d_col} by count",
                        "filter_context": {"column": d_col}
                    })
                    list_count += 1
                except Exception:
                    pass

            # ── STEP 6: Data-driven insights (computed from actual data) ──
            insight_widgets = self._generate_data_insights(fingerprint)
            for iw in insight_widgets[:max_insights]:
                iw["id"] = f"widget-{len(widgets)}"
                widgets.append(iw)
            _stage_t["insights_done"] = time.perf_counter()

            # ── STEP 7: Charts with descriptions (data-driven) ──
            try:
                chart_widgets = self._generate_dashboard_charts(fingerprint)
                for cw in chart_widgets[:max_charts]:
                    cw['id'] = f"widget-{len(widgets)}"
                    widgets.append(cw)
                logger.info(f"[generate_kpi_dashboard] 📈 Generated {min(len(chart_widgets), max_charts)} chart widgets")
            except Exception as ce:
                logger.warning(f"[generate_kpi_dashboard] Chart auto-generation failed: {ce}")
            _stage_t["charts_done"] = time.perf_counter()

            # ── Re-number all widget IDs cleanly ──
            for idx, w in enumerate(widgets):
                w['id'] = f"widget-{idx+1}"

            component_details = self._trace_dashboard_components(widgets)

            logger.info(f"[generate_kpi_dashboard] ✅ Total widgets: {len(widgets)} "
                         f"(kpis={sum(1 for w in widgets if w['type']=='kpi')}, "
                         f"lists={sum(1 for w in widgets if w['type']=='list')}, "
                         f"insights={sum(1 for w in widgets if w['type']=='insight')}, "
                         f"charts={sum(1 for w in widgets if w['type']=='chart')})")

            # Build fingerprint for the frontend (expanded limits)
            fp_for_client = {
                "measures": [{"col": m["col"], "agg": m["agg"], "format_hint": m["format_hint"]}
                             for m in measures[:12]],
                "dimensions": [{"col": d["col"], "cardinality": d["cardinality"], "dim_type": d["dim_type"],
                                "top_values": d["top_values"]}
                               for d in dims[:10]],
                "time_intelligence": ti,
                "data_quality": dq,
            }

            final_response = self._build_response_envelope(widgets, fp_for_client)

            # Save dashboard to database for persistence (include fingerprint)
            self.save_dashboard(widgets, fp_for_client)

            _elapsed_ms = round((time.perf_counter() - _t0) * 1000, 2)
            _phase_ms = {
                "fingerprint_ms": round((_stage_t.get("fingerprint_done", _t0) - _t0) * 1000, 2),
                "summary_ms": round((_stage_t.get("summary_done", _stage_t.get("fingerprint_done", _t0)) - _stage_t.get("fingerprint_done", _t0)) * 1000, 2),
                "kpis_lists_ms": round((_stage_t.get("kpis_lists_done", _stage_t.get("summary_done", _t0)) - _stage_t.get("summary_done", _t0)) * 1000, 2),
                "insights_ms": round((_stage_t.get("insights_done", _stage_t.get("kpis_lists_done", _t0)) - _stage_t.get("kpis_lists_done", _t0)) * 1000, 2),
                "charts_ms": round((_stage_t.get("charts_done", _stage_t.get("insights_done", _t0)) - _stage_t.get("insights_done", _t0)) * 1000, 2),
            }

            _llm_summary = {
                "executive_summary_llm": True,
                "insight_enrichment_llm": True,
                "langfuse_callbacks_available": bool(_LANGFUSE_CALLBACK_AVAILABLE),
            }

            self._last_dashboard_trace_info = _strip_none({
                "status": "success",
                "elapsed_ms": _elapsed_ms,
                "phase_timings_ms": _phase_ms,
                "fingerprint": {
                    "measure_count": len(measures),
                    "dimension_count": len(dims),
                    "time_column_count": len(fingerprint.get("time_columns", [])),
                    "primary_date": ti.get("primary_date"),
                    "suggested_grain": ti.get("suggested_grain"),
                    "mom_growth": ti.get("mom_growth"),
                    "yoy_growth": ti.get("yoy_growth"),
                },
                "limits": {
                    "max_kpis": max_kpis,
                    "max_lists": max_lists,
                    "max_insights": max_insights,
                    "max_charts": max_charts,
                },
                "widget_counts": {
                    "total": len(widgets),
                    "kpi": sum(1 for w in widgets if w.get("type") == "kpi"),
                    "list": sum(1 for w in widgets if w.get("type") == "list"),
                    "insight": sum(1 for w in widgets if w.get("type") == "insight"),
                    "chart": sum(1 for w in widgets if w.get("type") == "chart"),
                    "summary": sum(1 for w in widgets if w.get("type") == "summary"),
                },
                "component_titles": [c.get("title", "Untitled") for c in component_details],
                "component_types": [c.get("type", "unknown") for c in component_details],
                "llm": _llm_summary,
                "user_hints": user_hints or {},
            })

            langfuse_context.update_current_observation(
                output=_strip_none({
                    "status": "success",
                    "elapsed_ms": _elapsed_ms,
                    "phase_timings_ms": _phase_ms,
                    "widget_count": len(widgets),
                    "widget_types": [w.get("type", "?") for w in widgets],
                    "fingerprint_counts": {
                        "measures": len(measures),
                        "dimensions": len(dims),
                        "time_columns": len(fingerprint.get("time_columns", [])),
                    },
                    "llm": _llm_summary,
                })
            )

            return final_response

        except Exception as e:
            self._last_dashboard_trace_info = {
                "status": "error",
                "error": str(e)[:400],
            }
            langfuse_context.update_current_observation(
                output={"status": "error", "error": str(e)[:400]}
            )
            log_full_exception(e, "Dashboard generation error")
            return {
                "status": "error",
                "message": f"Dashboard generation failed: {str(e)}",
                "widgets": [],
                "fingerprint": {},
                "total_rows": len(self.df) if self.df is not None else 0,
            }

    def _generate_dashboard_charts(self, fingerprint: dict = None) -> list:
        """
        Auto-generate interactive chart widgets using the semantic fingerprint.
        If no fingerprint is provided, builds one first.
        Returns chart widgets with labels + series + description + origin_query + filter_context.
        Dynamically generates more charts for larger datasets.
        """
        charts = []
        try:
            # Always use fingerprint — build one if not supplied
            if not fingerprint or not fingerprint.get("dimensions") or not fingerprint.get("measures"):
                fingerprint = self._build_file_fingerprint()

            dims = fingerprint["dimensions"]
            measures = fingerprint["measures"]
            ti = fingerprint.get("time_intelligence", {})
            col_count = fingerprint.get("col_count", len(self.df.columns))

            if not dims and not measures:
                logger.info("[_generate_dashboard_charts] No dims or measures in fingerprint — skipping")
                return charts

            # Track which dim×measure combos have been charted to avoid duplicates
            charted_combos = set()

            # ── 1. BAR CHART: Top dimension by count ──
            if dims:
                col = dims[0]["col"]
                all_counts = self.df[col].value_counts()  # full sorted list
                counts = all_counts.head(50)              # cap at 50 for payload size
                col_label = self._title_case(col)
                total = int(counts.sum())
                top_name = str(counts.index[0])
                top_pct = round((int(counts.iloc[0]) / max(total, 1)) * 100, 1)
                charts.append({
                    "type": "chart", "chartType": "bar",
                    "title": f"{col_label} Distribution",
                    "description": f"Shows the count distribution across {col_label} values. '{top_name}' leads with {top_pct}% of records.",
                    "chartData": {
                        "labels": [str(k) for k in counts.index.tolist()],
                        "series": [{"name": f"{col_label} Count", "data": [int(v) for v in counts.values.tolist()]}]
                    },
                    "colorTheme": "indigo", "gridW": 6, "gridH": 3,
                    "origin_query": f"Distribution of {col_label}",
                    "filter_context": {"column": col, "type": "dimension"}
                })
                charted_combos.add((col, "__count__"))

            # ── 2. DONUT/PIE: Second dimension or fallback ──
            pie_dim = dims[1] if len(dims) >= 2 else (dims[0] if dims else None)
            if pie_dim:
                col = pie_dim["col"]
                if (col, "__count__") not in charted_combos:
                    card = pie_dim.get("cardinality", self.df[col].nunique())
                    all_counts_pie = self.df[col].value_counts()
                    counts = all_counts_pie.head(15)  # pie/donut: cap at 15 slices
                    col_label = self._title_case(col)
                    chart_type = "pie" if card <= 6 else "donut"
                    top_name = str(counts.index[0]) if len(counts) > 0 else "N/A"
                    charts.append({
                        "type": "chart", "chartType": chart_type,
                        "title": f"{col_label} Breakdown",
                        "description": f"Proportional breakdown of records by {col_label}. '{top_name}' is the largest segment.",
                        "chartData": {
                            "labels": [str(k) for k in counts.index.tolist()],
                            "series": [{"name": f"{col_label} Count", "data": [int(v) for v in counts.values.tolist()]}]
                        },
                        "colorTheme": "violet", "gridW": 6, "gridH": 3,
                        "origin_query": f"Breakdown by {col_label}",
                        "filter_context": {"column": col, "type": "dimension"}
                    })
                    charted_combos.add((col, "__count__"))

            # ── 3. AREA CHART: Top measure by top dimension ──
            if measures and dims:
                m_col = measures[0]["col"]
                d_col = dims[0]["col"]
                agg = measures[0].get("agg", "sum")
                agg_fn = self.df.groupby(d_col)[m_col].sum() if agg == 'sum' else self.df.groupby(d_col)[m_col].mean()
                all_grouped_area = agg_fn.sort_values(ascending=False)
                grouped = all_grouped_area.head(50)  # full data capped at 50
                m_label = self._title_case(m_col)
                d_label = self._title_case(d_col)
                agg_label = "Total" if agg == "sum" else "Average"
                if len(grouped) >= 3:
                    top_val = self._format_list_value(float(grouped.iloc[0]), measures[0].get("format_hint", "number"))
                    charts.append({
                        "type": "chart", "chartType": "area",
                        "title": f"{agg_label} {m_label} by {d_label}",
                        "description": f"{agg_label} {m_label} across {d_label} categories. Highest: '{str(grouped.index[0])}' at {top_val}.",
                        "chartData": {
                            "labels": [str(k) for k in grouped.index.tolist()],
                            "series": [{"name": f"{agg_label} {m_label}", "data": [round(float(v), 2) for v in grouped.values.tolist()]}]
                        },
                        "colorTheme": "emerald", "gridW": 8, "gridH": 3,
                        "origin_query": f"{agg} of {m_label} grouped by {d_label}",
                        "filter_context": {"column": d_col, "measure": m_col, "agg": agg}
                    })
                    charted_combos.add((d_col, m_col))

            # ── 4. HORIZONTAL BAR: Top N by second measure ──
            if len(measures) >= 2 and dims:
                m_col = measures[1]["col"]
                d_col = dims[0]["col"]
                agg = measures[1].get("agg", "sum")
                try:
                    if agg == "sum":
                        all_grouped_hbar = self.df.groupby(d_col)[m_col].sum().sort_values(ascending=False)
                    else:
                        all_grouped_hbar = self.df.groupby(d_col)[m_col].mean().sort_values(ascending=False)
                    grouped = all_grouped_hbar.head(50)  # full data capped at 50
                    m_label = self._title_case(m_col)
                    d_label = self._title_case(d_col)
                    agg_label = "Total" if agg == "sum" else "Avg"
                    if len(grouped) >= 3 and (d_col, m_col) not in charted_combos:
                        charts.append({
                            "type": "chart", "chartType": "bar",
                            "title": f"Top {d_label} by {agg_label} {m_label}",
                            "description": f"Ranks {d_label} by {agg_label.lower()} {m_label}. Best performer: '{str(grouped.index[0])}'.",
                            "chartData": {
                                "labels": [str(v) for v in grouped.index.tolist()],
                                "series": [{"name": f"{agg_label} {m_label}", "data": [round(float(v), 2) for v in grouped.values.tolist()]}]
                            },
                            "horizontal": True,
                            "colorTheme": "amber", "gridW": 4, "gridH": 3,
                            "origin_query": f"Top {d_label} by {agg} of {m_label}",
                            "filter_context": {"column": d_col, "measure": m_col}
                        })
                        charted_combos.add((d_col, m_col))
                except Exception:
                    pass

            # ── 5. TIME SERIES: Trend line using primary date ──
            if ti.get("primary_date") and measures:
                date_col = ti["primary_date"]
                m_col = measures[0]["col"]
                m_label = self._title_case(m_col)
                grain = ti.get("suggested_grain", "M")
                if isinstance(grain, str):
                    _g = grain.upper()
                    if _g == "M":
                        grain = "ME"
                    elif _g == "Y":
                        grain = "YE"
                agg = measures[0].get("agg", "sum")
                try:
                    if agg == "sum":
                        ts = self.df.set_index(date_col)[m_col].resample(grain).sum().dropna().tail(24)
                    else:
                        ts = self.df.set_index(date_col)[m_col].resample(grain).mean().dropna().tail(24)
                    if len(ts) >= 3:
                        trend_dir = "upward" if float(ts.iloc[-1]) > float(ts.iloc[0]) else "downward"
                        charts.append({
                            "type": "chart", "chartType": "line",
                            "title": f"{m_label} Trend Over Time",
                            "description": f"Shows {m_label} trend over time ({grain} grain). Overall {trend_dir} trajectory.",
                            "chartData": {
                                "labels": [d.strftime('%Y-%m') for d in ts.index.tolist()],
                                "series": [{"name": m_label, "data": [round(float(v), 2) for v in ts.values.tolist()]}]
                            },
                            "colorTheme": "rose", "gridW": 12, "gridH": 3,
                            "origin_query": f"Time trend of {m_label}",
                            "filter_context": {"column": date_col, "measure": m_col, "type": "time_series"}
                        })
                except Exception:
                    pass

            # ── 6+ EXTRA CHARTS for large datasets ──
            # Generate additional dim×measure charts for columns not yet covered
            if col_count > 10:
                color_rotation = ["cyan", "rose", "amber", "emerald", "violet", "indigo"]
                extra_idx = 0

                for d in dims[1:]:  # Skip first dim (already used)
                    for m in measures[:3]:
                        combo = (d["col"], m["col"])
                        if combo in charted_combos:
                            continue
                        d_col = d["col"]
                        m_col = m["col"]
                        agg = m.get("agg", "sum")
                        try:
                            if agg == "sum":
                                all_grouped_extra = self.df.groupby(d_col)[m_col].sum().sort_values(ascending=False)
                            else:
                                all_grouped_extra = self.df.groupby(d_col)[m_col].mean().sort_values(ascending=False)
                            grouped = all_grouped_extra.head(50)  # full data capped at 50
                            if len(grouped) < 3:
                                continue
                            m_label = self._title_case(m_col)
                            d_label = self._title_case(d_col)
                            agg_label = "Total" if agg == "sum" else "Avg"
                            # Alternate between bar and area
                            ct = "bar" if extra_idx % 2 == 0 else "area"
                            color = color_rotation[extra_idx % len(color_rotation)]
                            charts.append({
                                "type": "chart", "chartType": ct,
                                "title": f"{agg_label} {m_label} by {d_label}",
                                "description": f"{agg_label} {m_label} broken down by {d_label}. Top: '{str(grouped.index[0])}'.",
                                "chartData": {
                                    "labels": [str(k) for k in grouped.index.tolist()],
                                    "series": [{"name": f"{agg_label} {m_label}", "data": [round(float(v), 2) for v in grouped.values.tolist()]}]
                                },
                                "colorTheme": color, "gridW": 6, "gridH": 3,
                                "origin_query": f"{agg} of {m_label} grouped by {d_label}",
                                "filter_context": {"column": d_col, "measure": m_col, "agg": agg}
                            })
                            charted_combos.add(combo)
                            extra_idx += 1
                        except Exception:
                            pass
                        if extra_idx >= 6:  # Cap extra charts
                            break
                    if extra_idx >= 6:
                        break

                # Additional pie/donut charts for remaining dimensions
                for d in dims[2:]:
                    d_col = d["col"]
                    if (d_col, "__count__") in charted_combos:
                        continue
                    card = d.get("cardinality", self.df[d_col].nunique())
                    if card > 15:
                        continue  # Too many categories for pie
                    try:
                        all_counts_extra_pie = self.df[d_col].value_counts()
                        counts = all_counts_extra_pie.head(15)  # pie/donut: cap at 15 slices
                        if len(counts) < 2:
                            continue
                        d_label = self._title_case(d_col)
                        ct = "pie" if card <= 6 else "donut"
                        charts.append({
                            "type": "chart", "chartType": ct,
                            "title": f"{d_label} Composition",
                            "description": f"Shows the proportional breakdown of {d_label} categories in the dataset.",
                            "chartData": {
                                "labels": [str(k) for k in counts.index.tolist()],
                                "series": [{"name": f"{d_label} Count", "data": [int(v) for v in counts.values.tolist()]}]
                            },
                            "colorTheme": color_rotation[extra_idx % len(color_rotation)],
                            "gridW": 6, "gridH": 3,
                            "origin_query": f"Composition of {d_label}",
                            "filter_context": {"column": d_col, "type": "dimension"}
                        })
                        charted_combos.add((d_col, "__count__"))
                        extra_idx += 1
                    except Exception:
                        pass
                    if extra_idx >= 8:
                        break

            logger.info(f"[_generate_dashboard_charts] Generated {len(charts)} chart widgets")
        except Exception as e:
            logger.warning(f"[_generate_dashboard_charts] Error: {e}")

        return charts

    # ──────────────────────────────────────────────────────────────────────────
    # CHART BUILDER — Looker Studio style interactive chart generation
    # ──────────────────────────────────────────────────────────────────────────

    def get_chart_schema(self) -> dict:
        """
        Return a lightweight schema of the dataset for the Chart Builder UI.
        Classifies every column into:
          - dimensions: qualitative/categorical columns
          - measures:   quantitative/numeric columns
        No LLM involved — pure Pandas dtype introspection + file fingerprint.
        """
        try:
            fp = self._build_file_fingerprint()
            return {
                "dimensions": [
                    {"col": d["col"], "cardinality": d.get("cardinality", 0)}
                    for d in fp.get("dimensions", [])
                ],
                "measures": [
                    {"col": m["col"], "agg": m.get("agg", "sum")}
                    for m in fp.get("measures", [])
                ],
            }
        except Exception as e:
            logger.warning(f"[get_chart_schema] Error: {e}")
            # Graceful fallback: classify by dtype
            dims, measures = [], []
            if self.df is not None:
                for col in self.df.columns:
                    if self.df[col].dtype in (object, "category") or self.df[col].nunique() < 50:
                        dims.append({"col": col, "cardinality": int(self.df[col].nunique())})
                    else:
                        measures.append({"col": col, "agg": "sum"})
            return {"dimensions": dims, "measures": measures}

    def generate_custom_chart_widget(
        self,
        chart_type: str,
        dimension: str,
        measure: str | None,
        aggregation: str = "sum",
    ) -> dict:
        """
        Build a single chart widget deterministically from user-chosen parameters.
        No LLM — pure Pandas groupby / value_counts.

        chart_type  : 'bar' | 'line' | 'area' | 'combo' | 'pie' | 'donut' | 'scatter' |
                      'bubble' | 'histogram' | 'funnel' | 'gauge' | 'heatmap' | 'treemap' | 'waterfall'
        dimension   : qualitative column (X-axis / labels)
        measure     : quantitative column (Y-axis / values), None for count charts
        aggregation : 'sum' | 'mean' | 'count'
        """
        import uuid as _uuid
        import numpy as np

        ct = chart_type.lower()
        supported_types = {
            "bar", "line", "area", "combo", "pie", "donut", "scatter",
            "bubble", "histogram", "funnel", "gauge", "heatmap", "treemap", "waterfall"
        }
        if ct not in supported_types:
            raise ValueError(f"Unsupported chart_type '{chart_type}'. Allowed: {', '.join(sorted(supported_types))}")
        dim_label = self._title_case(dimension)

        # ── Validate columns exist ──
        if dimension not in self.df.columns:
            raise ValueError(f"Column '{dimension}' not found in dataset")
        if measure and measure not in self.df.columns:
            raise ValueError(f"Column '{measure}' not found in dataset")

        # ── Compute aggregated data ──
        if measure and aggregation in ("sum", "mean"):
            if aggregation == "sum":
                grouped = self.df.groupby(dimension)[measure].sum().sort_values(ascending=False)
                agg_label = "Total"
            else:
                grouped = self.df.groupby(dimension)[measure].mean().sort_values(ascending=False)
                agg_label = "Average"
            m_label = self._title_case(measure)
            title = f"{agg_label} {m_label} by {dim_label}"
            description = f"{agg_label} {m_label} grouped by {dim_label}."
        else:
            # count aggregation or no measure
            grouped = self.df[dimension].value_counts()
            agg_label = "Count"
            m_label = "Count"
            title = f"{dim_label} Distribution"
            description = f"Count of records per {dim_label} category."

        # Cap at 50 for payload size (pie-like: 15)
        max_items = 15 if ct in ("pie", "donut", "funnel") else 50
        grouped = grouped.head(max_items)

        if len(grouped) == 0:
            raise ValueError(f"No data to chart for dimension '{dimension}'")

        # ── Build chartData in the standard widget format ──
        labels = [str(k) for k in grouped.index.tolist()]
        values = [round(float(v), 2) for v in grouped.values.tolist()]

        if ct in ("pie", "donut"):
            chart_data = {"labels": labels, "series": values}
        elif ct == "combo":
            running = []
            acc = 0.0
            for i, v in enumerate(values):
                acc += float(v)
                running.append(round(acc / (i + 1), 2))
            chart_data = {
                "labels": labels,
                "series": [
                    {"name": f"{agg_label} {m_label}", "data": values},
                    {"name": "Trend", "data": running},
                ],
            }
        else:
            chart_data = {
                "labels": labels,
                "series": [{"name": f"{agg_label} {m_label}", "data": values}],
            }

        color_map = {
            "bar": "indigo", "line": "violet", "area": "emerald", "combo": "mokkup1",
            "pie": "amber", "donut": "rose", "scatter": "cyan", "bubble": "cyan",
            "histogram": "indigo", "funnel": "holidaySpark", "gauge": "rustic",
            "heatmap": "mokkup2", "treemap": "emerald", "waterfall": "holidaySpark",
        }

        grid_w = 12 if ct in ("line", "area", "combo", "heatmap", "treemap", "waterfall") else 6
        if ct == "gauge":
            grid_w = 4

        widget = {
            "id": f"cb-{_uuid.uuid4().hex[:8]}",
            "type": "chart",
            "chartType": ct,
            "title": title,
            "description": description,
            "chartData": chart_data,
            "horizontal": ct in ("bar", "histogram") and len(labels) > 8,
            "colorTheme": color_map.get(ct, "indigo"),
            "gridW": grid_w,
            "gridH": 3,
            "origin_query": f"Chart Builder: {agg_label} {m_label} by {dim_label}",
            "filter_context": {
                "column": dimension,
                "measure": measure or "__count__",
                "agg": aggregation,
                "source": "chart_builder",
            },
        }
        logger.info(f"[generate_custom_chart_widget] Built '{ct}' chart: {title}")
        return widget

    def generate_filtered_dashboard(self, filters: dict) -> dict:
        """
        Re-generate dashboard widgets with cross-filter applied.
        filters: {"column": "Region", "value": "West"} or
                 {"filters": {"Region": "West", "Category": "Tech"}}
        Applies the filter to self.df, regenerates charts + recalculates KPIs,
        and returns the full widget set with updated data.
        """
        try:
            # Parse filters: support single {column, value} or multi {filters: {col: val, ...}}
            active_filters = {}
            if "filters" in filters and isinstance(filters["filters"], dict):
                active_filters = filters["filters"]
            elif "column" in filters and "value" in filters:
                active_filters = {filters["column"]: filters["value"]}

            if not active_filters:
                return {"status": "error", "detail": "No valid filters provided"}

            # Apply filters to get filtered DataFrame
            filtered_df = self.df.copy()
            applied = []
            for col, val in active_filters.items():
                if col in filtered_df.columns:
                    filtered_df = filtered_df[filtered_df[col].astype(str) == str(val)]
                    applied.append(f"{col}={val}")

            if filtered_df.empty:
                return {"status": "error", "detail": f"No data matches filter: {', '.join(applied)}"}

            logger.info(f"[generate_filtered_dashboard] 🔍 Applying filter: {applied} → {len(filtered_df)} rows (from {len(self.df)})")

            # Temporarily swap the DataFrame
            original_df = self.df
            self.df = filtered_df

            try:
                fingerprint = self._build_file_fingerprint()
                measures = fingerprint.get("measures", [])
                dims = fingerprint.get("dimensions", [])
                ti = fingerprint.get("time_intelligence", {})
                dq = fingerprint.get("data_quality", {})

                # Build stable dimensions from the ORIGINAL (unfiltered) DataFrame
                # so that slicers never disappear when filters reduce cardinality
                try:
                    self.df = original_df
                    orig_fp = self._build_file_fingerprint()
                    original_dims = orig_fp.get("dimensions", dims)
                    self.df = filtered_df  # swap back to filtered
                except Exception:
                    original_dims = dims  # fallback
                    self.df = filtered_df

                widgets = []
                filter_desc = ", ".join(f"{c}={v}" for c, v in active_filters.items())

                # ── Summary banner (filtered context) ──
                summary_parts = [f"Filtered view: {filter_desc}. Showing {len(filtered_df):,} of {len(original_df):,} records."]
                if measures:
                    top = measures[0]
                    val = top.get("sum") if top.get("agg") == "sum" else top.get("mean", 0)
                    fmt = f"₹{val:,.0f}" if top.get("format_hint") == "currency" else f"{val:,.2f}"
                    summary_parts.append(f"{self._title_case(top['col'])}: {fmt}.")
                if ti.get("mom_growth") is not None:
                    direction = "up" if ti["mom_growth"] > 0 else "down"
                    summary_parts.append(f"MoM: {direction} {abs(ti['mom_growth'])}%.")

                widgets.append({
                    "id": "widget-0", "type": "summary",
                    "title": f"Filtered: {filter_desc}",
                    "text": " ".join(summary_parts),
                    "icon": "filter", "gridW": 12, "gridH": 2,
                    "origin_query": f"Filtered analysis: {filter_desc}",
                    "filter_context": active_filters
                })

                # ── KPIs from top measures (recalculated on filtered data) ──
                for i, m in enumerate(measures[:3]):
                    col = m["col"]
                    agg = m.get("agg", "sum")
                    val = float(filtered_df[col].sum()) if agg == "sum" else float(filtered_df[col].mean())
                    display = self._format_kpi_value(val, m.get("format_hint", "number"), agg)

                    # Compare with unfiltered — context depends on agg type
                    orig_val = float(original_df[col].sum()) if agg == "sum" else float(original_df[col].mean())
                    if agg == "sum" and orig_val:
                        pct_of_total = round((val / orig_val * 100), 1)
                        subtitle = f"{pct_of_total}% of total"
                        trend = "positive" if pct_of_total > 50 else "neutral"
                    elif agg == "mean" and orig_val:
                        diff = val - orig_val
                        diff_pct = round((diff / abs(orig_val) * 100), 1) if orig_val else 0
                        sign = "+" if diff_pct >= 0 else ""
                        subtitle = f"Avg ({sign}{diff_pct}% vs overall)"
                        trend = "positive" if diff_pct > 0 else ("negative" if diff_pct < -5 else "neutral")
                    else:
                        subtitle = self._format_kpi_subtitle(m)
                        trend = "neutral"

                    icon = self._pick_kpi_icon(m)

                    widgets.append({
                        "id": f"widget-{i+1}", "type": "kpi",
                        "title": self._format_kpi_title(m),
                        "value": display,
                        "subtitle": subtitle,
                        "trend": trend,
                        "icon": icon,
                        "gridW": 3, "gridH": 2,
                        "origin_query": f"{agg} of {col} where {filter_desc}",
                        "filter_context": {"column": col, "agg": agg}
                    })

                # ── Charts from filtered data ──
                chart_widgets = self._generate_dashboard_charts(fingerprint)
                for cw in chart_widgets:
                    cw['id'] = f"chart-{len(widgets)}"
                    widgets.append(cw)

                # Re-number IDs
                for idx, w in enumerate(widgets):
                    w['id'] = f"widget-{idx+1}"

                fp_for_client = {
                    "measures": [{"col": m["col"], "agg": m.get("agg", "sum"), "format_hint": m.get("format_hint", "number")}
                                 for m in measures[:12]],
                    "dimensions": [{"col": d["col"], "cardinality": d.get("cardinality", 0),
                                    "dim_type": d.get("dim_type", "categorical"), "top_values": d.get("top_values", {})}
                                   for d in original_dims[:10]],
                    "time_intelligence": ti,
                    "data_quality": dq,
                }

                result = self._build_response_envelope(widgets, fp_for_client)
                result["applied_filters"] = active_filters
                result["filtered_rows"] = len(filtered_df)
                result["total_rows"] = len(original_df)
                return result

            finally:
                # Always restore the original DataFrame
                self.df = original_df

        except Exception as e:
            log_full_exception(e, "Filtered dashboard generation error")
            return {"status": "error", "detail": str(e)}

    # ========================================================================
    # QUERY DETECTION HELPERS
    # ========================================================================
    
    def _detect_insight_query(self, query: str) -> bool:
        """Check if the query is asking for insights/analysis (not a chart)"""
        insight_keywords = [
            'insight', 'analyze', 'analysis', 'summary', 'summarize',
            'key findings', 'key takeaway', 'pattern', 'observation',
            'what can you tell', 'tell me about', 'explain', 'overview',
            'highlight', 'notable', 'interesting', 'anomal'
        ]
        query_lower = query.lower()
        return any(kw in query_lower for kw in insight_keywords)

    def _detect_chart_query(self, query: str) -> bool:
        """Check if the query is asking for a chart/visualization"""
        chart_keywords = [
            'chart', 'plot', 'graph', 'visualize', 'visualization',
            'pie', 'bar', 'line', 'scatter', 'bubble', 'histogram', 'area',
            'doughnut', 'donut', 'polar', 'funnel', 'gauge', 'heatmap',
            'treemap', 'waterfall', 'combo', 'trend', 'distribution'
        ]
        query_lower = query.lower()
        return any(keyword in query_lower for keyword in chart_keywords)
    
    def _get_chart_type(self, query: str) -> str:
        """Detect chart type from query keywords"""
        query_lower = query.lower()
        
        if 'waterfall' in query_lower:
            return 'waterfall'
        elif 'heatmap' in query_lower:
            return 'heatmap'
        elif 'treemap' in query_lower:
            return 'treemap'
        elif 'funnel' in query_lower:
            return 'funnel'
        elif 'gauge' in query_lower or 'speedometer' in query_lower:
            return 'gauge'
        elif 'combo' in query_lower or 'combined' in query_lower or 'combination' in query_lower:
            return 'combo'
        elif 'bubble' in query_lower:
            return 'bubble'
        elif 'histogram' in query_lower:
            return 'histogram'
        elif 'line' in query_lower or 'trend' in query_lower:
            return 'line'
        elif 'area' in query_lower or 'filled' in query_lower:
            return 'area'
        elif 'doughnut' in query_lower or 'donut' in query_lower:
            return 'doughnut'
        elif 'polar' in query_lower:
            return 'polarArea'
        elif 'pie' in query_lower:
            return 'pie'
        elif 'scatter' in query_lower:
            return 'scatter'
        else:
            return 'bar'  # default

    # ── COMPARE-MODE: Unified semantic comparison ────────────────
    @observe(name="dashboard.compare_unified.build", as_type="span")
    def generate_unified_comparison(self, compare_agent: Any,
                                     base_widgets: list,
                                     base_label: str = "File A",
                                     compare_label: str = "File B") -> list:
        """
        Produce MERGED widgets for a unified comparison view.
        Takes base-file widgets and the compare agent, returns a single widget list
        where KPIs show value + compare_value + delta_percentage, and charts
        overlay dual series from both files.
        """
        import numpy as np
        unified: list = []

        langfuse_context.update_current_observation(
            input={
                "base_widget_count": len(base_widgets),
                "base_label": base_label,
                "compare_label": compare_label,
            },
            metadata={
                "base_file_uuid": self.file_uuid,
                "base_filename": self.filename,
                "compare_file_uuid": getattr(compare_agent, "file_uuid", None),
                "compare_filename": getattr(compare_agent, "filename", None),
            },
            tags=["dashboard", "compare", "unified", "build"],
        )

        try:
            base_fp = self._build_file_fingerprint()
        except Exception:
            base_fp = {"measures": [], "dimensions": [], "time_intelligence": {},
                       "data_quality": {}, "row_count": len(self.df)}

        try:
            cmp_fp = compare_agent._build_file_fingerprint()
        except Exception:
            cmp_fp = {"measures": [], "dimensions": [], "time_intelligence": {},
                      "data_quality": {}, "row_count": len(compare_agent.df)}

        base_measures = base_fp.get("measures", [])
        cmp_measures = cmp_fp.get("measures", [])
        base_dims = base_fp.get("dimensions", [])
        cmp_dims = cmp_fp.get("dimensions", [])
        base_ti = base_fp.get("time_intelligence", {})
        cmp_ti = cmp_fp.get("time_intelligence", {})

        def _find_measure(measures_list: list, hint: str) -> dict | None:
            hint = hint.lower().strip()
            for m in measures_list:
                if m["col"].lower() == hint:
                    return m
            for m in measures_list:
                if hint in m["col"].lower() or m["col"].lower() in hint:
                    return m
            return measures_list[0] if measures_list else None

        def _find_dim(dims_list: list, hint: str) -> dict | None:
            hint = hint.lower().strip()
            for d in dims_list:
                if d["col"].lower() == hint:
                    return d
            for d in dims_list:
                if hint in d["col"].lower() or d["col"].lower() in hint:
                    return d
            return dims_list[0] if dims_list else None

        def _calc_delta(val_a: float, val_b: float) -> float | None:
            """Percentage difference: how much A differs from B."""
            if val_b and val_b != 0:
                return round(((val_a - val_b) / abs(val_b)) * 100, 1)
            return None

        def _dedup_words(text: str) -> str:
            """Remove consecutive duplicate words: 'Total Total Applications' → 'Total Applications'."""
            words = text.split()
            result = []
            for w in words:
                if not result or w.lower() != result[-1].lower():
                    result.append(w)
            return ' '.join(result)

        for bw in base_widgets:
            wtype = bw.get("type", "")
            wid = bw.get("id", f"widget-{len(unified)}")
            gridW = bw.get("gridW", 3)
            gridH = bw.get("gridH", 2)

            try:
                # ── SUMMARY → Rich comparison overview ──
                if wtype == "summary":
                    base_rows = len(self.df)
                    cmp_rows = len(compare_agent.df)
                    base_cols = len(self.df.columns)
                    cmp_cols = len(compare_agent.df.columns)
                    row_delta = _calc_delta(float(base_rows), float(cmp_rows))

                    # ── Build metric summaries ──
                    metric_summaries = []
                    for bm in base_measures[:6]:
                        cm = _find_measure(cmp_measures, bm["col"])
                        if cm:
                            agg = bm.get("agg", "sum")
                            bv = float(bm.get("sum") if agg == "sum" else bm.get("mean", 0))
                            cv = float(cm.get("sum") if agg == "sum" else cm.get("mean", 0))
                            delta = _calc_delta(bv, cv)
                            delta_str = f" ({delta:+.1f}%)" if delta is not None else ""
                            metric_summaries.append({
                                "name": self._title_case(bm['col']),
                                "base": f"{bv:,.2f}" if bv != int(bv) else f"{bv:,.0f}",
                                "compare": f"{cv:,.2f}" if cv != int(cv) else f"{cv:,.0f}",
                                "delta": delta, "delta_str": delta_str
                            })

                    # ── Build insightful summary text ──
                    insights: list[str] = []

                    # Dataset size comparison
                    if row_delta is not None and abs(row_delta) >= 1:
                        direction = "more" if row_delta > 0 else "fewer"
                        insights.append(
                            f"{base_label} has {abs(row_delta):.1f}% {direction} records "
                            f"({base_rows:,} vs {cmp_rows:,})"
                        )
                    else:
                        insights.append(
                            f"Both datasets have similar record counts "
                            f"({base_rows:,} vs {cmp_rows:,})"
                        )

                    # Biggest mover
                    if metric_summaries:
                        significant = [m for m in metric_summaries if m["delta"] is not None and abs(m["delta"]) >= 0.5]
                        if significant:
                            biggest = max(significant, key=lambda m: abs(m["delta"]))
                            direction = "higher" if biggest["delta"] > 0 else "lower"
                            insights.append(
                                f"{biggest['name']} is {abs(biggest['delta']):.1f}% {direction} in {base_label} "
                                f"({biggest['base']} vs {biggest['compare']})"
                            )
                        else:
                            top = metric_summaries[0]
                            insights.append(
                                f"{top['name']}: {base_label} = {top['base']}, {compare_label} = {top['compare']}"
                            )

                    # Additional metric highlights (up to 2 more)
                    extra_count = 0
                    for ms in metric_summaries[1:]:
                        if extra_count >= 2:
                            break
                        if ms["delta"] is not None and abs(ms["delta"]) >= 5:
                            direction = "higher" if ms["delta"] > 0 else "lower"
                            insights.append(
                                f"{ms['name']} also {abs(ms['delta']):.1f}% {direction} "
                                f"({ms['base']} vs {ms['compare']})"
                            )
                            extra_count += 1

                    # Overall trend verdict
                    positive_count = sum(1 for m in metric_summaries if (m["delta"] or 0) > 0)
                    negative_count = sum(1 for m in metric_summaries if (m["delta"] or 0) < 0)
                    if len(metric_summaries) >= 2:
                        if positive_count > negative_count:
                            insights.append(f"{base_label} outperforms on {positive_count} of {len(metric_summaries)} metrics")
                        elif negative_count > positive_count:
                            insights.append(f"{compare_label} outperforms on {negative_count} of {len(metric_summaries)} metrics")
                        else:
                            insights.append(f"Performance is balanced across {len(metric_summaries)} metrics")

                    text = (
                        f"Comparative analysis: {base_label} ({base_cols} cols) vs "
                        f"{compare_label} ({cmp_cols} cols). "
                        + ". ".join(insights) + "."
                    )

                    unified.append({
                        "id": wid, "type": "summary",
                        "title": f"Comparison: {base_label} vs {compare_label}",
                        "text": text, "icon": "git-compare",
                        "gridW": 12, "gridH": 2,
                        "origin_query": "Unified comparison overview",
                        "filter_context": {},
                        "base_label": base_label, "compare_label": compare_label,
                        "metric_summaries": metric_summaries,
                        "row_delta": row_delta,
                        "base_rows": base_rows, "compare_rows": cmp_rows
                    })

                # ── KPI → Merged with compare_value + delta ──
                elif wtype == "kpi":
                    hint_col = bw.get("filter_context", {}).get("column", "")
                    hint_agg = bw.get("filter_context", {}).get("agg", "")
                    title_lower = bw.get("title", "").lower()

                    # Special: Total Records
                    if "record" in title_lower or "total record" in title_lower:
                        bv = len(self.df)
                        cv = len(compare_agent.df)
                        delta = _calc_delta(float(bv), float(cv))
                        unified.append({
                            "id": wid, "type": "kpi",
                            "title": "Total Records",
                            "value": f"{bv:,}", "compare_value": f"{cv:,}",
                            "delta_percentage": delta,
                            "subtitle": f"{base_label} vs {compare_label}",
                            "trend": "positive" if (delta or 0) > 0 else "negative" if (delta or 0) < 0 else "neutral",
                            "icon": "database",
                            "gridW": max(gridW, 4), "gridH": gridH,
                            "origin_query": "record count", "filter_context": {},
                            "base_label": base_label, "compare_label": compare_label
                        })
                        continue

                    # Special: MoM Growth
                    if "mom" in title_lower or "growth" in title_lower:
                        bv_raw = base_ti.get("mom_growth")
                        cv_raw = cmp_ti.get("mom_growth")
                        bv_str = f"{bv_raw:+.1f}%" if bv_raw is not None else "N/A"
                        cv_str = f"{cv_raw:+.1f}%" if cv_raw is not None else "N/A"
                        unified.append({
                            "id": wid, "type": "kpi",
                            "title": "MoM Growth",
                            "value": bv_str, "compare_value": cv_str,
                            "delta_percentage": None,
                            "subtitle": f"{base_label} vs {compare_label}",
                            "trend": "positive" if (bv_raw or 0) > 0 else "negative",
                            "icon": "trending-up",
                            "gridW": max(gridW, 4), "gridH": gridH,
                            "origin_query": "MoM growth", "filter_context": {},
                            "base_label": base_label, "compare_label": compare_label
                        })
                        continue

                    # Standard KPI: match columns across both files by title first, then fingerprint
                    if not hint_col:
                        hint_col = bw.get("origin_query", bw.get("title", ""))

                    # 1. Try exact title match in compare fingerprint measures
                    bw_title_lower = bw.get("title", "").lower().replace(" ", "")
                    cm_by_title = next(
                        (m for m in cmp_measures
                         if m["col"].lower().replace(" ", "") in bw_title_lower
                         or bw_title_lower in m["col"].lower().replace(" ", "")),
                        None
                    )

                    bm = _find_measure(base_measures, hint_col)
                    cm = cm_by_title or _find_measure(cmp_measures, hint_col)

                    if bm:
                        agg = hint_agg or bm.get("agg", "sum")
                        bv_raw = float(bm.get("sum") if agg == "sum" else bm.get("mean", 0))
                        bv_str = self._format_kpi_value(bv_raw, bm.get("format_hint", "number"), agg)

                        if cm:
                            cv_raw = float(cm.get("sum") if agg == "sum" else cm.get("mean", 0))
                            cv_str = self._format_kpi_value(cv_raw, cm.get("format_hint", "number"), agg)
                            delta = _calc_delta(bv_raw, cv_raw)
                        else:
                            cv_str = "N/A"
                            cv_raw = 0
                            delta = None

                        unified.append({
                            "id": wid, "type": "kpi",
                            "title": self._format_kpi_title(bm),
                            "value": bv_str, "compare_value": cv_str,
                            "delta_percentage": delta,
                            "subtitle": f"{base_label} vs {compare_label}",
                            "trend": "positive" if (delta or 0) > 0 else "negative" if (delta or 0) < 0 else "neutral",
                            "icon": self._pick_kpi_icon(bm),
                            "gridW": max(gridW, 4), "gridH": gridH,
                            "origin_query": bw.get("origin_query", f"{agg} of {bm['col']}"),
                            "filter_context": bw.get("filter_context", {}),
                            "base_label": base_label, "compare_label": compare_label
                        })
                    else:
                        unified.append({
                            "id": wid, "type": "kpi",
                            "title": bw.get("title", "KPI"),
                            "value": bw.get("value", "N/A"), "compare_value": "N/A",
                            "delta_percentage": None,
                            "subtitle": "No matching metric", "trend": "neutral",
                            "icon": "bar-chart-2",
                            "gridW": max(gridW, 4), "gridH": gridH,
                            "origin_query": "", "filter_context": {},
                            "base_label": base_label, "compare_label": compare_label
                        })

                # ── LIST → Merged side-by-side ranking ──
                elif wtype == "list":
                    fc = bw.get("filter_context", {})
                    dim_hint = fc.get("column", "")
                    origin = bw.get("origin_query", "")
                    measure_hint = ""
                    if " by " in origin.lower():
                        parts = origin.lower().split(" by ", 1)
                        dim_hint = dim_hint or parts[0].replace("top ", "").strip()
                        measure_hint = parts[1].strip()

                    bd = _find_dim(base_dims, dim_hint)
                    cd = _find_dim(cmp_dims, dim_hint)
                    bm = _find_measure(base_measures, measure_hint) if measure_hint else (base_measures[0] if base_measures else None)
                    cm = _find_measure(cmp_measures, measure_hint) if measure_hint else (cmp_measures[0] if cmp_measures else None)

                    items = []
                    if bd and bm:
                        d_col_b = bd["col"]
                        m_col_b = bm["col"]
                        agg = bm.get("agg", "sum")
                        fmt_hint = bm.get("format_hint", "number")
                        try:
                            grp_b = self.df.groupby(d_col_b)[m_col_b]
                            agg_b = grp_b.sum() if agg == "sum" else grp_b.mean()
                            top5_b = agg_b.sort_values(ascending=False).head(5)

                            # Try compare side
                            d_col_c = cd["col"] if cd else d_col_b
                            m_col_c = cm["col"] if cm else m_col_b
                            try:
                                grp_c = compare_agent.df.groupby(d_col_c)[m_col_c]
                                agg_c = grp_c.sum() if agg == "sum" else grp_c.mean()
                                cmp_map = agg_c.to_dict()
                            except Exception:
                                cmp_map = {}

                            for k, v in top5_b.items():
                                cv = cmp_map.get(k)
                                item = {
                                    "label": str(k),
                                    "value": self._format_list_value(float(v), fmt_hint),
                                    "compare_value": self._format_list_value(float(cv), fmt_hint) if cv is not None else "—",
                                }
                                items.append(item)
                        except Exception:
                            items = [{"label": "N/A", "value": "—", "compare_value": "—"}]

                    unified.append({
                        "id": wid, "type": "list",
                        "title": bw.get("title", "Top Items"),
                        "items": items or [{"label": "N/A", "value": "—", "compare_value": "—"}],
                        "icon": "trophy",
                        "gridW": max(gridW, 4), "gridH": gridH,
                        "origin_query": bw.get("origin_query", ""),
                        "filter_context": fc,
                        "base_label": base_label, "compare_label": compare_label
                    })

                # ── CHART → Dual series overlay ──
                elif wtype == "chart":
                    chart_type = bw.get("chartType", "bar")
                    base_chart_data = bw.get("chartData", {})
                    base_labels = base_chart_data.get("labels", [])
                    raw_series = base_chart_data.get("series", [])

                    # Normalize base_series: could be flat numbers or list-of-dicts
                    normalized_base_series = []
                    if raw_series:
                        if isinstance(raw_series[0], dict):
                            normalized_base_series = raw_series
                        else:
                            # Flat number array → wrap in single series object
                            series_name = bw.get("title", "Value").replace("Distribution", "").replace("Breakdown", "").strip()
                            normalized_base_series = [{"name": series_name, "data": raw_series}]

                    # Get the dimension and measure hints from the base chart
                    fc = bw.get("filter_context", {})
                    dim_hint = fc.get("column", "")
                    measure_col = fc.get("measure", "")
                    # Detect whether the base chart is a COUNT chart (distribution / category count)
                    fc_agg = fc.get("agg", "").lower()
                    fc_type = fc.get("type", "").lower()
                    is_count_chart = (
                        fc_agg == "count"
                        or fc_type == "dimension"
                        or (not measure_col and not fc_agg)
                        or "count" in bw.get("origin_query", "").lower()
                        or "distribution" in bw.get("title", "").lower()
                        or "breakdown" in bw.get("title", "").lower()
                    )

                    # Also try extracting hints from the title / origin_query
                    if not dim_hint:
                        origin = bw.get("origin_query", bw.get("title", ""))
                        if " by " in origin.lower():
                            dim_hint = origin.lower().split(" by ", 1)[1].strip()
                        elif " of " in origin.lower():
                            dim_hint = origin.lower().split(" of ", 1)[1].strip()

                    # Try to rebuild the same chart grouping on compare data
                    cmp_series_data = []

                    if dim_hint:
                        cd = _find_dim(cmp_dims, dim_hint)
                        if cd:
                            try:
                                d_col = cd["col"]
                                if is_count_chart:
                                    # COUNT: use value_counts — same aggregation as the base chart
                                    agg_result = compare_agent.df[d_col].value_counts()
                                    cmp_map = {str(k): round(float(v), 2) for k, v in agg_result.items()}
                                    cmp_series_data = [cmp_map.get(str(lbl), 0) for lbl in base_labels]
                                else:
                                    # SUM / MEAN of a numeric measure
                                    cm = _find_measure(cmp_measures, measure_col) if measure_col else (cmp_measures[0] if cmp_measures else None)
                                    if cm:
                                        m_col = cm["col"]
                                        agg = cm.get("agg", "sum")
                                        grp = compare_agent.df.groupby(d_col)[m_col]
                                        agg_result = grp.sum() if agg == "sum" else grp.mean()
                                        cmp_map = agg_result.to_dict()
                                        cmp_series_data = [round(float(cmp_map.get(lbl, 0)), 2) for lbl in base_labels]
                            except Exception:
                                pass

                    if not cmp_series_data and base_labels:
                        # Fallback: mirror the exact aggregation type of the base chart
                        if cmp_dims:
                            try:
                                d_col = cmp_dims[0]["col"]
                                if is_count_chart:
                                    agg_result = compare_agent.df[d_col].value_counts()
                                    cmp_map = {str(k): round(float(v), 2) for k, v in agg_result.items()}
                                    cmp_series_data = [cmp_map.get(str(lbl), 0) for lbl in base_labels]
                                elif cmp_measures:
                                    m_col = cmp_measures[0]["col"]
                                    agg = cmp_measures[0].get("agg", "sum")
                                    grp = compare_agent.df.groupby(d_col)[m_col]
                                    agg_result = grp.sum() if agg == "sum" else grp.mean()
                                    cmp_map = {str(k): round(float(v), 2) for k, v in agg_result.items()}
                                    cmp_series_data = [cmp_map.get(str(lbl), 0) for lbl in base_labels]
                            except Exception:
                                cmp_series_data = [0] * len(base_labels)

                    # Build merged series — use _dedup_words to prevent "Total Total" etc.
                    merged_series = []
                    for s in normalized_base_series:
                        raw_name = _dedup_words(s.get("name", "Value"))
                        merged_series.append({
                            "name": f"{base_label}: {raw_name}",
                            "data": s.get("data", []),
                            "source": "base"
                        })
                    if cmp_series_data:
                        raw_name = _dedup_words(normalized_base_series[0].get("name", "Value") if normalized_base_series else "Value")
                        merged_series.append({
                            "name": f"{compare_label}: {raw_name}",
                            "data": cmp_series_data,
                            "source": "compare"
                        })

                    # For pie/donut charts: keep separate datasets for side-by-side rendering
                    is_pie_donut = chart_type in ('pie', 'donut', 'doughnut', 'polarArea')
                    if is_pie_donut and cmp_series_data:
                        # Build independent compare-side labels + series (own top-N, not just base_labels)
                        cmp_own_labels = []
                        cmp_own_data = []
                        try:
                            cd_pie = _find_dim(cmp_dims, dim_hint) if dim_hint else (cmp_dims[0] if cmp_dims else None)
                            if cd_pie:
                                d_col_pie = cd_pie["col"]
                                if is_count_chart:
                                    vc = compare_agent.df[d_col_pie].value_counts().head(len(base_labels) or 10)
                                    cmp_own_labels = [str(k) for k in vc.index]
                                    cmp_own_data = [round(float(v), 2) for v in vc.values]
                                else:
                                    cm_pie = _find_measure(cmp_measures, measure_col) if measure_col else (cmp_measures[0] if cmp_measures else None)
                                    if cm_pie:
                                        grp_pie = compare_agent.df.groupby(d_col_pie)[cm_pie["col"]]
                                        agg_pie = grp_pie.sum() if cm_pie.get("agg", "sum") == "sum" else grp_pie.mean()
                                        agg_pie = agg_pie.sort_values(ascending=False).head(len(base_labels) or 10)
                                        cmp_own_labels = [str(k) for k in agg_pie.index]
                                        cmp_own_data = [round(float(v), 2) for v in agg_pie.values]
                        except Exception:
                            pass
                        if not cmp_own_labels:
                            cmp_own_labels = base_labels
                            cmp_own_data = cmp_series_data

                        unified.append({
                            "id": wid, "type": "chart",
                            "chartType": "donut",
                            "title": bw.get("title", "Chart"),
                            "chartData": {"labels": base_labels, "series": raw_series},
                            "base_chartData": {"labels": base_labels, "series": raw_series},
                            "cmp_chartData": {"labels": cmp_own_labels, "series": cmp_own_data},
                            "gridW": max(gridW, 6), "gridH": max(gridH, 3),
                            "origin_query": bw.get("origin_query", ""),
                            "filter_context": fc,
                            "base_label": base_label, "compare_label": compare_label,
                            "is_comparison": True
                        })
                    else:
                        unified.append({
                            "id": wid, "type": "chart",
                            "chartType": chart_type,
                            "title": bw.get("title", "Chart"),
                            "chartData": {
                                "labels": base_labels,
                                "series": merged_series
                            },
                            "gridW": max(gridW, 6), "gridH": max(gridH, 3),
                            "origin_query": bw.get("origin_query", ""),
                            "filter_context": fc,
                            "base_label": base_label, "compare_label": compare_label,
                            "is_comparison": True
                        })

                # ── INSIGHT → Comparative insight using both files ──
                elif wtype == "insight":
                    base_title = bw.get("title", "Insight")
                    base_text = bw.get("text", "")
                    fc_ins = bw.get("filter_context", {})
                    dim_hint_ins = fc_ins.get("column", "")

                    # Build comparative fact block from both files
                    try:
                        comp_raw_facts = ""
                        # Concentration comparison
                        if dim_hint_ins and base_measures:
                            bd_ins = _find_dim(base_dims, dim_hint_ins)
                            cd_ins = _find_dim(cmp_dims, dim_hint_ins)
                            bm_ins = base_measures[0]
                            cm_ins = _find_measure(cmp_measures, bm_ins["col"])

                            if bd_ins and cd_ins and cm_ins:
                                d_col_b = bd_ins["col"]
                                m_col_b = bm_ins["col"]
                                d_col_c = cd_ins["col"]
                                m_col_c = cm_ins["col"]
                                agg = bm_ins.get("agg", "sum")

                                grp_b = self.df.groupby(d_col_b)[m_col_b]
                                agg_b = grp_b.sum() if agg == "sum" else grp_b.mean()
                                agg_b = agg_b.sort_values(ascending=False)
                                grp_c = compare_agent.df.groupby(d_col_c)[m_col_c]
                                agg_c = grp_c.sum() if agg == "sum" else grp_c.mean()
                                agg_c = agg_c.sort_values(ascending=False)

                                top3_b = list(agg_b.head(3).index)
                                top3_c = list(agg_c.head(3).index)
                                total_b = agg_b.sum()
                                total_c = agg_c.sum()
                                top3_share_b = round((agg_b.head(3).sum() / max(total_b, 1)) * 100, 1)
                                top3_share_c = round((agg_c.head(3).sum() / max(total_c, 1)) * 100, 1)

                                comp_raw_facts = (
                                    f"COMPARATIVE ANALYSIS of {self._title_case(m_col_b)} by {self._title_case(d_col_b)}:\n"
                                    f"{base_label}: Top 3 are {', '.join(str(x) for x in top3_b)} "
                                    f"contributing {top3_share_b}% of total ({total_b:,.0f}).\n"
                                    f"{compare_label}: Top 3 are {', '.join(str(x) for x in top3_c)} "
                                    f"contributing {top3_share_c}% of total ({total_c:,.0f}).\n"
                                )
                                # Rank changes
                                rank_changes = []
                                for idx_b, name in enumerate(top3_b):
                                    if name in list(agg_c.index):
                                        idx_c = list(agg_c.index).index(name)
                                        if idx_b != idx_c:
                                            rank_changes.append(f"{name}: rank {idx_c+1} → {idx_b+1}")
                                if rank_changes:
                                    comp_raw_facts += f"Rank changes: {'; '.join(rank_changes)}.\n"

                                delta_total = _calc_delta(float(total_b), float(total_c))
                                if delta_total is not None:
                                    comp_raw_facts += f"Overall change: {delta_total:+.1f}%.\n"

                        # Correlation comparison (if no dim hint, try correlation)
                        elif len(base_measures) >= 2 and len(cmp_measures) >= 2:
                            m1_b = base_measures[0]["col"]
                            m2_b = base_measures[1]["col"]
                            m1_c = cmp_measures[0]["col"]
                            m2_c = cmp_measures[1]["col"]
                            try:
                                corr_b = float(self.df[[m1_b, m2_b]].corr().iloc[0, 1])
                                corr_c = float(compare_agent.df[[m1_c, m2_c]].corr().iloc[0, 1])
                                comp_raw_facts = (
                                    f"COMPARATIVE CORRELATION of {self._title_case(m1_b)} vs {self._title_case(m2_b)}:\n"
                                    f"{base_label}: Correlation r = {corr_b:.2f}.\n"
                                    f"{compare_label}: Correlation r = {corr_c:.2f}.\n"
                                    f"Change in correlation: {corr_b - corr_c:+.2f}.\n"
                                )
                            except Exception:
                                pass

                        # Enrich with comparison-specific LLM prompt
                        if comp_raw_facts:
                            try:
                                prompt = (
                                    "You are a senior data analyst writing a comparative insight for a dashboard.\n"
                                    "Two datasets are being compared side by side.\n"
                                    "Rewrite the statistical comparison below into a clear, insightful paragraph (3-5 sentences)\n"
                                    "that highlights KEY DIFFERENCES AND TRENDS between the two datasets.\n\n"
                                    "Rules:\n"
                                    "- Focus on WHAT changed between the two files and WHY it might matter.\n"
                                    "- Highlight rank changes, proportion shifts, and notable deltas.\n"
                                    "- Use plain language a business user can understand.\n"
                                    "- Use ONLY the numbers provided — do NOT invent any.\n"
                                    "- Do NOT use markdown, bullet points, or headers.\n"
                                    "- Keep under 80 words.\n\n"
                                    f"TITLE: {base_title}\n\n"
                                    f"RAW COMPARISON:\n{comp_raw_facts}\n"
                                    "Rewrite now:"
                                )
                                from app.core.llm import invoke_llm_with_retry
                                enriched = invoke_llm_with_retry(self.llm, prompt, max_retries=1, context_name=f"Compare Insight: {base_title}")
                                enriched = enriched.strip().strip('"').strip("'")
                                if len(enriched) > 40:
                                    insight_text = enriched
                                else:
                                    insight_text = comp_raw_facts
                            except Exception:
                                insight_text = comp_raw_facts
                        else:
                            insight_text = base_text

                    except Exception as insight_err:
                        logger.debug(f"[unified_compare] Comparative insight failed for '{wid}': {insight_err}")
                        insight_text = base_text

                    # Extract highlight from comparison data
                    highlight = ""
                    if comp_raw_facts:
                        # Try to extract a delta for highlight
                        import re as _re
                        delta_match = _re.search(r'Overall change: ([+-]?\d+\.\d+%)', comp_raw_facts)
                        if delta_match:
                            highlight = delta_match.group(1)
                        else:
                            highlight = bw.get("highlight", "")
                    else:
                        highlight = bw.get("highlight", "")

                    unified.append({
                        "id": wid, "type": "insight",
                        "title": base_title,
                        "text": insight_text,
                        "highlight": highlight,
                        "icon": "git-compare" if comp_raw_facts else bw.get("icon", "lightbulb"),
                        "gridW": gridW, "gridH": gridH,
                        "origin_query": bw.get("origin_query", ""),
                        "filter_context": fc_ins,
                        "is_comparison": True,
                        "base_label": base_label, "compare_label": compare_label,
                    })

                # ── UNKNOWN → Pass through ──
                else:
                    unified.append(dict(bw))

            except Exception as widget_err:
                logger.warning(f"[unified_compare] Failed to merge widget '{wid}': {widget_err}")
                # Always fall back to 'insight' type so it renders text, not empty chart
                unified.append({
                    "id": wid, "type": "insight",
                    "title": bw.get("title", "Error"),
                    "text": f"Could not generate comparative data for this widget: {str(widget_err)[:120]}",
                    "highlight": "Merge failed",
                    "gridW": gridW, "gridH": gridH,
                    "icon": "alert-circle",
                    "origin_query": "", "filter_context": {}
                })

        left_out = self._detect_compare_left_out(unified, mode="unified")
        self._last_unified_compare_trace_info = self._strip_trace_none({
            "status": "success",
            "mode": "unified",
            "counts": {
                "base_widgets": len(base_widgets),
                "unified_widgets": len(unified),
            },
            "widget_type_counts": self._widget_type_counts(unified),
            "left_out_count": len(left_out),
            "left_out": left_out,
            "component_titles": [w.get("title", "Untitled") for w in unified if isinstance(w, dict)],
            "component_types": [w.get("type", "unknown") for w in unified if isinstance(w, dict)],
        })

        langfuse_context.update_current_observation(
            output={
                "status": "success",
                "mode": "unified",
                "base_widget_count": len(base_widgets),
                "unified_widget_count": len(unified),
                "widget_type_counts": self._widget_type_counts(unified),
                "left_out_count": len(left_out),
            }
        )

        logger.info(f"[unified_compare] ✅ Generated {len(unified)} unified widgets")
        return unified

    # ── COMPARE-MODE: Clone base widgets onto this file's data ─────
    @observe(name="dashboard.compare_split.build", as_type="span")
    def clone_widgets_from_blueprints(self, base_widgets: list) -> list:
        """Non-streaming wrapper — returns full list."""
        return list(self.clone_widgets_from_blueprints_iter(base_widgets))

    def clone_widgets_from_blueprints_iter(self, base_widgets: list):
        """
        Given widget descriptors from a base file, produce equivalent widgets
        for *this* file's DataFrame.  Each cloned widget keeps the original
        id / gridW / gridH so the two GridStacks stay in perfect sync.

        Strategy per widget type:
          summary  → generate fresh executive summary from this file's fingerprint
          kpi      → recompute using best-matching column & same agg
          list     → groupby the best-matching dim×measure
          insight  → regenerate data-driven insight
          chart    → regenerate chart using best-matching columns
        """
        import numpy as np
        cloned: list = []

        langfuse_context.update_current_observation(
            input={
                "base_widget_count": len(base_widgets),
            },
            metadata={
                "target_file_uuid": self.file_uuid,
                "target_filename": self.filename,
            },
            tags=["dashboard", "compare", "split", "build"],
        )
        try:
            fingerprint = self._build_file_fingerprint()
        except Exception:
            fingerprint = {"measures": [], "dimensions": [], "time_intelligence": {},
                           "data_quality": {}, "row_count": len(self.df), "col_count": len(self.df.columns)}

        measures = fingerprint.get("measures", [])
        dims = fingerprint.get("dimensions", [])
        ti = fingerprint.get("time_intelligence", {})
        dq = fingerprint.get("data_quality", {})
        my_cols_lower = {c.lower(): c for c in self.df.columns}  # fast lookup

        def _best_measure(hint_col: str) -> dict | None:
            """Find the closest measure in this file matching hint_col."""
            hint = hint_col.lower().strip()
            # Exact match
            for m in measures:
                if m["col"].lower() == hint:
                    return m
            # Substring match
            for m in measures:
                if hint in m["col"].lower() or m["col"].lower() in hint:
                    return m
            # Fallback: first measure
            return measures[0] if measures else None

        def _best_dim(hint_col: str) -> dict | None:
            hint = hint_col.lower().strip()
            for d in dims:
                if d["col"].lower() == hint:
                    return d
            for d in dims:
                if hint in d["col"].lower() or d["col"].lower() in hint:
                    return d
            return dims[0] if dims else None

        used_measure_idx = 0  # fallback round-robin
        cloned_count = 0

        # Lazy-init: insights & charts generated on first use so fast widgets stream immediately
        _prebuilt_insights = None
        _prebuilt_charts = None

        for bw in base_widgets:
            wtype = bw.get("type", "")
            shared_id = bw.get("id", f"widget-{cloned_count}")
            gridW = bw.get("gridW", 3)
            gridH = bw.get("gridH", 2)
            fc = bw.get("filter_context", {}) if isinstance(bw.get("filter_context", {}), dict) else {}
            origin_query = str(bw.get("origin_query", "") or fc.get("query") or "").strip()
            widget_id = str(bw.get("id", "") or "")
            is_custom_query_widget = (
                (origin_query and fc.get("source") in ("widget_query", "custom_widget"))
                or (origin_query and widget_id.startswith("widget-custom-"))
                or (origin_query and widget_id.startswith("widget-chart-"))
                or (origin_query and widget_id.startswith("widget-insight-"))
                or (origin_query and widget_id.startswith("widget-error-"))
            )

            try:
                # ── CUSTOM +WIDGET QUERY CLONE ──
                # If widget came from the "+" query builder, re-run the same query on the target file
                # instead of guessing from title text. This preserves semantic intent across file switches.
                if is_custom_query_widget:
                    try:
                        regenerated = self.generate_single_widget(
                            origin_query,
                            widget_type_hint=(wtype or None),
                            chart_type_hint=(bw.get("chartType") or None),
                            filter_context_hint=fc,
                        ).get("widget", {})
                        if regenerated:
                            regenerated_type = str(regenerated.get("type", "") or "").lower()
                            expected_type = str(wtype or "").lower()
                            if expected_type in {"chart", "kpi", "list", "insight", "summary"} and regenerated_type and regenerated_type != expected_type:
                                logger.warning(
                                    f"[clone_widgets] Type mismatch for '{shared_id}' (expected={expected_type}, got={regenerated_type}); using type-specific clone path"
                                )
                                regenerated = {}

                        if regenerated:
                            regenerated["id"] = shared_id
                            regenerated["gridW"] = gridW
                            regenerated["gridH"] = gridH
                            # Keep query metadata durable for future switches.
                            # Preserve original title/type identity from blueprint.
                            regenerated["title"] = bw.get("title") or regenerated.get("title") or "Untitled"
                            if wtype:
                                regenerated["type"] = wtype
                            # Keep metadata durable for future switches
                            regenerated["origin_query"] = origin_query
                            rfc = regenerated.get("filter_context", {}) if isinstance(regenerated.get("filter_context", {}), dict) else {}
                            source_hint = str(fc.get("source") or rfc.get("source") or "widget_query").strip() or "widget_query"
                            rfc.update({"source": source_hint, "query": origin_query})
                            for k, v in fc.items():
                                if k not in rfc and v is not None:
                                    rfc[k] = v
                            regenerated["filter_context"] = rfc
                            cloned_count += 1
                            yield regenerated
                            continue
                    except Exception as qclone_err:
                        logger.warning(f"[clone_widgets] Query-clone fallback for '{shared_id}': {qclone_err}")

                # ── SUMMARY ──
                if wtype == "summary":
                    text = self._generate_executive_summary(fingerprint)
                    cloned_count += 1
                    yield {
                        "id": shared_id, "type": "summary",
                        "title": bw.get("title", "Executive Summary"),
                        "text": text, "icon": "file-text",
                        "gridW": gridW, "gridH": gridH,
                        "origin_query": "Dataset overview summary", "filter_context": {}
                    }

                # ── KPI ──
                elif wtype == "kpi":
                    # Try to find matching column via filter_context or title
                    hint_col = bw.get("filter_context", {}).get("column", "")
                    hint_agg = bw.get("filter_context", {}).get("agg", "")
                    if not hint_col:
                        hint_col = bw.get("origin_query", bw.get("title", ""))

                    # Special KPI types
                    title_lower = bw.get("title", "").lower()
                    origin_lower = str(bw.get("origin_query", "") or "").lower()

                    # Special: Column Count / Total Columns
                    if (
                        ("column" in title_lower and "count" in title_lower)
                        or "total columns" in title_lower
                        or "number of columns" in title_lower
                        or "column count" in origin_lower
                        or "total columns" in origin_lower
                    ):
                        cloned_count += 1
                        yield {
                            "id": shared_id, "type": "kpi",
                            "title": bw.get("title", "Column Count"),
                            "value": f"{len(self.df.columns):,}",
                            "subtitle": f"Across {len(self.df):,} records",
                            "trend": "neutral", "icon": "columns-3",
                            "gridW": gridW, "gridH": gridH,
                            "origin_query": bw.get("origin_query") or "column count",
                            "filter_context": bw.get("filter_context", {}) if isinstance(bw.get("filter_context", {}), dict) else {},
                        }
                        continue

                    if "record" in title_lower or "total record" in title_lower:
                        cloned_count += 1
                        yield {
                            "id": shared_id, "type": "kpi",
                            "title": bw.get("title", "Total Records"),
                            "value": f"{len(self.df):,}",
                            "subtitle": f"Across {len(self.df.columns)} columns",
                            "trend": "neutral", "icon": "database",
                            "gridW": gridW, "gridH": gridH,
                            "origin_query": bw.get("origin_query") or "record count",
                            "filter_context": bw.get("filter_context", {}) if isinstance(bw.get("filter_context", {}), dict) else {},
                        }
                        continue
                    if "mom" in title_lower or "growth" in title_lower:
                        if ti.get("mom_growth") is not None:
                            cloned_count += 1
                            yield {
                                "id": shared_id, "type": "kpi",
                                "title": "MoM Growth",
                                "value": f"{ti['mom_growth']:+.1f}%",
                                "subtitle": f"{self._title_case(ti.get('mom_measure', ''))} ({ti.get('latest_period', '')})",
                                "trend": "positive" if ti["mom_growth"] > 0 else "negative",
                                "icon": "trending-up" if ti["mom_growth"] > 0 else "trending-down",
                                "gridW": gridW, "gridH": gridH,
                                "origin_query": "MoM growth", "filter_context": {}
                            }
                        else:
                            cloned_count += 1
                            yield {
                                "id": shared_id, "type": "kpi",
                                "title": "MoM Growth",
                                "value": "N/A",
                                "subtitle": "No time data available",
                                "trend": "neutral", "icon": "minus",
                                "gridW": gridW, "gridH": gridH,
                                "origin_query": "MoM growth", "filter_context": {}
                            }
                        continue

                    m = _best_measure(hint_col)
                    if m:
                        agg = hint_agg if hint_agg in ("sum", "mean") else m.get("agg", "sum")
                        val = m.get("sum") if agg == "sum" else m.get("mean", 0)
                        display = self._format_kpi_value(val, m.get("format_hint", "number"), agg)
                        subtitle = self._format_kpi_subtitle(m)
                        cloned_count += 1
                        yield {
                            "id": shared_id, "type": "kpi",
                            "title": bw.get("title") or self._format_kpi_title({"col": m["col"], "agg": agg}),
                            "value": display, "subtitle": subtitle,
                            "trend": "neutral", "icon": self._pick_kpi_icon(m),
                            "gridW": gridW, "gridH": gridH,
                            "origin_query": bw.get("origin_query") or f"{agg} of {m['col']}",
                            "filter_context": {
                                **(bw.get("filter_context", {}) if isinstance(bw.get("filter_context", {}), dict) else {}),
                                "column": m["col"],
                                "agg": agg,
                            }
                        }
                    else:
                        cloned_count += 1
                        yield {
                            "id": shared_id, "type": "kpi",
                            "title": bw.get("title", "N/A"),
                            "value": "N/A", "subtitle": "No matching column",
                            "trend": "neutral", "icon": "minus",
                            "gridW": gridW, "gridH": gridH,
                            "origin_query": "", "filter_context": {}
                        }

                # ── LIST ──
                elif wtype == "list":
                    dim_hint = bw.get("filter_context", {}).get("column", "")
                    measure_hint = ""
                    # Try to extract measure from origin_query like "Top X by Y"
                    origin = bw.get("origin_query", bw.get("title", ""))
                    if " by " in origin.lower():
                        parts = origin.lower().split(" by ", 1)
                        if len(parts) == 2:
                            dim_hint = dim_hint or parts[0].replace("top ", "").strip()
                            measure_hint = parts[1].strip()

                    d = _best_dim(dim_hint)
                    m = _best_measure(measure_hint) if measure_hint else (measures[0] if measures else None)

                    if d and m:
                        d_col = d["col"]
                        m_col = m["col"]
                        agg = m.get("agg", "sum")
                        try:
                            grp = self.df.groupby(d_col)[m_col]
                            agg_series = grp.sum() if agg == "sum" else grp.mean()
                            top5 = agg_series.sort_values(ascending=False).head(5)
                            fmt_hint = m.get("format_hint", "number")
                            items = [{"label": str(k), "value": self._format_list_value(float(v), fmt_hint)}
                                     for k, v in top5.items()]
                        except Exception:
                            items = [{"label": "N/A", "value": "—"}]

                        agg_label = "Total" if agg == "sum" else "Avg"
                        m_title = self._title_case(m_col)
                        if agg_label == "Total" and m_title.lower().startswith("total"):
                            title = f"Top {self._title_case(d_col)} by {m_title}"
                        else:
                            title = f"Top {self._title_case(d_col)} by {agg_label} {m_title}"

                        cloned_count += 1
                        yield {
                            "id": shared_id, "type": "list",
                            "title": title, "items": items,
                            "icon": "trophy",
                            "gridW": gridW, "gridH": gridH,
                            "origin_query": f"Top {d_col} by {m_col}",
                            "filter_context": {"column": d_col}
                        }
                    else:
                        cloned_count += 1
                        yield {
                            "id": shared_id, "type": "list",
                            "title": bw.get("title", "Top Items"),
                            "items": [{"label": "N/A", "value": "—"}],
                            "icon": "list",
                            "gridW": gridW, "gridH": gridH,
                            "origin_query": "", "filter_context": {}
                        }

                # ── INSIGHT ──
                elif wtype == "insight":
                    # Lazy-generate insight pool on first insight widget
                    if _prebuilt_insights is None:
                        _prebuilt_insights = self._generate_data_insights(fingerprint)
                    # Use pre-built insight pool (consumed one-by-one)
                    if _prebuilt_insights:
                        ins = _prebuilt_insights.pop(0)
                        cloned_count += 1
                        yield {
                            "id": shared_id, "type": "insight",
                            "title": ins.get("title", bw.get("title", "Data Insight")),
                            "text": ins.get("text", ""),
                            "highlight": ins.get("highlight", ""),
                            "icon": ins.get("icon", "lightbulb"),
                            "gridW": gridW, "gridH": gridH,
                            "origin_query": "data insight", "filter_context": {}
                        }
                    else:
                        cloned_count += 1
                        yield {
                            "id": shared_id, "type": "insight",
                            "title": bw.get("title", "Data Insight"),
                            "text": "No matching insight could be generated for this dataset.",
                            "icon": "info", "gridW": gridW, "gridH": gridH,
                            "origin_query": "", "filter_context": {}
                        }

                # ── CHART ──
                elif wtype == "chart":
                    # Preserve Chart Builder widgets exactly (dimension/measure/agg) across file switches.
                    # Generic chart-pool matching can otherwise produce empty/mismatched charts.
                    origin_hint = str(bw.get("origin_query", "") or "").lower().strip()
                    is_chart_builder_blueprint = (
                        fc.get("source") == "chart_builder"
                        or str(bw.get("id", "")).startswith("cb-")
                        or origin_hint.startswith("chart builder:")
                    )
                    if is_chart_builder_blueprint:
                        chart_type = bw.get("chartType", "bar")
                        dim_hint = fc.get("column") or fc.get("dimension") or ""
                        if not dim_hint:
                            title_hint = str(bw.get("title", "") or "")
                            if " by " in title_hint.lower():
                                dim_hint = title_hint.rsplit(" by ", 1)[-1].strip()
                        measure_hint = fc.get("measure")
                        agg_hint = str(fc.get("agg") or fc.get("aggregation") or "sum").lower().strip()
                        if agg_hint == "avg":
                            agg_hint = "mean"
                        if agg_hint not in ("sum", "mean", "count"):
                            agg_hint = "sum"

                        d = _best_dim(dim_hint) if dim_hint else (dims[0] if dims else None)
                        m = None
                        if measure_hint and str(measure_hint) not in ("__count__", "count", "null", "none"):
                            m = _best_measure(str(measure_hint))

                        try:
                            if d is not None:
                                rebuilt = self.generate_custom_chart_widget(
                                    chart_type=chart_type,
                                    dimension=d["col"],
                                    measure=(m["col"] if m else None),
                                    aggregation=("count" if m is None else agg_hint),
                                )
                                rebuilt["id"] = shared_id
                                rebuilt["gridW"] = gridW
                                rebuilt["gridH"] = gridH
                                # Keep original filter context shape for future reloads
                                rebuilt["filter_context"] = {
                                    "column": d["col"],
                                    "measure": (m["col"] if m else "__count__"),
                                    "agg": ("count" if m is None else agg_hint),
                                    "source": "chart_builder",
                                }
                                cloned_count += 1
                                yield rebuilt
                                continue
                        except Exception as cb_err:
                            logger.warning(f"[clone_widgets] Chart Builder clone fallback for '{shared_id}': {cb_err}")

                    # Lazy-generate chart pool on first chart widget
                    if _prebuilt_charts is None:
                        _prebuilt_charts = self._generate_dashboard_charts(fingerprint)
                    chart_type = bw.get("chartType", "bar")
                    # Find best match by chart type from pre-built pool
                    match_chart = None
                    for ch in _prebuilt_charts:
                        if ch.get("chartType") == chart_type:
                            match_chart = ch
                            _prebuilt_charts.remove(ch)
                            break
                    if not match_chart and _prebuilt_charts:
                        match_chart = _prebuilt_charts.pop(0)

                    if match_chart:
                        match_chart["id"] = shared_id
                        match_chart["gridW"] = gridW
                        match_chart["gridH"] = gridH
                        cloned_count += 1
                        yield match_chart
                    else:
                        cloned_count += 1
                        yield {
                            "id": shared_id, "type": "chart",
                            "chartType": chart_type,
                            "title": bw.get("title", "Chart"),
                            "chartData": {"labels": [], "series": []},
                            "gridW": gridW, "gridH": gridH,
                            "origin_query": "", "filter_context": {}
                        }

                # ── UNKNOWN ──
                else:
                    # Pass through with a copy
                    fallback = dict(bw)
                    fallback["id"] = shared_id
                    cloned_count += 1
                    yield fallback

            except Exception as widget_err:
                logger.warning(f"[clone_widgets] Failed to clone widget '{shared_id}': {widget_err}")
                cloned_count += 1
                yield {
                    "id": shared_id, "type": wtype or "insight",
                    "title": bw.get("title", "Error"),
                    "text": f"Could not generate equivalent for this file.",
                    "gridW": gridW, "gridH": gridH,
                    "icon": "alert-circle",
                    "origin_query": "", "filter_context": {}
                }

        left_out = self._detect_compare_left_out(cloned, mode="split")
        self._last_clone_trace_info = self._strip_trace_none({
            "status": "success",
            "mode": "split",
            "counts": {
                "base_widgets": len(base_widgets),
                "cloned_widgets": len(cloned),
            },
            "widget_type_counts": self._widget_type_counts(cloned),
            "left_out_count": len(left_out),
            "left_out": left_out,
            "component_titles": [w.get("title", "Untitled") for w in cloned if isinstance(w, dict)],
            "component_types": [w.get("type", "unknown") for w in cloned if isinstance(w, dict)],
        })

        langfuse_context.update_current_observation(
            output={
                "status": "success",
                "mode": "split",
                "base_widget_count": len(base_widgets),
                "cloned_widget_count": len(cloned),
                "widget_type_counts": self._widget_type_counts(cloned),
                "left_out_count": len(left_out),
            }
        )

        logger.info(f"[clone_widgets] ✅ Cloned {len(cloned)} widgets for {self.filename}")
        return cloned

    def generate_single_widget(
        self,
        user_query: str,
        widget_type_hint: str | None = None,
        chart_type_hint: str | None = None,
        filter_context_hint: dict | None = None,
    ) -> dict:
        """
        Generate a single dashboard widget from a user's natural language query.
        Routes to interactive chart (with chartData for ApexCharts) or data widget based on query intent.
        """
        try:
            logger.info(f"🧩 Generating single widget for: {user_query}")
            
            columns = list(self.df.columns)
            numeric_cols, categorical_cols, _ = self._get_column_types()
            widget_type_hint = str(widget_type_hint or "").strip().lower()
            chart_type_hint = str(chart_type_hint or "").strip().lower()
            filter_context_hint = filter_context_hint if isinstance(filter_context_hint, dict) else {}

            # Hard guard: any chart metadata/hint must force chart path and never fall to pandas-agent list/KPI path.
            filter_chart_type_hint = str(filter_context_hint.get("chart_type") or "").strip().lower()
            source_hint = str(filter_context_hint.get("source") or "").strip().lower()
            force_chart_intent = (
                widget_type_hint == "chart"
                or bool(chart_type_hint)
                or bool(filter_chart_type_hint)
                or source_hint == "chart_builder"
            )
            if not chart_type_hint and filter_chart_type_hint:
                chart_type_hint = filter_chart_type_hint
            effective_query = user_query
            if force_chart_intent and not self._detect_chart_query(user_query):
                inferred_type = chart_type_hint or "bar"
                effective_query = f"{inferred_type} chart for {user_query}"
            
            # ===== CHECK IF THIS IS AN INSIGHT QUERY =====
            if not force_chart_intent and self._detect_insight_query(user_query):
                logger.info(f"[generate_single_widget] 💡 Insight query detected, generating data-driven insight widget")
                try:
                    # Same data-first approach as initial dashboard insights:
                    # 1. Smart fuzzy column matching from user query
                    # 2. Compute real stats from pandas (with group-by if categorical matched)
                    # 3. Enrich with LLM via _enrich_insight_with_llm (passing user query for context)
                    numeric_cols_list, cat_cols_list, _ = self._get_column_types()
                    raw_facts = []

                    # ── Smart fuzzy column matching ──
                    # Split query and column names into words and check overlap
                    import re as _re
                    query_words = set(_re.findall(r'[a-z0-9]+', user_query.lower()))
                    # Remove common stop words
                    _stop = {'the', 'a', 'an', 'of', 'in', 'for', 'and', 'or', 'to', 'with',
                             'is', 'are', 'was', 'were', 'be', 'show', 'me', 'give', 'get',
                             'tell', 'about', 'what', 'how', 'which', 'wise', 'by', 'per',
                             'based', 'on', 'data', 'insight', 'insights', 'analysis',
                             'analyze', 'summary', 'summarize', 'explain', 'please', 'can',
                             'you', 'i', 'my', 'this', 'that', 'it'}
                    query_words -= _stop

                    def _col_match_score(col_name: str) -> int:
                        """Score how well a column name matches the query words."""
                        col_words = set(_re.findall(r'[a-z0-9]+', col_name.lower()))
                        overlap = query_words & col_words
                        return len(overlap)

                    # Score all columns and pick best matches
                    scored_num = [(c, _col_match_score(c)) for c in numeric_cols_list]
                    scored_cat = [(c, _col_match_score(c)) for c in cat_cols_list]

                    # Filter to columns with at least 1 word overlap, sorted by score desc
                    relevant_num = [c for c, s in sorted(scored_num, key=lambda x: -x[1]) if s > 0]
                    relevant_cat = [c for c, s in sorted(scored_cat, key=lambda x: -x[1]) if s > 0]

                    logger.info(f"[generate_single_widget] Matched columns — num: {relevant_num[:3]}, cat: {relevant_cat[:2]}")

                    # Fallback to top columns only if nothing matched
                    if not relevant_num:
                        relevant_num = numeric_cols_list[:3]
                    if not relevant_cat:
                        relevant_cat = cat_cols_list[:2]

                    # Build raw fact block from actual data
                    raw_facts.append(f"User asked: \"{user_query}\"")
                    raw_facts.append(f"Dataset: {self.filename}, {len(self.df):,} rows, {len(self.df.columns)} columns.")

                    # If we have both a categorical and numeric match, do group-by analysis
                    if relevant_cat and relevant_num:
                        grp_col = relevant_cat[0]
                        for measure_col in relevant_num[:2]:
                            try:
                                grp = self.df.groupby(grp_col)[measure_col].agg(['sum', 'mean', 'count'])
                                grp = grp.sort_values('sum', ascending=False)
                                raw_facts.append(
                                    f"\n{self._title_case(measure_col)} breakdown by {self._title_case(grp_col)} "
                                    f"({self.df[grp_col].nunique()} categories):"
                                )
                                for cat_val, row in list(grp.iterrows())[:7]:
                                    raw_facts.append(
                                        f"  - {cat_val}: total={row['sum']:,.2f}, avg={row['mean']:,.2f}, count={int(row['count']):,}"
                                    )
                                # Concentration check
                                total = grp['sum'].sum()
                                if total > 0:
                                    top_share = (grp['sum'].iloc[0] / total * 100) if len(grp) > 0 else 0
                                    raw_facts.append(f"  Top category ({grp.index[0]}) holds {top_share:.1f}% of total {self._title_case(measure_col)}.")
                            except Exception:
                                pass

                    # Add overall stats for numeric columns
                    for col in relevant_num[:3]:
                        s = self.df[col].dropna()
                        if len(s) > 0:
                            raw_facts.append(
                                f"\nOverall {self._title_case(col)}: min={s.min():,.2f}, max={s.max():,.2f}, "
                                f"mean={s.mean():,.2f}, median={s.median():,.2f}, "
                                f"total={s.sum():,.2f}, records={len(s):,}."
                            )

                    # Add categorical distribution if only categorical matched (no numeric)
                    if relevant_cat and not [c for c, s in scored_num if s > 0]:
                        for col in relevant_cat[:2]:
                            vc = self.df[col].value_counts()
                            top5 = ", ".join(f"{k} ({v:,})" for k, v in list(vc.items())[:5])
                            raw_facts.append(
                                f"\n{self._title_case(col)}: {self.df[col].nunique()} unique values. "
                                f"Top entries: {top5}."
                            )

                    raw_text = " ".join(raw_facts)

                    # Build a descriptive title from matched columns
                    if relevant_cat and [c for c, s in scored_cat if s > 0]:
                        best_cat = relevant_cat[0]
                        if relevant_num and [c for c, s in scored_num if s > 0]:
                            title = f"{self._title_case(relevant_num[0])} by {self._title_case(best_cat)}"
                        else:
                            title = f"Insight: {self._title_case(best_cat)}"
                    elif relevant_num and [c for c, s in scored_num if s > 0]:
                        title = f"Insight: {self._title_case(relevant_num[0])}"
                    else:
                        title = f"Insight: {user_query[:40].strip()}"

                    # Enrich via same LLM path as initial insights
                    text = self._enrich_insight_with_llm(raw_text, title)

                    widget = {
                        "id": f"widget-insight-{uuid.uuid4().hex[:8]}",
                        "type": "insight",
                        "title": title,
                        "text": text,
                        "icon": "lightbulb",
                        "gridW": 6, "gridH": 2,
                        "origin_query": user_query,
                        "filter_context": {"source": "widget_query", "query": user_query}
                    }
                    logger.info(f"✅ Generated insight widget: {widget.get('title', 'Untitled')}")
                    return {"status": "success", "widget": widget}
                except Exception as insight_err:
                    logger.warning(f"[generate_single_widget] Insight generation failed: {insight_err}, falling back to regular widget")
            
            # ===== CHECK IF THIS IS A CHART QUERY =====
            if force_chart_intent or self._detect_chart_query(effective_query):
                logger.info(f"[generate_single_widget] 📊 Chart detected, generating interactive chartData")
                try:
                    chart_type = chart_type_hint or self._get_chart_type(effective_query)
                    logger.info(f"[generate_single_widget] Chart type detected: {chart_type}")

                    # Deterministic chart regeneration path for known chart-builder templates.
                    if (filter_context_hint.get("source") == "chart_builder") and filter_context_hint.get("column"):
                        try:
                            dimension = str(filter_context_hint.get("column") or "").strip()
                            measure = filter_context_hint.get("measure")
                            if isinstance(measure, str):
                                measure = measure.strip()
                            if measure in ("", "__count__", "count", "null", "none"):
                                measure = None

                            aggregation = str(filter_context_hint.get("agg") or filter_context_hint.get("aggregation") or "sum").strip().lower()
                            if aggregation == "avg":
                                aggregation = "mean"
                            if aggregation not in ("sum", "mean", "count"):
                                aggregation = "sum"

                            chart_widget = self.generate_custom_chart_widget(
                                chart_type=chart_type,
                                dimension=dimension,
                                measure=measure,
                                aggregation=("count" if measure is None else aggregation),
                            )
                            chart_widget["origin_query"] = user_query
                            chart_widget["filter_context"] = {
                                "source": "chart_builder",
                                "query": user_query,
                                "column": dimension,
                                "measure": (measure if measure is not None else "__count__"),
                                "agg": ("count" if measure is None else aggregation),
                            }
                            logger.info("[generate_single_widget] ✅ Used chart-builder blueprint path")
                            return {"status": "success", "widget": chart_widget}
                        except Exception as cb_err:
                            logger.warning(f"[generate_single_widget] Chart-builder blueprint failed, fallback to inferred chart path: {cb_err}")
                    
                    # Extract chart data using existing pandas-based method
                    chart_data = self._extract_chart_data(effective_query, chart_type)
                    
                    if not chart_data or not chart_data.get('data'):
                        logger.warning("[generate_single_widget] Failed to extract chart data, falling back to data widget")
                        raise ValueError("No chart data extracted")
                    
                    raw_data = chart_data.get('data', {})
                    chart_title = chart_data.get('title', user_query[:50])
                    logger.info(f"[generate_single_widget] Chart data extracted: keys={list(raw_data.keys())[:5]}")
                    
                    # ── Convert raw chart data to structured chartData for ApexCharts ──
                    labels = []
                    series = []
                    is_pie_type = chart_type in ('pie', 'donut', 'doughnut', 'polarArea')
                    
                    if isinstance(raw_data, dict):
                        if 'labels' in raw_data and 'datasets' in raw_data:
                            # Chart.js format: {labels: [...], datasets: [{data: [...], label: "..."}]}
                            labels = [str(l) for l in raw_data.get('labels', [])]
                            datasets = raw_data.get('datasets', [])
                            if is_pie_type:
                                series = [int(v) if isinstance(v, (int, float)) else 0 for v in (datasets[0].get('data', []) if datasets else [])]
                            else:
                                for ds in datasets:
                                    series.append({
                                        "name": ds.get('label', 'Value'),
                                        "data": [round(float(v), 2) if isinstance(v, (int, float)) else 0 for v in ds.get('data', [])]
                                    })
                        elif 'datasets' in raw_data and 'labels' not in raw_data:
                            # Scatter format or other
                            datasets = raw_data.get('datasets', [])
                            for ds in datasets:
                                points = ds.get('data', [])
                                if points and isinstance(points[0], dict) and 'x' in points[0]:
                                    labels = [str(p.get('x', '')) for p in points]
                                    series.append({
                                        "name": ds.get('label', 'Value'),
                                        "data": [round(float(p.get('y', 0)), 2) for p in points]
                                    })
                        else:
                            # Simple dict {key: value, ...}
                            labels = [str(k) for k in list(raw_data.keys())[:15]]
                            values = [round(float(v), 2) if isinstance(v, (int, float)) else 0 for v in list(raw_data.values())[:15]]
                            if is_pie_type:
                                series = [int(v) for v in values]
                            else:
                                series = [{"name": "Value", "data": values}]
                    elif isinstance(raw_data, list):
                        # List of dicts [{x: ..., y: ...}] or simple list
                        if raw_data and isinstance(raw_data[0], dict):
                            keys = list(raw_data[0].keys())
                            x_key = keys[0] if keys else 'x'
                            y_key = keys[1] if len(keys) > 1 else keys[0]
                            labels = [str(item.get(x_key, '')) for item in raw_data[:15]]
                            values = [round(float(item.get(y_key, 0)), 2) for item in raw_data[:15]]
                            if is_pie_type:
                                series = [int(v) for v in values]
                            else:
                                series = [{"name": self._title_case(y_key), "data": values}]
                    
                    if not labels or (not series):
                        raise ValueError("Could not convert chart data to labels/series")
                    
                    # Map chart type for ApexCharts
                    apex_chart_type = chart_type
                    if chart_type == 'doughnut':
                        apex_chart_type = 'donut'
                    
                    # Pick color theme based on chart type
                    color_map = {
                        'bar': 'indigo', 'line': 'rose', 'area': 'emerald', 'combo': 'mokkup1',
                        'pie': 'violet', 'donut': 'violet', 'doughnut': 'violet',
                        'scatter': 'cyan', 'bubble': 'cyan', 'polarArea': 'amber',
                        'histogram': 'indigo', 'funnel': 'holidaySpark', 'gauge': 'rustic',
                        'heatmap': 'mokkup2', 'treemap': 'emerald', 'waterfall': 'holidaySpark'
                    }
                    
                    is_horizontal = 'horizontal' in effective_query.lower() or 'sideways' in effective_query.lower()
                    
                    chart_widget = {
                        "id": f"widget-chart-{uuid.uuid4().hex[:8]}",
                        "type": "chart",
                        "chartType": apex_chart_type,
                        "title": chart_title,
                        "chartData": {
                            "labels": labels,
                            "series": series
                        },
                        "horizontal": is_horizontal,
                        "colorTheme": color_map.get(apex_chart_type, 'indigo'),
                        "gridW": 6,
                        "gridH": 3,
                        "icon": "bar-chart-3",
                        "origin_query": user_query,
                        "filter_context": {"source": "widget_query", "query": user_query, "chart_type": apex_chart_type}
                    }
                    
                    logger.info(f"✅ Generated interactive chart widget: {chart_widget['title']} ({apex_chart_type}, {len(labels)} labels)")
                    return {"status": "success", "widget": chart_widget}
                    
                except Exception as chart_err:
                    logger.warning(f"[generate_single_widget] Chart generation failed: {chart_err}, falling back to data widget")
                    # Fall through to regular data widget generation
            
            # ===== REGULAR DATA WIDGET GENERATION (KPI/List/Insight) =====
            raw_answer = None
            agent_ready = self._ensure_pandas_agent()
            
            # Step 1: Try the pandas agent to compute the answer
            try:
                if not agent_ready:
                    raise RuntimeError("Pandas agent unavailable for this file context")

                compute_prompt = f"""Compute the answer to this question about the dataframe `df`:
"{user_query}"

Rules:
- Output ONLY the computed result (a number, a list, or a short text).
- If it's a single number, just print the number.
- If it's a top-N list, print a Python list of tuples: [("label", value), ...]
- Do NOT print explanations.
"""
                response = self.pandas_agent.invoke({"input": compute_prompt})
                raw_answer = str(response.get('output', '')).strip()
                logger.info(f"[generate_single_widget] ✅ Agent computed answer: {raw_answer[:200]}")
            except Exception as agent_err:
                logger.warning(f"[generate_single_widget] ⚠️ Agent failed, falling back to LLM-only: {agent_err}")
                # Fallback: build a quick data summary and let LLM answer directly
                self._ensure_llm()
                dataset_summary = self._build_dataset_summary()
                
                fallback_prompt = f"""Answer this question about a dataset:
Question: "{user_query}"

Dataset summary:
{dataset_summary}

Provide a concise factual answer based on the data summary above. If it's a count or aggregation, compute it from the provided stats. Be specific with numbers."""
                
                raw_answer = invoke_llm_with_retry(self.llm, fallback_prompt, max_retries=2, context_name="Widget fallback computation")
                logger.info(f"[generate_single_widget] ✅ LLM fallback answer: {raw_answer[:200]}")
            
            # Now ask LLM to format this as a widget JSON
            format_prompt = f"""Convert this data query result into a dashboard widget JSON object.

USER QUERY: "{user_query}"
COMPUTED ANSWER: {raw_answer}
AVAILABLE COLUMNS: {', '.join(columns)}

Return ONE JSON object (not an array) matching one of these formats:

If the answer is a single number/metric:
{{"type": "kpi", "title": "Short Title", "value": "formatted_value", "subtitle": "context", "trend": "neutral", "icon": "lucide-icon-name", "gridW": 3, "gridH": 1}}

If the answer is a list/ranking:
{{"type": "list", "title": "Short Title", "items": [{{"label": "Item", "value": "123"}}], "icon": "lucide-icon-name", "gridW": 4, "gridH": 2}}

If the answer is a text insight:
{{"type": "insight", "title": "Short Title", "text": "The insight text here...", "icon": "lightbulb", "gridW": 4, "gridH": 1}}

Rules:
- Use the COMPUTED ANSWER as the real data. Never make up values.
- Format numbers with commas and appropriate symbols ($, %, etc.).
- Choose an appropriate lucide icon name.
- Return ONLY the JSON object, no markdown fences, no extra text.
"""
            
            widget_response = invoke_llm_with_retry(self.llm, format_prompt, max_retries=2, context_name="Widget formatting")
            widget_response = self._clean_llm_json(widget_response)
            
            widget = json.loads(widget_response)
            expected_type = widget_type_hint if widget_type_hint in {"kpi", "list", "insight", "summary"} else ""
            actual_type = str(widget.get("type", "") or "").strip().lower()
            if expected_type and actual_type and actual_type != expected_type:
                logger.warning(
                    f"[generate_single_widget] Type mismatch (expected={expected_type}, got={actual_type}); coercing to expected type"
                )
                if expected_type == "kpi":
                    widget = {
                        "type": "kpi",
                        "title": widget.get("title") or "Metric",
                        "value": str(widget.get("value") or raw_answer or "N/A"),
                        "subtitle": widget.get("subtitle") or "Computed from selected file",
                        "trend": widget.get("trend") or "neutral",
                        "icon": widget.get("icon") or "bar-chart-3",
                        "gridW": widget.get("gridW", 3),
                        "gridH": widget.get("gridH", 1),
                    }
                elif expected_type == "list":
                    widget = {
                        "type": "list",
                        "title": widget.get("title") or "Top Items",
                        "items": widget.get("items") if isinstance(widget.get("items"), list) and widget.get("items") else [{"label": "Result", "value": str(raw_answer or "N/A")}],
                        "icon": widget.get("icon") or "list",
                        "gridW": widget.get("gridW", 4),
                        "gridH": widget.get("gridH", 2),
                    }
                elif expected_type == "insight":
                    widget = {
                        "type": "insight",
                        "title": widget.get("title") or "Insight",
                        "text": str(widget.get("text") or raw_answer or "No insight available"),
                        "icon": widget.get("icon") or "lightbulb",
                        "gridW": widget.get("gridW", 4),
                        "gridH": widget.get("gridH", 1),
                    }

            if str(widget.get("type", "")).strip().lower() == "kpi":
                widget["value"] = self._normalize_kpi_display_value(widget.get("value"))
                if widget.get("compare_value") is not None:
                    widget["compare_value"] = self._normalize_kpi_display_value(widget.get("compare_value"))

            widget['id'] = f"widget-custom-{uuid.uuid4().hex[:8]}"
            widget.setdefault('gridW', 3)
            widget.setdefault('gridH', 1)
            widget.setdefault('icon', 'bar-chart-3')
            widget['origin_query'] = user_query
            fc = widget.get('filter_context', {}) if isinstance(widget.get('filter_context', {}), dict) else {}
            source_hint = str(filter_context_hint.get("source") or fc.get("source") or "widget_query").strip() or "widget_query"
            fc.update({"source": source_hint, "query": user_query})
            for key, value in filter_context_hint.items():
                if key not in fc and value is not None:
                    fc[key] = value
            widget['filter_context'] = fc
            
            logger.info(f"✅ Generated custom widget: {widget.get('title', 'Untitled')}")
            return {"status": "success", "widget": widget}
            
        except Exception as e:
            log_full_exception(e, "Single widget generation error")
            return {
                "status": "error",
                "widget": {
                    "id": f"widget-error-{uuid.uuid4().hex[:8]}",
                    "type": "insight",
                    "title": "Generation Failed",
                    "text": f"Could not compute: {user_query}. Please try rephrasing.",
                    "icon": "alert-circle",
                    "gridW": 4,
                    "gridH": 1
                }
            }

