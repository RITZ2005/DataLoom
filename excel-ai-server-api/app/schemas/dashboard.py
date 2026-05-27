from typing import Any, Dict, List

from pydantic import BaseModel


class DashboardWidgetRequest(BaseModel):
    query: str
    compare_file_id: str | None = None
    session_id: str | None = None
    source_type: str | None = None
    widget_type_hint: str | None = None
    chart_type_hint: str | None = None
    filter_context_hint: Dict[str, Any] | None = None
    mode: str | None = None


class CloneWidgetsRequest(BaseModel):
    base_file_id: str
    target_file_id: str
    session_id: str | None = None


class TemplateCloneRequest(BaseModel):
    template_widgets: List[Dict[str, Any]]
    session_id: str | None = None


class UnifiedCompareRequest(BaseModel):
    base_file_id: str
    compare_file_id: str
    session_id: str | None = None


class DashboardGenerateRequest(BaseModel):
    user_requirements: str | None = None
    session_id: str | None = None
    source_type: str | None = None
    mode: str | None = None


class ChartBuilderRequest(BaseModel):
    chart_type: str
    dimension: str
    measure: str | None = None
    aggregation: str = "sum"
    source_type: str | None = None
    mode: str | None = None


class DashboardFilterRequest(BaseModel):
    column: str | None = None
    value: str | None = None
    filters: dict | None = None
    session_id: str | None = None
    source_type: str | None = None
