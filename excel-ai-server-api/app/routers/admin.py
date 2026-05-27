from typing import List

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_db, log_audit_event
from app.schemas.auth import AdminCreateUserRequest, AdminUpdateUserRequest, AdminUserResponse
from app.utils.logging import log_full_exception, user_facing_error_message
from app.core.auth import UserManager, get_current_admin

from app.config import observe, langfuse_context


router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users", response_model=List[AdminUserResponse])
@observe(name="admin.list_users")
async def admin_list_users(current_user: dict = Depends(get_current_admin)):
    user_manager = UserManager()
    return user_manager.list_users()


@router.post("/users", response_model=AdminUserResponse)
@observe(name="admin.create_user")
async def admin_create_user(
    request: AdminCreateUserRequest,
    current_user: dict = Depends(get_current_admin),
):
    try:
        user_manager = UserManager()
        user = user_manager.create_user(
            email=request.email,
            username=request.username,
            password=request.password,
            role=request.role if request.role in user_manager.roles else "user",
            name=request.name or request.username,
        )
        log_audit_event(
            db=get_db(),
            user_id=current_user.get("id"),
            action="admin_create_user",
            entity_type="user",
            entity_id=user["id"],
            details={"email": user["email"], "role": user["role"]},
        )
        return {k: v for k, v in user.items() if k != "password"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log_full_exception(e, "Admin create user failed")
        raise HTTPException(status_code=500, detail=user_facing_error_message(e))


@router.patch("/users/{email}", response_model=AdminUserResponse)
@observe(name="admin.update_user")
async def admin_update_user(
    email: str,
    request: AdminUpdateUserRequest,
    current_user: dict = Depends(get_current_admin),
):
    try:
        user_manager = UserManager()
        user = user_manager.update_user(
            email=email,
            is_active=request.is_active,
            role=request.role,
            name=request.name,
            username=request.username,
            password=request.password,
        )
        log_audit_event(
            db=get_db(),
            user_id=current_user.get("id"),
            action="admin_update_user",
            entity_type="user",
            entity_id=user["id"],
            details={"email": user["email"], "role": user["role"]},
        )
        return {k: v for k, v in user.items() if k != "password"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log_full_exception(e, "Admin update user failed")
        raise HTTPException(status_code=500, detail=user_facing_error_message(e))
