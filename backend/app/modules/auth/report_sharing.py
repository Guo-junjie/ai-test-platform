"""报告专用签名与过期校验，与登录 Token 用途隔离。"""
import hmac
from datetime import datetime, timedelta
from fastapi import HTTPException
from jose import JWTError, jwt
from app.config import settings


def create_report_token(run_id, nonce):
    return jwt.encode({"purpose": "report_share", "run_id": str(run_id), "nonce": nonce,
                       "exp": datetime.utcnow() + timedelta(days=7)},
                      settings.SECRET_KEY, algorithm="HS256")


def verify_report_token(token, run_id, nonce=None):
    try:
        payload = jwt.decode(token or "", settings.SECRET_KEY, algorithms=["HS256"],
                             options={"require_exp": True})
        if payload.get("purpose") != "report_share" or payload.get("run_id") != str(run_id):
            raise ValueError("wrong purpose or report")
        if not payload.get("nonce") or (nonce is not None and not hmac.compare_digest(payload["nonce"], nonce)):
            raise ValueError("revoked share")
        return payload
    except (JWTError, ValueError, TypeError):
        raise HTTPException(401, "分享链接无效或已过期，请重新获取")
