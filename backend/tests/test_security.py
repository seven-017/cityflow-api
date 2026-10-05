"""密码哈希和 JWT 这两块的测试。

这两块有个共同点：写错了不会当场报错，只会静默失效 ——
哈希写错就是登不进去，验签写松了就是谁都能伪造身份。
所以下面重点在「不该通过的必须不通过」，而不是「正常路径能跑通」。
"""

import base64
import json
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import get_settings
from app.core.exceptions import UnauthorizedException
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_password_roundtrip():
    """哈希存进去，明文能验出来。"""
    hashed = hash_password("CityFlow@123")
    assert verify_password("CityFlow@123", hashed)


def test_wrong_password_rejected():
    hashed = hash_password("CityFlow@123")
    assert not verify_password("CityFlow@124", hashed)


def test_same_password_hashes_differently_twice():
    """同一个密码哈希两次，结果必须不一样。

    这是「加盐」在起作用。要是两次一样，说明没加随机盐 ——
    那样一张彩虹表就能把所有用户一起端掉，而且两个碰巧用同一密码的用户
    在库里长得一模一样，看到一个就等于看到另一个。
    """
    assert hash_password("CityFlow@123") != hash_password("CityFlow@123")


def test_token_roundtrip():
    token, expires_in = create_access_token(7)
    payload = decode_access_token(token)

    # sub 必须是字符串。JWT 规范这么要求的，塞 int 有些库直接报错
    assert payload["sub"] == "7"
    assert expires_in == get_settings().access_token_expire_minutes * 60


def test_token_signed_with_another_key_rejected():
    """拿着别人的密钥签出来的 token，不能认。

    密钥写够 32 字节是因为 pyjwt 会对短密钥报 InsecureKeyLengthWarning ——
    那警告本身是对的（HS256 的密钥短了容易被爆破），只是这儿它是故意的，
    没必要让测试输出里挂一条噪音。
    """
    forged = jwt.encode(
        {"sub": "7"}, "some-other-secret-long-enough-for-hs256", algorithm="HS256"
    )

    with pytest.raises(UnauthorizedException):
        decode_access_token(forged)


def test_tampered_token_rejected():
    """签名被改过就得拒掉。

    只动签名段的最后一个字符，载荷一个字没变 —— 这正是攻击者最容易尝试的：
    改完内容、签名对不上了，就看服务端到底验不验。
    """
    token, _ = create_access_token(7)
    last = token[-1]
    tampered = token[:-1] + ("A" if last != "A" else "B")

    with pytest.raises(UnauthorizedException):
        decode_access_token(tampered)


def test_expired_token_rejected():
    """过期了就拒掉。

    手工签一张 exp 在过去的 —— 不去改全局配置把有效期调短，
    那样得清 get_settings 的缓存，还会影响同一进程里别的测试。
    """
    settings = get_settings()
    now = datetime.now(UTC)
    expired = jwt.encode(
        {
            "sub": "7",
            "iat": now - timedelta(minutes=90),
            "exp": now - timedelta(minutes=60),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )

    with pytest.raises(UnauthorizedException):
        decode_access_token(expired)


def test_alg_none_token_rejected():
    """alg 改成 none 的经典绕过手法，必须拒掉。

    这种 token 长这样：头部声明「我没签名」，签名段留空。手工拼一个出来 ——
    jwt.encode 不会帮你签 none，得自己拼 base64。

    验签时要是没指定 algorithms，库会去读头部声明的算法，看到 none 就真的
    不验签了，于是谁都能拿着一张自制的 token 冒充任意用户。
    代码里 algorithms=[...] 只给一个，挡的就是这个。
    """

    def b64(obj: dict) -> str:
        raw = json.dumps(obj).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    forged = f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64({'sub': '1'})}."

    with pytest.raises(UnauthorizedException):
        decode_access_token(forged)
