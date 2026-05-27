from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.dependencies import get_db, log_audit_event
from app.schemas.auth import (
    AuthResponse,
    ChangePasswordRequest,
    LoginRequest,
    RegisterRequest,
    UserInfo,
)
from app.services.langfuse_sso import ensure_langfuse_user
from app.utils.logging import log_full_exception, logger, user_facing_error_message
from app.core.auth import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    UserManager,
    create_access_token,
    get_current_user,
    verify_password,
)

from app.config import observe, langfuse_context, _LANGFUSE_ENABLED


router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=AuthResponse)
@observe(name="auth.register")
async def register(request: RegisterRequest, background_tasks: BackgroundTasks):
    try:
        user_manager = UserManager()

        if not request.email or not request.password:
            raise HTTPException(status_code=400, detail="Email and password are required")

        if len(request.password) < 8:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

        if user_manager.user_exists(request.email):
            raise HTTPException(status_code=400, detail="User with this email already exists")

        user = user_manager.create_user(
            email=request.email,
            username=request.username,
            password=request.password,
            role=request.role if request.role in user_manager.roles else "user",
            name=request.name or request.username,
        )

        access_token = create_access_token(
            data={"email": user["email"], "role": user["role"], "user_id": user["id"]},
            expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
        )

        log_audit_event(
            db=get_db(),
            user_id=user["id"],
            action="register",
            entity_type="user",
            entity_id=user["id"],
            details={"email": user["email"], "role": user["role"]},
        )

        background_tasks.add_task(
            ensure_langfuse_user,
            request.email,
            request.password,
            request.name or getattr(request, "username", "") or "",
        )

        logger.info("New user registered: %s with role: %s", request.email, user["role"])

        return AuthResponse(
            status="success",
            token=access_token,
            email=user["email"],
            name=user["name"],
            role=user["role"],
            message="Registration successful",
            langfuse_enabled=_LANGFUSE_ENABLED,
        )
    except HTTPException:
        raise
    except Exception as e:
        log_full_exception(e, "Registration failed")
        raise HTTPException(status_code=500, detail=user_facing_error_message(e))


@router.post("/login", response_model=AuthResponse)
@observe(name="auth.login")
async def login(request: LoginRequest, background_tasks: BackgroundTasks):
    try:
        user_manager = UserManager()

        login_identifier = (request.email or request.loginId or "").strip().lower()
        if not login_identifier:
            raise HTTPException(status_code=400, detail="email or loginId required")

        user = user_manager.get_user_by_login(login_identifier)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid email or password")

        if not verify_password(request.password, user["password"]):
            raise HTTPException(status_code=401, detail="Invalid email or password")

        if not user.get("is_active", True):
            raise HTTPException(status_code=403, detail="User account is inactive")

        access_token = create_access_token(
            data={"email": user["email"], "role": user["role"], "user_id": user["id"]},
            expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
        )

        log_audit_event(
            db=get_db(),
            user_id=user["id"],
            action="login",
            entity_type="user",
            entity_id=user["id"],
            details={"email": user["email"], "role": user["role"]},
        )

        background_tasks.add_task(
            ensure_langfuse_user,
            user.get("email", login_identifier),
            request.password,
            user.get("name") or user.get("username") or "",
        )

        logger.info("User logged in: %s", user.get("email", login_identifier))
        user_name = user.get("name") or user.get("username") or user.get("email", "User")

        return AuthResponse(
            status="success",
            token=access_token,
            email=user.get("email", login_identifier),
            name=user_name,
            role=user["role"],
            message="Login successful",
            langfuse_enabled=_LANGFUSE_ENABLED,
        )
    except HTTPException:
        raise
    except Exception as e:
        log_full_exception(e, "Login failed")
        raise HTTPException(status_code=500, detail=user_facing_error_message(e))


@router.get("/me", response_model=UserInfo)
@observe(name="auth.me")
async def get_current_user_info(current_user: dict = Depends(get_current_user)):
    try:
        user_manager = UserManager()
        permissions = user_manager.get_permissions(current_user.get("role", "user"))

        return UserInfo(
            email=current_user["email"],
            name=current_user["name"],
            role=current_user["role"],
            permissions=permissions,
            langfuse_enabled=_LANGFUSE_ENABLED,
        )
    except Exception as e:
        log_full_exception(e, "Failed to get user info")
        raise HTTPException(status_code=500, detail=user_facing_error_message(e))


@router.post("/logout")
@observe(name="auth.logout")
async def logout(current_user: dict = Depends(get_current_user)):
    logger.info("User logged out: %s", current_user["email"])
    return {"status": "success", "message": "Logout successful"}


@router.post("/change-password")
@observe(name="auth.change_password")
async def change_password(
    request: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
):
    try:
        if len(request.new_password) < 8:
            raise HTTPException(status_code=400, detail="New password must be at least 8 characters")

        user_manager = UserManager()
        user = user_manager.get_user(current_user["email"])
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        if not verify_password(request.current_password, user["password"]):
            raise HTTPException(status_code=400, detail="Current password is incorrect")

        if verify_password(request.new_password, user["password"]):
            raise HTTPException(status_code=400, detail="New password must be different from the current password")

        user_manager.update_user(current_user["email"], password=request.new_password)

        log_audit_event(
            db=get_db(),
            user_id=current_user.get("id"),
            action="change_password",
            entity_type="user",
            entity_id=current_user.get("id"),
            details={"email": current_user["email"]},
        )

        logger.info("Password changed successfully for: %s", current_user["email"])
        return {"status": "success", "message": "Password changed successfully"}

    except HTTPException:
        raise
    except Exception as e:
        log_full_exception(e, "Change password failed")
        raise HTTPException(status_code=500, detail=user_facing_error_message(e))



