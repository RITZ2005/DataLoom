from typing import Optional

from pydantic import BaseModel


class CategoryItem(BaseModel):
    name: str
    question_count: int = 0
    is_default: bool = False


class CategoryRenameRequest(BaseModel):
    old_name: str
    new_name: str


class SaveQuestionRequest(BaseModel):
    question_text: str
    category: str = "Generic"
    file_uuid: str


class SavedQuestionResponse(BaseModel):
    id: int
    question_text: str
    question_category: str
    scope_level: str
    scope_id: Optional[str] = None
    created_at: str
