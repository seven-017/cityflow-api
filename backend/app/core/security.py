from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from pwdlib import PasswordHash

from app.core.config import get_settings
from app.core.exceptions import UnauthorizedException

# 推荐算法自动选（当前是 Argon2id）。密码**永远不存明文**，只存这个哈希串
password_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    # 把用户输入的明文重新算一遍哈希，跟库里存的比。
    # 这个过程是"不可逆"的 —— 拿到哈希也推不回密码
    return password_hasher.verify(password, password_hash)


def create_access_token(user_id: int) -> tuple[str, int]:
    """签一张 token 出来，返回 (token, 多少秒后过期)。"""
    settings = get_settings()
    expires_in = settings.access_token_expire_minutes * 60
    now = datetime.now(UTC)
    payload = {
        # sub 是 JWT 的标准字段，意思是"这张 token 是谁的"。
        # 必须转成字符串：JWT 规范要求 sub 是字符串，塞 int 有些库会报错
        "sub": str(user_id),
        "iat": now,                            # issued at，签发时间
        "exp": now + timedelta(seconds=expires_in),  # expires，过期时间；jwt.decode 会自动检查
    }
    token = jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return token, expires_in


def decode_access_token(token: str) -> dict[str, Any]:
    """验签 + 解出内容。签名不对、过期、被改过，都会抛异常。"""
    settings = get_settings()
    try:
        return jwt.decode(
            token,
            settings.jwt_secret_key,
            # algorithms 只给一个是有意为之。不写的话库会去读 token 头部里声明的算法，
            # 攻击者就能把头部改成 none / HS256 来绕过验签
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.PyJWTError as exc:
        # 统一转成自己的异常，外面不用认识 pyjwt 的异常类型；
        # from exc 保留因果链，排查时能看到到底是过期还是签名不对
        raise UnauthorizedException("Invalid or expired access token.") from exc
