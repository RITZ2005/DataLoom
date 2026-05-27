from typing import List, Optional

from pydantic import BaseModel


class LoginRequest(BaseModel):
    email: Optional[str] = None
    loginId: Optional[str] = None
    companyId: Optional[str] = None
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class RegisterRequest(BaseModel):
    email: str
    username: str
    password: str
    name: Optional[str] = None
    role: str = "user"


class AuthResponse(BaseModel):
    status: str
    token: str
    email: str
    name: str
    role: str
    message: str = ""
    langfuse_enabled: Optional[bool] = False


class UserInfo(BaseModel):
    email: str
    name: str
    role: str
    permissions: List[str]
    langfuse_enabled: Optional[bool] = False


class AdminCreateUserRequest(BaseModel):
    email: str
    username: str
    password: str
    name: Optional[str] = None
    role: str = "user"


class AdminUpdateUserRequest(BaseModel):
    is_active: Optional[bool] = None
    role: Optional[str] = None
    name: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None


class AdminUserResponse(BaseModel):
    id: str
    email: str
    username: str
    role: str
    name: str
    is_active: bool
    created_at: str
    updated_at: str
