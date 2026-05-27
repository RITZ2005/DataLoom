"""
Authentication and Role-Based Access Control (RBAC) Module.
Handles JWT tokens, password verification, and permission checks.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

import bcrypt
import jwt
from fastapi import Depends, Header, HTTPException, status

logger = logging.getLogger(__name__)

# Configuration
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production-12345")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))  # 24 hours
USERS_FILE = str(Path(__file__).resolve().parents[2] / "users.json")


class UserManager:
    """Manages user data stored in the JSON user store."""

    def __init__(self, file_path: str = USERS_FILE):
        self.file_path = file_path
        self.users = self._load_users()
        self.roles = self._load_roles()

    def _load_users(self) -> dict:
        try:
            if os.path.exists(self.file_path):
                with open(self.file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return {user["email"]: user for user in data.get("users", [])}
        except Exception:
            logger.exception("Error loading users")
        return {}

    def _load_roles(self) -> dict:
        try:
            if os.path.exists(self.file_path):
                with open(self.file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("roles", {})
        except Exception:
            logger.exception("Error loading roles")
        return {}

    def _save_users(self):
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            data["users"] = list(self.users.values())

            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            logger.exception("Error saving users")
            raise

    def get_user(self, email: str) -> Optional[dict]:
        return self.users.get(email)

    def get_user_by_login(self, login_id: str) -> Optional[dict]:
        """Get user by email (preferred) or username (legacy login)."""
        if not login_id:
            return None

        key = login_id.strip().lower()
        by_email = self.users.get(key)
        if by_email:
            return by_email

        for user in self.users.values():
            username = (user.get("username") or "").strip().lower()
            if username and username == key:
                return user
        return None

    def user_exists(self, email: str) -> bool:
        return email in self.users

    def create_user(self, email: str, username: str, password: str, role: str = "user", name: str = "") -> dict:
        if self.user_exists(email):
            raise ValueError(f"User with email {email} already exists")

        if role not in self.roles:
            raise ValueError(f"Invalid role: {role}")

        user_id = str(len(self.users) + 1)
        hashed_password = hash_password(password)
        now = datetime.utcnow().isoformat() + "Z"

        user = {
            "id": user_id,
            "email": email,
            "username": username,
            "password": hashed_password,
            "role": role,
            "name": name or username,
            "created_at": now,
            "updated_at": now,
            "is_active": True,
        }

        self.users[email] = user
        self._save_users()
        return user

    def list_users(self) -> List[dict]:
        users = []
        for user in self.users.values():
            sanitized = {k: v for k, v in user.items() if k != "password"}
            users.append(sanitized)
        return users

    def update_user(
        self,
        email: str,
        is_active: Optional[bool] = None,
        role: Optional[str] = None,
        name: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        langfuse_enabled: Optional[bool] = None,
    ) -> dict:
        user = self.get_user(email)
        if not user:
            raise ValueError(f"User with email {email} not found")

        if role is not None and role not in self.roles:
            raise ValueError(f"Invalid role: {role}")

        if is_active is not None:
            user["is_active"] = is_active
        if role is not None:
            user["role"] = role
        if name is not None:
            user["name"] = name
        if username is not None:
            user["username"] = username
        if password is not None:
            user["password"] = hash_password(password)
        if langfuse_enabled is not None:
            user["langfuse_enabled"] = langfuse_enabled

        user["updated_at"] = datetime.utcnow().isoformat() + "Z"
        self.users[email] = user
        self._save_users()
        return user

    def get_permissions(self, role: str) -> List[str]:
        role_data = self.roles.get(role, {})
        return role_data.get("permissions", [])

    def reload(self):
        self.users = self._load_users()
        self.roles = self._load_roles()


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        logger.exception("Error verifying password")
        return False


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token aligned with Langfuse NextAuth."""
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update(
        {
            "exp": expire,
            "iat": datetime.utcnow(),
            "sub": data.get("email"),
            "name": data.get("name", "User"),
        }
    )

    try:
        return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    except Exception:
        logger.exception("Error creating token")
        raise


def decode_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("Token has expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning("Invalid token: %s", e)
        return None


def verify_token(token: str) -> Optional[dict]:
    if not token:
        return None
    if token.startswith("Bearer "):
        token = token[7:]
    return decode_token(token)


async def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No authorization header provided",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization.replace("Bearer ", "")
    payload = verify_token(token)

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    email = payload.get("email")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing email claim",
        )

    user_manager = UserManager()
    user = user_manager.get_user(email)

    if not user or not user.get("is_active"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )


    # Calculate and inject effective permissions into the user object
    role_name = user.get("role")
    effective_permissions = set(user.get("permissions", []))
    if role_name:
        role_permissions = user_manager.get_permissions(role_name)
        effective_permissions.update(role_permissions)

    user["effective_permissions"] = list(effective_permissions)
    return user


async def get_current_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return current_user
