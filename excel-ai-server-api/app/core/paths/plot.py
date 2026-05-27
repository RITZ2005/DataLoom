"""
Plot path mixin for HybridAgent.

Extracted from agent.py — handles chart type detection, data extraction,
chart insights generation, and the plot execution path.
"""
from __future__ import annotations

import json
import warnings

import numpy as np
import pandas as pd

from app.utils.logging import logger, log_full_exception
from app.config import observe, langfuse_context


class PlotPathMixin:
    """Mixin providing chart/plot detection, data extraction, and the plot execution path."""

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

    @observe(name="llm.chart_data_extraction")
    def _extract_chart_data(self, query, chart_type):
        """Extract chart data intelligently from DataFrame"""
        try:
            logger.info("Extracting chart data from DataFrame...")
            langfuse_context.update_current_observation(
                input={"query": query, "chart_type": chart_type},
                metadata={"file_uuid": self.file_uuid, "filename": self.filename},
                tags=["chart-extraction"],
            )
            
            # Step 1: Use LLM to understand what to visualize
            columns_str = ", ".join(self.df.columns)
            
            # Check if this is a scatter plot query
            is_scatter = any(keyword in query.lower() for keyword in ['scatter', 'correlation', 'relationship', 'vs ', 'versus', 'against', 'by vs'])
            
            # Check if this is a pie/doughnut chart query
            is_pie_doughnut_polar = any(keyword in query.lower() for keyword in ['pie', 'doughnut', 'donut', 'polar', 'polar area', 'distribution', 'breakdown', 'proportion', 'radial'])
            
            if is_scatter:
                column_identification_prompt = f"""
You are a data analysis expert. Given a user query and available columns, identify TWO columns for a scatter plot.

Available columns: {columns_str}

User Query: {query}

Task: Respond with ONLY a JSON object (no markdown, no explanation) with this structure:
{{"x_column": "column_name", "y_column": "column_name"}}

For scatter plots, identify:
- x_column: The independent variable (horizontal axis) - usually what you measure against
- y_column: The dependent variable (vertical axis) - usually what changes as a result
- Both should be numeric columns

Generic Guidelines:
- Look for patterns like "column_A vs column_B" or "column_A against column_B"
- Usually the second column is the y_axis and first is x_axis
- Both columns must have numeric values

Examples (dataset-agnostic):
- Query: "scatter plot of column A versus column B" → {{"x_column": "A", "y_column": "B"}}
- Query: "show correlation between column X and column Y" → {{"x_column": "X", "y_column": "Y"}}
- Query: "column1 vs column2 scatter" → {{"x_column": "column1", "y_column": "column2"}}
- Query: "relationship between value_col1 and value_col2" → {{"x_column": "value_col1", "y_column": "value_col2"}}

Return ONLY the JSON object:
                """
            elif is_pie_doughnut_polar:
                column_identification_prompt = f"""
You are a data analysis expert. Given a user query and available columns, identify what to visualize in a pie/doughnut/polar chart.

Available columns: {columns_str}

User Query: {query}

Task: Respond with ONLY a JSON object (no markdown, no explanation) with this structure:
{{"column": "column_name", "aggregation": "count|sum|avg|max|min|none", "group_by": "column_name_or_null", "filter_column": "column_name_or_null", "filter_value": "value_or_null"}}

Instructions:
- column: The VALUE column to aggregate (extract from phrases like "mean X", "total Y", "count of Z")
- aggregation: How to process
  * "mean" or "average" → avg
  * "total" or "sum" → sum
  * "count" or "distribution" → count
  * "max" or "maximum" → max
  * "min" or "minimum" → min
- group_by: The CATEGORICAL column that creates pie segments (from "per X", "by X", "grouped by X")
- filter_column: If there's a condition, extract the column
- filter_value: The filter value

Critical Pattern: "AGGREGATION VALUE per/by GROUP_BY"
- "mean column_A per column_B" → column="column_A", aggregation="avg", group_by="column_B"
- "total column_X by column_Y" → column="column_X", aggregation="sum", group_by="column_Y"

Generic Examples (dataset-agnostic):
- Query: "average column A per column B" → column="A", aggregation="avg", group_by="B"
- Query: "sum of column X by column Y" → column="X", aggregation="sum", group_by="Y"
- Query: "mean column M grouped by column N" → column="M", aggregation="avg", group_by="N"
- Query: "distribution by column A for value X" → column="count_data", aggregation="count", group_by="A", filter_column="col", filter_value="X"
- Query: "maximum column P per column Q" → column="P", aggregation="max", group_by="Q"

Return ONLY the JSON object:
                """
            else:
                column_identification_prompt = f"""
You are a data analysis expert. Given a user query and available columns, identify what to visualize.

Available columns: {columns_str}

User Query: {query}

Task: Respond with ONLY a JSON object (no markdown, no explanation) with this structure:
{{"column": "column_name", "aggregation": "count|sum|avg|max|min|none", "group_by": "column_name_or_null", "filter_column": "column_name_or_null", "filter_value": "value_or_null"}}

Guidelines:
- column: The main column to aggregate or visualize
- aggregation: How to process the data (count items, sum values, calculate average, find max/min, or none for raw values)
- group_by: If the query asks to group/categorize by something, specify that column name; otherwise null
- filter_column: If the query has conditions or constraints, identify the column to filter on; otherwise null
  * Look for: "where", "only", "filter by", "in the", "for the", "within", "by column X in Y", "grouped by X in Y", "by job role in department"
  * Extract the FILTER column/value from these patterns
- filter_value: The value to match in the filter_column; otherwise null

Critical: Distinguish between GROUP BY and FILTER:
- GROUP BY: Shows all groups/categories in the result (divides data into categories for display)
- FILTER: Narrows down the data BEFORE processing (keeps only matching records)
- EXAMPLE: "Plot count by column_A in column_B" → group_by="column_A" AND filter_column="column_B" with filter_value="value_from_query"

Generic Examples (work for any dataset):
- Query: "show distribution of column A" → {{"column": "A", "aggregation": "count", "group_by": null, "filter_column": null, "filter_value": null}}
- Query: "sum of column X grouped by column Y" → {{"column": "X", "aggregation": "sum", "group_by": "Y", "filter_column": null, "filter_value": null}}
- Query: "count by column B within category X" → {{"column": "count_metric", "aggregation": "count", "group_by": "B", "filter_column": "category_col", "filter_value": "X"}}
- Query: "average of column A grouped by column B where C equals D" → {{"column": "A", "aggregation": "avg", "group_by": "B", "filter_column": "C", "filter_value": "D"}}
- Query: "number of items by column A in column B value" → {{"column": "count_metric", "aggregation": "count", "group_by": "A", "filter_column": "B", "filter_value": "value"}}

Return ONLY the JSON object:
                """
            
            # Log the prompt being sent to LLM so it's visible in Langfuse.
            langfuse_context.update_current_observation(
                input={"query": query, "chart_type": chart_type, "prompt": column_identification_prompt.strip()},
            )
            try:
                try:
                    lf_cb = langfuse_context.get_current_langchain_handler()
                    _chart_cbs = [lf_cb] if lf_cb else None
                except Exception:
                    _chart_cbs = None
                response = self.llm.invoke(
                    column_identification_prompt,
                    config={"callbacks": _chart_cbs} if _chart_cbs else {}
                ).content.strip()

                # Clean markdown if present
                response = response.replace('```json', '').replace('```', '').strip()

                # Extract JSON
                json_start = response.find('{')
                json_end = response.rfind('}') + 1
                if json_start != -1 and json_end > json_start:
                    analysis = json.loads(response[json_start:json_end])
                    logger.info(f"LLM identified: {analysis}")
                    langfuse_context.update_current_observation(output={"column_mapping": analysis})
                else:
                    logger.warning("Could not parse LLM response, using fallback")
                    return self._extract_auto_categorical(query, chart_type)
            except Exception as e:
                log_full_exception(e, "LLM analysis failed, using fallback")
                return self._extract_auto_categorical(query, chart_type)
            
            # Step 2: Handle scatter plot specifically
            # Helper function for case-insensitive column matching
            def find_column(col_name):
                if not col_name:
                    return None
                # First try exact match
                if col_name in self.df.columns:
                    return col_name
                # Try case-insensitive match
                col_lower = str(col_name).lower()
                for df_col in self.df.columns:
                    if str(df_col).lower() == col_lower:
                        return df_col
                return None

            if is_scatter:
                x_column = analysis.get('x_column')
                y_column = analysis.get('y_column')
                
                x_column = find_column(x_column)
                y_column = find_column(y_column)
                
                if not x_column or not y_column:
                    logger.warning(f"X or Y column not found, using fallback")
                    return self._extract_auto_categorical(query, chart_type)
                
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        
                        # Extract numeric data for scatter plot
                        x_values = pd.to_numeric(self.df[x_column], errors='coerce').dropna()
                        y_values = pd.to_numeric(self.df[y_column], errors='coerce')
                        
                        # Align indices
                        valid_idx = x_values.index
                        y_values = y_values[valid_idx]
                        
                        # Create array of {x, y} points
                        points = [
                            {'x': float(x), 'y': float(y)} 
                            for x, y in zip(x_values.values, y_values.values)
                        ]
                        
                        logger.info(f"Extracted {len(points)} scatter points")
                        return {
                            'chart_type': 'scatter',
                            'data': points,
                            'title': f'{y_column} vs {x_column}'
                        }
                except Exception as e:
                    log_full_exception(e, "Scatter extraction error")
                    return self._extract_auto_categorical(query, chart_type)
            
            # Step 2: Extract data based on identified column and aggregation (for non-scatter)
            column = analysis.get('column')
            aggregation = analysis.get('aggregation', 'count')
            group_by = analysis.get('group_by')
            filter_column = analysis.get('filter_column')
            filter_value = analysis.get('filter_value')
            
            # For pie/doughnut charts with count, use group_by column if column is placeholder
            if (chart_type in ['pie', 'doughnut', 'polarArea']) and aggregation == 'count' and column == 'count_data' and group_by:
                column = group_by
            
            # Try to find column with case-insensitive matching
            actual_column = find_column(column)
            if actual_column:
                column = actual_column
            elif group_by and find_column(group_by):
                column = find_column(group_by)
            else:
                logger.warning(f"Column '{column}' not found (tried case-insensitive match)")
                logger.error(f"No valid column found for aggregation")
                return None
            
            # Try to find group_by column with case-insensitive matching
            if group_by:
                actual_group_by = find_column(group_by)
                if actual_group_by:
                    group_by = actual_group_by
            
            # Try to find filter_column with case-insensitive matching
            if filter_column:
                actual_filter_column = find_column(filter_column)
                if actual_filter_column:
                    filter_column = actual_filter_column
            
            # Apply filter if specified
            filtered_df = self.df
            if filter_column and filter_value:
                if filter_column in self.df.columns:
                    logger.info(f"Applying filter: {filter_column} = {filter_value}")
                    filtered_df = self.df[self.df[filter_column].astype(str).str.lower() == str(filter_value).lower()]
                    logger.info(f"After filter: {len(filtered_df)} rows (from {len(self.df)})")
            
            logger.info(f"Using column: {column}, aggregation: {aggregation}, group_by: {group_by}, filter: {filter_column}={filter_value}")
            
            # Handle year extraction for temporal data
            if group_by == 'year' and column in self.df.columns:
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        # Try to extract year from any date column
                        if 'date' in column.lower() or 'hire' in column.lower():
                            dates = pd.to_datetime(filtered_df[column], errors='coerce')
                            years = dates.dt.year
                            year_counts = years.value_counts().sort_index()
                            data = {str(int(year)): int(count) for year, count in year_counts.items()}
                            return {
                                'chart_type': chart_type,
                                'data': data,
                                'title': f'Count by Year'
                            }
                except Exception as e:
                    logger.warning(f"Year extraction failed: {e}")
            
            # Handle groupby aggregations
            if group_by and group_by in filtered_df.columns:
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        
                        if aggregation == 'count':
                            grouped = filtered_df[group_by].value_counts()
                        elif aggregation == 'sum':
                            grouped = filtered_df.groupby(group_by)[column].sum()
                        elif aggregation == 'avg':
                            grouped = filtered_df.groupby(group_by)[column].mean()
                        elif aggregation == 'max':
                            grouped = filtered_df.groupby(group_by)[column].max()
                        elif aggregation == 'min':
                            grouped = filtered_df.groupby(group_by)[column].min()
                        else:
                            grouped = filtered_df[group_by].value_counts()
                        
                        data = {str(key): float(value) if isinstance(value, (int, float)) else int(value) 
                               for key, value in grouped.items()}
                        
                        logger.info(f"Extracted {len(data)} groups")
                        return {
                            'chart_type': chart_type,
                            'data': data,
                            'title': f'{aggregation.capitalize()} {column} by {group_by}'
                        }
                except Exception as e:
                    log_full_exception(e, "Groupby extraction error")
                    return None
            
            # Handle simple column aggregation (no groupby)
            else:
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        
                        if aggregation == 'count':
                            counts = self.df[column].value_counts()
                            data = {str(key): int(value) for key, value in counts.items()}
                        elif aggregation == 'sum':
                            data = {"total": float(self.df[column].sum())}
                        elif aggregation == 'avg':
                            data = {"average": float(self.df[column].mean())}
                        elif aggregation == 'max':
                            data = {"maximum": float(self.df[column].max())}
                        elif aggregation == 'min':
                            data = {"minimum": float(self.df[column].min())}
                        else:
                            counts = self.df[column].value_counts()
                            data = {str(key): int(value) for key, value in counts.items()}
                        
                        logger.info(f"Extracted {len(data)} data points")
                        return {
                            'chart_type': chart_type,
                            'data': data,
                            'title': f'{aggregation.capitalize()} of {column}'
                        }
                except Exception as e:
                    log_full_exception(e, "Simple aggregation error")
                    return self._extract_auto_categorical(query, chart_type)
                
        except Exception as e:
            log_full_exception(e, "Data extraction error")
            return None

    def _extract_auto_categorical(self, query, chart_type):
        """Fallback: automatically find a categorical column"""
        try:
            for col in self.df.columns:
                if self.df[col].dtype == 'object' or self.df[col].nunique() < 20:
                    counts = self.df[col].value_counts().head(10)
                    data = {str(key): int(value) for key, value in counts.items()}
                    return {
                        'chart_type': chart_type,
                        'data': data,
                        'title': f'Distribution of {col}'
                    }
        except:
            pass
        return None

    def _generate_chart_insights(self, chart_data: dict, query: str = "") -> str:
        """Generate intelligent insights from chart data based on chart type"""
        try:
            if not chart_data or 'data' not in chart_data:
                return ""
            
            chart_type = chart_data.get('chart_type', 'bar')
            data = chart_data.get('data', {})
            title = chart_data.get('title', 'Chart')
            
            # Handle scatter plots (array of points)
            if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                return self._generate_scatter_insights(data, title)
            
            # Handle categorical charts (dict of key-value pairs)
            if isinstance(data, dict) and len(data) > 0:
                if chart_type == 'line' or chart_type == 'area':
                    return self._generate_line_insights(data, title)
                else:
                    return self._generate_categorical_insights(data, title, chart_type)
            
            return ""
        except Exception as e:
            log_full_exception(e, "Insight generation error")
            return ""
    
    def _generate_categorical_insights(self, data: dict, title: str, chart_type: str) -> str:
        """Generate insights for bar, pie, doughnut, polar charts"""
        try:
            # Sort by value
            sorted_items = sorted(data.items(), key=lambda x: x[1], reverse=True)
            total = sum(data.values())
            
            if total == 0 or len(sorted_items) == 0:
                return ""
            
            # Get top and bottom items
            top_key, top_value = sorted_items[0]
            top_pct = (top_value / total) * 100
            
            insights = []
            
            # Top category insight
            insights.append(f"{top_key} leads with {top_pct:.1f}% of the total ({int(top_value):,} out of {int(total):,})")
            
            # Second place if significantly different
            if len(sorted_items) > 1:
                second_key, second_value = sorted_items[1]
                second_pct = (second_value / total) * 100
                if top_pct - second_pct > 5:  # Significant difference
                    insights.append(f"followed by {second_key} at {second_pct:.1f}%")
            
            # Distribution insight
            if len(sorted_items) >= 3:
                top_3_total = sum(v for k, v in sorted_items[:3])
                top_3_pct = (top_3_total / total) * 100
                if top_3_pct > 70:
                    insights.append(f"The top 3 categories account for {top_3_pct:.1f}% of all data")
            
            # Balance/skew insight
            if len(sorted_items) > 2:
                bottom_key, bottom_value = sorted_items[-1]
                bottom_pct = (bottom_value / total) * 100
                if top_pct > 50:
                    insights.append(f"The distribution is heavily skewed towards {top_key}")
                elif bottom_pct < 5 and len(sorted_items) > 3:
                    low_count = sum(1 for k, v in sorted_items if (v/total)*100 < 5)
                    insights.append(f"{low_count} categories each represent less than 5% of the total")
            
            return ". ".join(insights) + "."
        except Exception as e:
            log_full_exception(e, "Categorical insight error")
            return ""
    
    def _generate_line_insights(self, data: dict, title: str) -> str:
        """Generate insights for line and area charts (trend analysis)"""
        try:
            if len(data) < 2:
                return ""
            
            values = list(data.values())
            labels = list(data.keys())
            
            insights = []
            
            # Overall trend
            first_val = values[0]
            last_val = values[-1]
            
            if last_val > first_val:
                pct_change = ((last_val - first_val) / first_val) * 100 if first_val != 0 else 0
                insights.append(f"Overall increasing trend with a {pct_change:.1f}% rise from {labels[0]} to {labels[-1]}")
            elif last_val < first_val:
                pct_change = ((first_val - last_val) / first_val) * 100 if first_val != 0 else 0
                insights.append(f"Overall decreasing trend with a {pct_change:.1f}% decline from {labels[0]} to {labels[-1]}")
            else:
                insights.append(f"Values remain relatively stable from {labels[0]} to {labels[-1]}")
            
            # Peak and valley
            max_val = max(values)
            min_val = min(values)
            max_idx = values.index(max_val)
            min_idx = values.index(min_val)
            
            insights.append(f"Peak value of {max_val:,.0f} at {labels[max_idx]}")
            
            if max_val != min_val:
                range_pct = ((max_val - min_val) / min_val) * 100 if min_val != 0 else 0
                insights.append(f"lowest at {labels[min_idx]} ({min_val:,.0f}), showing a {range_pct:.0f}% variation")
            
            return ". ".join(insights) + "."
        except Exception as e:
            log_full_exception(e, "Line insight error")
            return ""
    
    def _generate_scatter_insights(self, data: list, title: str) -> str:
        """Generate insights for scatter plots (correlation analysis)"""
        try:
            if len(data) < 3:
                return ""
            
            x_values = [p['x'] for p in data if 'x' in p and 'y' in p]
            y_values = [p['y'] for p in data if 'x' in p and 'y' in p]
            
            if len(x_values) == 0:
                return ""
            
            insights = []
            
            # Basic stats
            insights.append(f"Analyzing {len(data)} data points")
            
            # Range information
            x_min, x_max = min(x_values), max(x_values)
            y_min, y_max = min(y_values), max(y_values)
            
            insights.append(f"X ranges from {x_min:.1f} to {x_max:.1f}, Y ranges from {y_min:.1f} to {y_max:.1f}")
            
            # Simple correlation detection (using basic slope)
            try:
                correlation = np.corrcoef(x_values, y_values)[0, 1]
                
                if correlation > 0.7:
                    insights.append(f"Shows a strong positive correlation (r={correlation:.2f})")
                elif correlation < -0.7:
                    insights.append(f"Shows a strong negative correlation (r={correlation:.2f})")
                elif abs(correlation) > 0.3:
                    direction = "positive" if correlation > 0 else "negative"
                    insights.append(f"Shows a moderate {direction} correlation (r={correlation:.2f})")
                else:
                    insights.append(f"Shows weak or no linear correlation (r={correlation:.2f})")
            except:
                # Fallback without numpy
                pass
            
            return ". ".join(insights) + "."
        except Exception as e:
            log_full_exception(e, "Scatter insight error")
            return ""

    @observe(as_type="span", name="Plot Path")
    def run_plot_path(self, query):
        langfuse_context.update_current_observation(
            input={"query": query},
            metadata={"file_uuid": self.file_uuid, "filename": self.filename},
            tags=["plot-path"],
        )
        try:
            logger.info(f"📊 PLOT PATH: {query}")
            
            # Determine chart type from query (reuse centralized detection)
            chart_type = self._get_chart_type(query)
            logger.info(f"Detected chart type: {chart_type}")
            
            # Extract chart data using direct pandas execution
            chart_data = self._extract_chart_data(query, chart_type)
            
            if not chart_data:
                logger.error("Failed to extract chart data")
                return json.dumps({"chart_type": chart_type, "data": {}, "title": "Error: Could not extract data"})
            
            # Generate insights from chart data
            logger.info("Generating chart insights...")
            insights = self._generate_chart_insights(chart_data, query)
            
            # Build final JSON response
            final_response = {
                "chart_type": chart_data.get('chart_type', chart_type),
                "data": chart_data.get('data', {}),
                "title": chart_data.get('title', 'Chart'),
                "insights": insights  # Include generated insights
            }
            
            result_json = json.dumps(final_response, ensure_ascii=False)
            logger.info(f"Chart JSON generated with insights: {result_json[:150]}...")
            self._trace_path_output(
                path_name="Plot Path",
                query=query,
                output_value=result_json,
                exit_point="plot_response",
                extra={
                    "chart_type": final_response["chart_type"],
                    "title": final_response["title"],
                    "data_points": len(final_response["data"]) if isinstance(final_response["data"], dict) else len(final_response.get("data", [])),
                    "has_insights": bool(insights),
                },
            )
            return result_json
            
        except Exception as e:
            log_full_exception(e, "Plot Error")
            user_msg = "Could not generate the chart due to an internal error. Please try again later."
            _err_json = json.dumps({"chart_type": "bar", "data": {}, "title": user_msg})
            self._trace_path_output(
                path_name="Plot Path",
                query=query,
                output_value=_err_json,
                exit_point="plot_error",
                status="error",
                extra={"error": str(e)[:200]},
            )
            return _err_json
