"""Persist forum session cookies in the operating system's credential store."""

from __future__ import annotations

import json

import httpx
import keyring
from keyring.errors import PasswordDeleteError


SERVICE = "Stage1stForumTUI"
ACCOUNT = "stage1st-session"


def load_session(cookies: httpx.Cookies) -> bool:
    saved = keyring.get_password(SERVICE, ACCOUNT)
    if not saved:
        return False
    for item in json.loads(saved):
        domain = item["domain"]
        if domain.lstrip(".").casefold() != "stage1st.com":
            continue
        cookies.set(item["name"], item["value"], domain=domain, path=item["path"])
    return True


def save_session(cookies: httpx.Cookies) -> None:
    saved = [
        {"name": cookie.name, "value": cookie.value, "domain": cookie.domain, "path": cookie.path}
        for cookie in cookies.jar
        if cookie.domain.lstrip(".").casefold() == "stage1st.com"
    ]
    if not saved:
        raise ValueError("论坛没有返回可保存的会话 Cookie")
    keyring.set_password(SERVICE, ACCOUNT, json.dumps(saved, ensure_ascii=False))


def clear_session() -> None:
    try:
        keyring.delete_password(SERVICE, ACCOUNT)
    except PasswordDeleteError:
        pass
