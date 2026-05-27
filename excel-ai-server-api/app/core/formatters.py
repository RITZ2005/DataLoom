"""
Formatters & display helpers mixin for HybridAgent.

Extracted from agent.py — contains all response formatting,
KPI helpers, CSV preview, and LLM humanization methods.
"""
from __future__ import annotations

import re
import json
from datetime import datetime
from typing import Any, Optional

import numpy as np
import pandas as pd

from app.utils.logging import logger, log_full_exception
from app.core.llm import invoke_llm_with_retry
from app.config import observe, langfuse_context


class FormattersMixin:
    """Mixin providing response formatting, KPI display, and humanization methods."""

    # ========================================================================
    # DISPLAY FORMATTING HELPER
    # ========================================================================
    def _format_dataframe_for_display(self, df):
        """
        Format DataFrame for display: converts dates and percentages to readable format.
        Returns a copy of the DataFrame with formatting applied.
        """
        df_formatted = df.copy()
        
        for col in df_formatted.columns:
            # Convert datetime columns to date-only strings (YYYY-MM-DD)
            if pd.api.types.is_datetime64_any_dtype(df_formatted[col]):
                df_formatted[col] = df_formatted[col].dt.strftime('%Y-%m-%d')
            
            # Convert percentage columns (0-1 range) to actual percentages (e.g., 0.15 → "15%")
            elif pd.api.types.is_numeric_dtype(df_formatted[col]):
                non_null_values = df_formatted[col].dropna()
                if len(non_null_values) > 0:
                    # Check if all non-null values are between 0 and 1 (inclusive)
                    if ((non_null_values >= 0) & (non_null_values <= 1)).all():
                        # Convert to percentage strings
                        df_formatted[col] = df_formatted[col].apply(
                            lambda x: f"{x * 100:.1f}%" if pd.notna(x) else None
                        )
        
        return df_formatted

    @staticmethod
    def _title_case(s: str) -> str:
        """Convert snake_case / kebab-case to Title Case."""
        return s.replace('_', ' ').replace('-', ' ').title()

    @staticmethod
    def _format_kpi_value(val: float, format_hint: str = "number", agg: str = "sum") -> str:
        """Format a KPI display value — always show full accurate numbers."""
        if format_hint == "currency":
            if abs(val) >= 1e6:
                return f"₹{val:,.0f}"
            return f"₹{val:,.2f}"
        if format_hint == "percentage":
            return f"{val:.1f}%"
        # Plain number — full display, no abbreviation
        if agg == "mean":
            if abs(val) >= 1e6: return f"{val:,.0f}"
            return f"{val:,.2f}"
        # Sum — full display
        if val == int(val) and abs(val) < 1e12:
            return f"{int(val):,}"
        if abs(val) >= 1e6: return f"{val:,.0f}"
        return f"{val:,.2f}"

    @staticmethod
    def _parse_numeric_token(value: Any) -> tuple[Optional[float], int]:
        """Parse localized numeric text and return (float_value, fraction_digits)."""
        if value is None:
            return None, 0
        if isinstance(value, (int, float)):
            num = float(value)
            if not np.isfinite(num):
                return None, 0
            text = str(value)
            dot = text.find('.')
            return num, (len(text) - dot - 1) if dot >= 0 else 0

        text = str(value).strip()
        if not text:
            return None, 0

        m = re.search(r"[-+]?\d[\d.,\s]*", text)
        if not m:
            return None, 0

        token = m.group(0).replace(' ', '')
        if not token:
            return None, 0

        has_dot = '.' in token
        has_comma = ',' in token

        if has_dot and has_comma:
            if token.rfind(',') > token.rfind('.'):
                token = token.replace('.', '').replace(',', '.')
            else:
                token = token.replace(',', '')
        elif has_comma:
            if re.fullmatch(r"[-+]?\d{1,3}(,\d{3})+", token):
                token = token.replace(',', '')
            elif re.fullmatch(r"[-+]?\d+,\d+", token):
                token = token.replace(',', '.')
            else:
                token = token.replace(',', '')
        elif has_dot:
            if re.fullmatch(r"[-+]?\d{1,3}(\.\d{3})+", token):
                token = token.replace('.', '')

        try:
            num = float(token)
        except Exception:
            return None, 0

        if not np.isfinite(num):
            return None, 0

        dot = token.find('.')
        frac = (len(token) - dot - 1) if dot >= 0 else 0
        return num, max(0, frac)

    @staticmethod
    def _normalize_kpi_display_value(value: Any) -> str:
        """Normalize KPI numeric display using decimal point and thousand separators."""
        if value is None:
            return "N/A"

        raw = str(value).strip()
        if not raw:
            return "N/A"

        # NOTE: We call through the class directly since this is a static method
        # that needs to call another static method. At runtime, the actual class
        # (HybridAgent) will be used via MRO.
        from app.core.formatters import FormattersMixin
        parsed, fraction_digits = FormattersMixin._parse_numeric_token(raw)
        if parsed is None:
            return raw

        decimals = min(max(fraction_digits, 0), 3)
        if decimals == 0 and not float(parsed).is_integer():
            decimals = 2

        is_percent = '%' in raw
        currency_match = re.search(r"[₹$€£]", raw)
        currency_symbol = currency_match.group(0) if currency_match else ""

        formatted = f"{parsed:,.{decimals}f}"
        if is_percent:
            return f"{formatted}%"
        if currency_symbol:
            return f"{currency_symbol}{formatted}"
        return formatted

    @staticmethod
    def _format_kpi_subtitle(m: dict) -> str:
        """Generate a context-appropriate subtitle for a KPI widget."""
        agg = m.get("agg", "sum")
        fmt = m.get("format_hint", "number")
        if agg == "mean":
            return "Average value"
        if agg == "sum":
            if fmt == "currency":
                return "Total amount"
            return "Total value"
        return f"{agg.title()} value"

    @staticmethod
    def _pick_kpi_icon(m: dict) -> str:
        """Pick an appropriate icon for a KPI based on column hints."""
        fmt = m.get("format_hint", "number")
        col_lower = m.get("col", "").lower()
        if fmt == "currency":
            return "dollar-sign"
        if fmt == "percentage":
            return "percent"
        if any(h in col_lower for h in ['age', 'experience', 'tenure', 'years']):
            return "users"
        if any(h in col_lower for h in ['count', 'quantity', 'num', 'orders']):
            return "hash"
        return "bar-chart-2"

    def _get_column_types(self) -> tuple:
        """Return (numeric_cols, categorical_cols, datetime_cols) lists — single source of truth."""
        numeric = self.df.select_dtypes(include='number').columns.tolist()
        categorical = self.df.select_dtypes(include=['object', 'category']).columns.tolist()
        datetime_cols = self.df.select_dtypes(include=['datetime64', 'datetime']).columns.tolist()
        return numeric, categorical, datetime_cols

    @staticmethod
    def _clean_llm_json(text: str) -> str:
        """Strip markdown code-fence wrappers from LLM JSON output."""
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r'^```\w*\n?', '', text)
            text = re.sub(r'\n?```$', '', text)
        return text.strip()

    def _build_response_envelope(self, widgets: list, fingerprint: dict | None = None) -> dict:
        """Standard dashboard response dict."""
        return {
            "status": "success",
            "filename": self.filename,
            "file_uuid": self.file_uuid,
            "total_rows": len(self.df) if self.df is not None else (fingerprint.get("total_rows", 0) if fingerprint else 0),
            "total_columns": len(self.df.columns) if self.df is not None else (fingerprint.get("total_columns", 0) if fingerprint else 0),
            "widgets": widgets,
            "fingerprint": fingerprint or {},
        }

    def _build_dataset_summary(self, max_numeric: int = 8, max_categorical: int = 6) -> str:
        """Build a reusable dataset summary string for LLM prompts."""
        columns = list(self.df.columns)
        row_count = len(self.df)
        numeric_cols, categorical_cols, date_cols = self._get_column_types()

        parts = [
            f"Total rows: {row_count}",
            f"Columns ({len(columns)}): {', '.join(columns)}",
            f"Numeric columns: {', '.join(numeric_cols) if numeric_cols else 'None'}",
            f"Categorical columns: {', '.join(categorical_cols) if categorical_cols else 'None'}",
            f"Date columns: {', '.join(date_cols) if date_cols else 'None'}",
        ]

        for col in numeric_cols[:max_numeric]:
            try:
                stats = self.df[col].describe()
                parts.append(f"  {col}: min={stats['min']}, max={stats['max']}, mean={stats['mean']:.2f}")
            except Exception:
                pass

        for col in categorical_cols[:max_categorical]:
            try:
                nunique = self.df[col].nunique()
                top_values = self.df[col].value_counts().head(5).to_dict()
                parts.append(f"  {col}: {nunique} unique values, top: {top_values}")
            except Exception:
                pass

        return "\n".join(parts)

    @staticmethod
    def _format_kpi_title(m: dict) -> str:
        """Generate a clean display title for a KPI widget from a measure dict."""
        col = m.get("col", "Metric")
        agg = m.get("agg", "sum")
        title = FormattersMixin._title_case(col)
        agg_label = "Total" if agg == "sum" else ("Avg" if agg == "mean" else agg.title())
        # Avoid "Total Total Applications" duplication
        if agg_label == "Total" and title.lower().startswith("total"):
            return title
        if agg_label == "Avg" and (title.lower().startswith("average") or title.lower().startswith("avg")):
            return title
        return f"{agg_label} {title}"

    @staticmethod
    def _format_list_value(val: float, format_hint: str = "number") -> str:
        """Format a value for list widget display."""
        if format_hint == "currency":
            return f"₹{val:,.0f}" if abs(val) >= 1000 else f"₹{val:,.2f}"
        if format_hint == "percentage":
            return f"{val:.1f}%"
        if val == int(val):
            return f"{int(val):,}"
        return f"{val:,.2f}"

    def _parse_list_string(self, dict_data: str):
        """Parse a stringified list (of dicts or simple values) into a Python object."""
        try:
            dict_data = dict_data.strip()

            if '[' in dict_data:
                start_idx = dict_data.index('[')
                dict_data = dict_data[start_idx:]
                logger.info(f"✂️ Extracted list portion starting at index {start_idx}")

            safe_dict = {'Timestamp': pd.Timestamp, 'NaT': pd.NaT, 'nan': np.nan, 'NaN': np.nan}
            parsed = eval(dict_data, {"__builtins__": {}}, safe_dict)
            logger.info(f"✅ Parsed successfully using eval() - got {type(parsed)}")
            return parsed
        except Exception as parse_err:
            log_full_exception(parse_err, "Parse failed during _parse_list_string")
            logger.error("Data sample: %s", str(dict_data)[:500])
            return None

    def _convert_dict_to_csv_preview(self, query, dict_data):
        """Convert dictionary to CSV file and return preview with download link."""
        try:
            logger.info(f"🔄 CSV Conversion - Input type: {type(dict_data)}, Length: {len(str(dict_data)[:100])}")
            
            # Parse if string - try to extract just the list part
            if isinstance(dict_data, str):
                dict_data = self._parse_list_string(dict_data)
                if dict_data is None:
                    return None
            
            if not isinstance(dict_data, list) or len(dict_data) == 0:
                logger.warning(f"⚠️ Not a valid list. Type: {type(dict_data)}, Length: {len(dict_data) if isinstance(dict_data, list) else 'N/A'}")
                return None

            if len(dict_data) == 1 and isinstance(dict_data[0], dict):
                logger.info("📋 Single-entry list detected in CSV conversion - formatting as single entity profile")
                return self._generate_profile_response(query, dict_data[0])
            
            # CASE 1: List of dicts (multi-column data)
            if isinstance(dict_data[0], dict):
                logger.info(f"✅ Detected list of dicts - creating multi-column DataFrame")
                df_result = pd.DataFrame(dict_data)
                total_rows = len(df_result)
                logger.info(f"✅ DataFrame created: {total_rows} rows × {len(df_result.columns)} columns")
            
            # CASE 2: Simple list (strings/numbers) - convert to single-column DataFrame
            else:
                logger.info(f"✅ Detected simple list - {len(dict_data)} items. Converting to single-column format")
                
                # Extract column name from query
                column_name = "value"  # default
                query_lower = query.lower()
                if "name" in query_lower:
                    column_name = "name"
                elif "id" in query_lower:
                    column_name = "id"
                elif "code" in query_lower:
                    column_name = "code"
                elif "district" in query_lower or "location" in query_lower:
                    column_name = "district"
                
                # Convert simple list to DataFrame with single column
                df_result = pd.DataFrame({column_name: [str(item) for item in dict_data]})
                total_rows = len(df_result)
                logger.info(f"✅ Single-column DataFrame created: {total_rows} rows")
            
            # Apply formatting for dates and percentages BEFORE null handling
            df_result = self._format_dataframe_for_display(df_result)
            
            # ---------------------------------------------------------
            # SAFE NULL/NaN HANDLING (After formatting)
            # ---------------------------------------------------------
            # Force entire DataFrame to Object type
            df_result = df_result.astype(object)
           
            # Universal Replace: Handles np.nan → "None" string for display
            df_result = df_result.where(pd.notnull(df_result), "None")
            
            # Clean up string representations of null values (e.g., "NaT", "nan") → show as "None"
            null_strings = {"NaT", "nan", "NaN", "null", "NAT"}
            df_result = df_result.replace(null_strings, "None")
            
            # Generate CSV filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            csv_filename = f"export_{timestamp}.csv"
            
            # Convert FULL data to CSV string (ALL rows for download)
            csv_content = df_result.to_csv(index=False, encoding='utf-8')
            logger.info(f"💾 Generated CSV with ALL {total_rows} rows (not limited)")
            
            # Create preview (ONLY first 10 rows) for display in chat
            preview_df = df_result.head(10)
            preview_data = preview_df.to_dict(orient='records')
            
            # Full data for CSV download (ALL rows)
            full_data_all = df_result.to_dict(orient='records')
            columns = list(df_result.columns)
            
            logger.info(f"📊 Preview: showing {len(preview_data)} rows, Full data: {len(full_data_all)} rows")
            
            # Return table format with CSV download
            response_data = {
                "type": "table",
                "columns": columns,
                "data": preview_data,  # Only first 10 rows for table display
                "full_data": full_data_all,  # ALL rows for CSV download
                "total_rows": total_rows,
                "displayed_rows": len(preview_data),
                "has_more": total_rows > 10,
                "message": f"Showing {len(preview_data)} of {total_rows} records. Download CSV for all {total_rows} rows.",
                "csv_download": {
                    "filename": csv_filename,
                    "content": csv_content  # Full CSV with ALL rows (alternative format)
                }
            }
            
            return json.dumps(response_data)
            
        except Exception as e:
                log_full_exception(e, "CSV conversion error")
                return None

    def _humanize_response(self, query, raw_answer, intermediate_steps):
        """
        Transforms raw data into a professional, human-readable Data Analyst response.
        Intelligently distinguishes between Single Profiles, Lists, and Scalar Metrics.
        """
        try:
            # 1. FAST PATH: TYPE CHECKING (Most Reliable)
            # If we already have a dictionary, it IS a profile. No string parsing needed.
            if isinstance(raw_answer, dict):
                logger.info("📋 Detected Dict Type -> Formatting as single entity profile")
                return self._generate_profile_response(query, raw_answer)

            # 2. String Cleanup
            answer_str = str(raw_answer).strip()
            answer_str = re.sub(r'\bNaT\b', 'None', answer_str)
            answer_str = re.sub(r'\bnan\b', 'None', answer_str)
            answer_str = re.sub(r'\bNaN\b', 'None', answer_str)
            answer_str = re.sub(r'dtype: \w+', '', answer_str)

            # 3. DETECT SHAPE (Robust Logic)
            
            # Case A: JSON Object String (Starts/Ends with curly braces)
            is_json_string = answer_str.startswith('{') and answer_str.endswith('}')
            
            # Case B: Key-Value Text (e.g. "Age: 30\nCity: NY") - Heuristic check
            # It has colons, newlines, but NO pipe characters (which indicate tables)
            is_key_value_text = (
                ":" in answer_str and 
                "\n" in answer_str and 
                "|" not in answer_str and 
                answer_str.count(':') >= 2 # At least 2 fields
            )

            # Case C: Markdown Table or List of dicts
            is_list_or_table = (
                ("|" in answer_str and "-|-" in answer_str) or  # Markdown table
                (answer_str.startswith('[') and "{" in answer_str) # JSON List of dicts
            )

            # Case D: Simple list of scalar values (e.g. ['name1', 'name2', ...])
            # Catches lists of strings/numbers that contain no dict structure
            is_simple_list = (
                answer_str.startswith('[') and
                answer_str.endswith(']') and
                not is_list_or_table
            )

            # 4. ROUTING LOGIC
            if is_json_string or is_key_value_text:
                logger.info("📋 Detected Profile String -> Formatting single entity")
                return self._generate_profile_response(query, answer_str)

            elif is_list_or_table:
                logger.info("📊 Detected List/Table (of dicts) -> Formatting mini-report")
                return self._generate_report_response(query, answer_str)

            elif is_simple_list:
                logger.info("📝 Detected Simple List -> Formatting named list response")
                return self._generate_list_response(query, answer_str)

            else:
                logger.info("💬 Detected Scalar/Text -> Formatting direct answer")
                return self._generate_scalar_response(query, answer_str)

        except Exception as e:
            log_full_exception(e, "Error humanizing response")
            return str(raw_answer)

    # =========================================================================
    # HELPER METHODS FOR PROMPT GENERATION (Keeps main function clean)
    # =========================================================================

    def _generate_list_response(self, query, data):
        """Format a simple list of scalar values (names, IDs, etc.) as a clean readable answer."""
        prompt = f"""
        You are a Data Analyst presenting query results.

        ⚠️ CRITICAL RULE: The INPUT DATA below is the CORRECT, ALREADY COMPUTED answer produced
        by a data engine running directly against the actual dataset.
        Your ONLY job is to present it clearly and professionally.
        NEVER question, re-evaluate, or say you cannot determine the answer.
        NEVER say "data is insufficient" or "I cannot determine" — the INPUT DATA IS the complete answer.

        INPUT DATA (this IS the answer): {data}
        USER QUERY: "{query}"

        INSTRUCTIONS:
        1. **Opening sentence**: One sentence contextualizing the results relative to the query
           (e.g., "The following 8 employees earn the maximum bonus:").
        2. **Format**: Present each item as a clean numbered list.
        3. **Count**: Always mention the total count of items.
        """
        try:
            return invoke_llm_with_retry(self.llm, prompt, max_retries=2, context_name="List response formatting")
        except Exception:
            logger.warning("⚠️ List response formatting failed, returning raw data")
            return data

    def _generate_profile_response(self, query, data):
        prompt = f"""
        You are a Data Analyst presenting a detailed entity profile.
        The user asked about a specific record (person, product, transaction).

        ⚠️ CRITICAL RULE: The INPUT DATA below is the CORRECT, ALREADY COMPUTED result from
        the data engine. Your ONLY job is to present it. Do NOT question or re-evaluate it.
        
        INPUT DATA: {data}
        USER QUERY: "{query}"
        
        INSTRUCTIONS:
        1. **Structure**: Organize fields into logical sections (e.g., ### 👤 Details, ### 📊 Metrics).
        2. **Formatting**: Use a clean bulleted list for every field.
        3. **Highlighting**: **Bold** field labels (e.g., - **Salary:** $50,000).
        4. **Cleanup**: Filter out internal IDs (like '_id') unless relevant.
        5. **No Fluff**: Do not say "Here is the profile". Just give the markdown.
        """
        langfuse_context.update_current_observation(
            input={"query": query, "prompt": prompt.strip()},
            tags=["humanize", "profile"],
        )
        try:
            try:
                lf_cb = langfuse_context.get_current_langchain_handler()
                _prof_cbs = [lf_cb] if lf_cb else None
            except Exception:
                _prof_cbs = None
            result = invoke_llm_with_retry(
                self.llm, prompt, max_retries=2, context_name="Profile formatting",
                callbacks=_prof_cbs,
            )
            langfuse_context.update_current_observation(output={"response_preview": (result or "")[:300]})
            return result
        except Exception:
            logger.warning("⚠️ Profile formatting failed, returning raw data")
            return data

    @observe(name="llm.humanize.report")
    def _generate_report_response(self, query, data):
        prompt = f"""
        You are a Data Analyst presenting a mini-report or ranking.

        ⚠️ CRITICAL RULE: The INPUT DATA below is the CORRECT, ALREADY COMPUTED result from
        the data engine. Your ONLY job is to present it. Do NOT question or re-evaluate it.
        NEVER say "I cannot determine" — the INPUT DATA IS the complete answer.
        
        INPUT DATA: {data}
        USER QUERY: "{query}"
        
        INSTRUCTIONS:
        1. **Format**: Use a clean Markdown Table for comparisons.
        2. **Rankings**: If it's a "Top X" list, use a numbered list with **bold** metrics.
        3. **Context**: Start with a 1-sentence summary of what the data shows.
        """
        langfuse_context.update_current_observation(
            input={"query": query, "prompt": prompt.strip()},
            tags=["humanize", "report"],
        )
        try:
            try:
                lf_cb = langfuse_context.get_current_langchain_handler()
                _rpt_cbs = [lf_cb] if lf_cb else None
            except Exception:
                _rpt_cbs = None
            result = invoke_llm_with_retry(
                self.llm, prompt, max_retries=2, context_name="Report formatting",
                callbacks=_rpt_cbs,
            )
            langfuse_context.update_current_observation(output={"response_preview": (result or "")[:300]})
            return result
        except Exception:
            logger.warning("⚠️ Report formatting failed, returning raw data")
            return data

    @observe(name="llm.humanize.scalar")
    def _generate_scalar_response(self, query, data):
        prompt = f"""
        You are a Data Analyst giving a direct, verbal answer.

        ⚠️ CRITICAL RULE: The INPUT DATA below is the CORRECT, ALREADY COMPUTED answer from
        the data engine. Your ONLY job is to present it clearly.
        NEVER question, verify, or re-evaluate it. NEVER say "I cannot determine" or
        "data is insufficient" — the INPUT DATA IS the complete answer.
        
        INPUT DATA (this IS the answer): {data}
        USER QUERY: "{query}"
        
        INSTRUCTIONS:
        1. **Sentence Wrapper**: Wrap the value in a complete professional sentence that directly
           answers the user's query (e.g., "The total revenue is **$50,000**.").
        2. **Formatting**: Format numbers (commas, currency symbols) correctly.
        3. **Context**: Relate the answer back to the user's query.
        """
        langfuse_context.update_current_observation(
            input={"query": query, "prompt": prompt.strip()},
            tags=["humanize", "scalar"],
        )
        try:
            try:
                lf_cb = langfuse_context.get_current_langchain_handler()
                _scl_cbs = [lf_cb] if lf_cb else None
            except Exception:
                _scl_cbs = None
            result = invoke_llm_with_retry(
                self.llm, prompt, max_retries=2, context_name="Scalar response formatting",
                callbacks=_scl_cbs,
            )
            langfuse_context.update_current_observation(output={"response_preview": (result or "")[:300]})
            return result
        except Exception:
            logger.warning("⚠️ Scalar response formatting failed, returning raw data")
            return data
