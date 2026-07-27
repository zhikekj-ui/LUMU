import os
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from models.base import get_db, async_session
from models.user import User, Tenant
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import uuid
from datetime import datetime, timezone
from auth.password import hash_password, verify_password
from auth.jwt_handler import create_access_token, create_refresh_token, verify_token
from auth.deps import get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])

class RegisterRequest(BaseModel):
    email: str
    username: str
    password: str
    display_name: str | None = None

class LoginRequest(BaseModel):
    email: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    user: dict

@router.post("/register", response_model=TokenResponse)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    # 已有用户则关闭开放注册，防止公网被乱注册；首次安装通过 BOOTSTRAP_ADMIN_* 引导
    existing = await db.execute(select(User))
    if existing.scalars().first():
        raise HTTPException(403, "注册已关闭，请联系管理员")
    result = await db.execute(select(User).where(User.email == req.email))
    if result.scalar_one_or_none():
        raise HTTPException(400, "Email already registered")
    result = await db.execute(select(User).where(User.username == req.username))
    if result.scalar_one_or_none():
        raise HTTPException(400, "Username already taken")

    user = User(
        email=req.email,
        username=req.username,
        hashed_password=hash_password(req.password),
        display_name=req.display_name or req.username,
        role="super_admin",
        api_key=f"lmu_{uuid.uuid4().hex[:32]}",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    tokens = TokenResponse(
        access_token=create_access_token(str(user.id), user.email, user.role),
        refresh_token=create_refresh_token(str(user.id)),
        user={"id": str(user.id), "email": user.email, "username": user.username, "display_name": user.display_name, "role": user.role},
    )
    return tokens

@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(401, "Invalid credentials")
    if user.status != "active":
        raise HTTPException(403, "Account disabled")

    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()

    return TokenResponse(
        access_token=create_access_token(str(user.id), user.email, user.role),
        refresh_token=create_refresh_token(str(user.id)),
        user={"id": str(user.id), "email": user.email, "username": user.username, "display_name": user.display_name, "role": user.role},
    )

@router.post("/refresh")
async def refresh(refresh_token: str, db: AsyncSession = Depends(get_db)):
    payload = verify_token(refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(401, "Invalid refresh token")
    result = await db.execute(select(User).where(User.id == uuid.UUID(payload["sub"])))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(401, "User not found")
    return {
        "access_token": create_access_token(str(user.id), user.email, user.role),
        "refresh_token": create_refresh_token(str(user.id)),
    }

@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user)):
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "username": current_user.username,
        "display_name": current_user.display_name,
        "role": current_user.role,
        "total_tokens_used": current_user.total_tokens_used,
        "billing_plan": current_user.billing_plan,
    }


async def ensure_bootstrap_admin():
    """启动时根据 .env 的 BOOTSTRAP_ADMIN_EMAIL/PASSWORD 确保超级管理员存在。

    仅当配置了这两个变量且对应用户不存在时创建，不影响任何已有用户。
    不配置则完全无操作（适用于已有用户或测试环境）。
    """
    email = os.getenv("BOOTSTRAP_ADMIN_EMAIL")
    pwd = os.getenv("BOOTSTRAP_ADMIN_PASSWORD")
    if not email or not pwd:
        return
    async with async_session() as db:
        res = await db.execute(select(User).where(User.email == email))
        if res.scalar_one_or_none():
            return
        user = User(
            email=email,
            username=email.split("@")[0],
            hashed_password=hash_password(pwd),
            display_name="Administrator",
            role="super_admin",
            status="active",
            api_key=f"lmu_{uuid.uuid4().hex[:32]}",
        )
        db.add(user)
        await db.commit()
