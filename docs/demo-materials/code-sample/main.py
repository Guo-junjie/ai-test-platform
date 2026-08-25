"""
电商订单中心 — FastAPI 示例服务（供【代码解析】功能测试）

仅作 demo，不会真实运行；提供 7 个 REST 接口，结构与 openapi.json 保持一致。
"""
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Depends, Header, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, field_validator
import jwt

app = FastAPI(
    title="电商订单中心 API",
    version="1.0.0",
    description="e2e-demo-project 的代码示例，结构与 openapi.json 一致。",
)

security = HTTPBearer()
JWT_SECRET = "demo-secret-do-not-use-in-prod"
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 120
REFRESH_TOKEN_EXPIRE_DAYS = 30
MAX_LOGIN_ATTEMPTS = 5


# ============ Schema Models ============

class RegisterReq(BaseModel):
    phone: str = Field(..., pattern=r"^1[3-9]\d{9}$", description="手机号")
    password: str = Field(..., min_length=8)
    sms_code: str = Field(..., pattern=r"^\d{6}$")
    nickname: Optional[str] = Field(None, max_length=32)


class LoginReq(BaseModel):
    account: str
    password: str


class ChangePasswordReq(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=8)


class OrderItemReq(BaseModel):
    sku_id: str
    quantity: int = Field(..., gt=0)


class CreateOrderReq(BaseModel):
    items: List[OrderItemReq] = Field(..., min_length=1)
    address_id: str
    coupon_id: Optional[str] = None
    remark: Optional[str] = Field(None, max_length=200)


# ============ 内存 mock 数据（不真存）============

_USERS: dict = {}
_ORDERS: dict = {}
_BLACKLIST: set = set()
_LOGIN_ATTEMPTS: dict = {}


# ============ Auth 工具 ============

def _create_token(user_id: str, expires_minutes: int) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.utcnow() + timedelta(minutes=expires_minutes),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """从 Bearer Token 解析当前用户。"""
    token = credentials.credentials
    if token in _BLACKLIST:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token revoked")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token expired")
    user_id = payload.get("sub")
    user = _USERS.get(user_id)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user not found")
    return user


# ============ User 路由 ============

@app.post("/api/v1/users/register", status_code=201, tags=["User"])
async def register(req: RegisterReq):
    """手机号 + 短信码注册。重复注册返回 409。"""
    if req.phone in [u["phone"] for u in _USERS.values()]:
        raise HTTPException(status.HTTP_409_CONFLICT, "PHONE_ALREADY_REGISTERED")
    user_id = f"user-{len(_USERS)+1:04d}"
    _USERS[user_id] = {
        "id": user_id,
        "phone": req.phone,
        "nickname": req.nickname or f"用户{user_id}",
        "password_hash": req.password,  # 演示用，真实应 bcrypt
        "created_at": datetime.utcnow().isoformat(),
    }
    return {"id": user_id, "phone": req.phone, "nickname": _USERS[user_id]["nickname"]}


@app.post("/api/v1/users/login", tags=["User"])
async def login(req: LoginReq):
    """账号密码登录；5 次错误锁定 30 分钟。"""
    attempts = _LOGIN_ATTEMPTS.get(req.account, 0)
    if attempts >= MAX_LOGIN_ATTEMPTS:
        raise HTTPException(status.HTTP_423_LOCKED, "account locked")
    user = next(
        (u for u in _USERS.values() if u["phone"] == req.account and u["password_hash"] == req.password),
        None,
    )
    if not user:
        _LOGIN_ATTEMPTS[req.account] = attempts + 1
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    _LOGIN_ATTEMPTS.pop(req.account, None)
    return {
        "access_token": _create_token(user["id"], ACCESS_TOKEN_EXPIRE_MINUTES),
        "refresh_token": _create_token(user["id"], REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60),
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


@app.post("/api/v1/users/refresh", tags=["User"])
async def refresh_token(refresh_token: str):
    """用 refresh_token 换新 access_token。"""
    try:
        payload = jwt.decode(refresh_token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "refresh expired")
    new_access = _create_token(payload["sub"], ACCESS_TOKEN_EXPIRE_MINUTES)
    return {"access_token": new_access, "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60}


@app.get("/api/v1/users/me", tags=["User"])
async def get_me(user: dict = Depends(get_current_user)):
    """查询当前登录用户信息。"""
    return {"id": user["id"], "phone": user["phone"], "nickname": user["nickname"]}


@app.put("/api/v1/users/password", tags=["User"])
async def change_password(
    req: ChangePasswordReq,
    user: dict = Depends(get_current_user),
    authorization: str = Header(...),
):
    """修改密码；成功后旧 token 立即失效。"""
    if user["password_hash"] != req.old_password:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "old password wrong")
    upper = any(c.isupper() for c in req.new_password)
    lower = any(c.islower() for c in req.new_password)
    digit = any(c.isdigit() for c in req.new_password)
    special = any(not c.isalnum() for c in req.new_password)
    if not (upper and lower and digit and special):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "WEAK_PASSWORD")
    user["password_hash"] = req.new_password
    _BLACKLIST.add(authorization.split(" ", 1)[-1])
    return {"message": "password changed"}


# ============ Order 路由 ============

@app.post("/api/v1/orders", status_code=201, tags=["Order"])
async def create_order(
    req: CreateOrderReq,
    user: dict = Depends(get_current_user),
):
    """创建订单（待支付状态）。"""
    order_id = f"ORD-{datetime.utcnow().strftime('%Y%m%d')}-{len(_ORDERS)+1:08d}"
    _ORDERS[order_id] = {
        "id": order_id,
        "user_id": user["id"],
        "status": "PENDING",
        "items": [item.model_dump() for item in req.items],
        "address_id": req.address_id,
        "remark": req.remark,
        "created_at": datetime.utcnow().isoformat(),
    }
    return _ORDERS[order_id]


@app.get("/api/v1/orders/{order_id}", tags=["Order"])
async def get_order(
    order_id: str,
    user: dict = Depends(get_current_user),
):
    """订单详情。仅订单所有者可访问。"""
    order = _ORDERS.get(order_id)
    if not order:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "order not found")
    if order["user_id"] != user["id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your order")
    return order


@app.post("/api/v1/orders/{order_id}/cancel", tags=["Order"])
async def cancel_order(
    order_id: str,
    reason: str = "USER_CANCEL",
    user: dict = Depends(get_current_user),
):
    """取消订单。PAID 状态会触发退款。"""
    order = _ORDERS.get(order_id)
    if not order:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "order not found")
    if order["user_id"] != user["id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your order")
    if order["status"] not in ("PENDING", "PAID"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"cannot cancel {order['status']}")
    order["status"] = "CANCELLED"
    order["cancel_reason"] = reason
    return {"message": "cancelled", "order": order}


@app.post("/api/v1/orders/{order_id}/pay", tags=["Order"])
async def pay_order(
    order_id: str,
    idempotency_key: str = Header(..., description="幂等键，5 分钟内相同 key 仅一次"),
    user: dict = Depends(get_current_user),
):
    """订单支付（幂等）。"""
    order = _ORDERS.get(order_id)
    if not order:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "order not found")
    if order["user_id"] != user["id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your order")
    if order["status"] != "PENDING":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"cannot pay {order['status']}")
    order["status"] = "PAID"
    order["paid_at"] = datetime.utcnow().isoformat()
    return order
