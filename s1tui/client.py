from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

from .constants import BASE
from .parser import Forum, Post, Thread, parse_forums, parse_posts, parse_threads


class ForumClient:
    def __init__(self) -> None:
        headers = {"User-Agent": "Stage1stForumTUI/0.1 (unofficial forum client)"}
        self.http = httpx.AsyncClient(
            headers=headers,
            follow_redirects=True,
            timeout=20.0,
        )
        # External image hosts must never receive the forum's login cookies.
        self.image_http = httpx.AsyncClient(headers=headers, follow_redirects=False, timeout=8.0)

    async def _get(self, url: str) -> str:
        response = await self.http.get(urljoin(BASE, url))
        response.raise_for_status()
        response.encoding = response.encoding or "utf-8"
        return response.text

    async def forums(self) -> list[Forum]:
        return parse_forums(await self._get(BASE))

    async def threads(self, forum: Forum, page: int = 1) -> tuple[list[Thread], int]:
        url = forum.url
        if page > 1:
            url = url.rsplit("-", 1)[0] + f"-{page}.html"
        return parse_threads(await self._get(url))

    async def posts(self, thread: Thread, page: int = 1) -> tuple[str, list[Post], int]:
        url = thread.url
        if page > 1:
            parts = url.rsplit("-", 2)
            url = f"{parts[0]}-{page}-{parts[2]}" if len(parts) == 3 else url
        html = await self._get(url)
        return parse_posts(html, url)

    async def account_page(self) -> tuple[str | None, str]:
        html = await self._get(BASE)
        soup = BeautifulSoup(html, "html.parser")
        user = soup.select_one("#um strong.vwmy a[href*='space-uid-']")
        if user is None:
            user = soup.select_one("#um .vwmy a")
        return (user.get_text(" ", strip=True) or None) if user else None, html

    async def login(self, username: str, password: str) -> tuple[str | None, str]:
        self.http.cookies.clear()
        login_url = urljoin(BASE, "member.php?mod=logging&action=login")
        response = await self.http.get(login_url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        form = soup.select_one("form[name='login']")
        if form is None:
            raise ValueError("找不到登录表单，论坛页面可能已变化")
        if form.select_one("input[name='seccodeverify'], input[name='secanswer']"):
            raise ValueError("论坛要求验证码或安全提问，请在网页中登录")
        action = urljoin(BASE, form.get("action", ""))
        parsed = urlsplit(action)
        if parsed.scheme != "https" or parsed.hostname != "stage1st.com" or parsed.path != "/2b/member.php":
            raise ValueError("登录表单地址异常")
        hash_input = form.select_one("input[name='formhash']")
        formhash = hash_input.get("value") if hash_input else None
        if not formhash:
            raise ValueError("登录表单缺少 formhash")
        payload = {
            "formhash": formhash,
            "referer": BASE,
            "username": username,
            "password": password,
            "questionid": "0",
            "answer": "",
            "cookietime": "2592000",
        }
        result = await self.http.post(action, data=payload, headers={"Referer": login_url})
        result.raise_for_status()
        account, _ = await self.account_page()
        if account:
            return account, "登录成功"
        message = BeautifulSoup(result.text, "html.parser").select_one("#messagetext p, .alert_error")
        detail = message.get_text(" ", strip=True)[:100] if message else "请检查账号、密码或验证码"
        return None, f"登录失败：{detail}"

    async def check_in(self, home_html: str) -> str:
        """Return a confirmed sign-in state; never infer success from a missing link."""
        soup = BeautifulSoup(home_html, "html.parser")
        if soup.select_one("a[href*='muanyun_053']"):
            return await self._check_muanyun()
        account_area = soup.select_one("#um")
        if account_area and re.search(r"今日已签|已(?:经)?签到|已打卡", account_area.get_text(" ", strip=True)):
            return "今日已签"
        link = soup.select_one("a[href*='study_daily_attendance-daily_attendance.html']")
        if link is None:
            link = next(
                (item for item in soup.select("#um a[href]")
                 if "签到" in item.get_text(" ", strip=True)),
                None,
            )
        if link is None:
            return "状态未知（未找到签到入口）"
        hash_input = soup.select_one("input[name='formhash']")
        formhash = hash_input.get("value") if hash_input else None
        target = urljoin(BASE, link.get("href", ""))
        parsed = urlsplit(target)
        explicit_sign_link = link is not None and "签到" in link.get_text(" ", strip=True)
        valid_path = (parsed.path == "/2b/study_daily_attendance-daily_attendance.html" or
                      (explicit_sign_link and parsed.path.startswith("/2b/") and
                       parsed.path not in {"/2b/", "/2b/forum.php"}))
        if (parsed.scheme != "https" or parsed.hostname != "stage1st.com" or
                not valid_path):
            return "状态未知（签到链接异常）"
        params = dict(parse_qsl(parsed.query))
        if formhash:
            params.setdefault("formhash", formhash)
        if not params.get("formhash"):
            return "状态未知（缺少 formhash）"
        params.setdefault("inajax", "1")
        target = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(params), ""))
        response = await self.http.get(target, follow_redirects=False)
        response.raise_for_status()
        if response.is_redirect:
            return "状态未知（签到页重定向）"
        text = BeautifulSoup(response.text, "html.parser").get_text(" ", strip=True)
        text = re.sub(r"\s+", "", text)
        if re.search(r"已(?:经)?签(?:到|过)|今日已签|已打卡|已经打卡", text):
            return "今日已签"
        if re.search(r"签到成功|打卡成功", text):
            return "签到成功"
        if re.search(r"请(?:先)?登录|尚未登录|需要登录|未登录", text):
            return "未登录"
        if "插件不存在或已关闭" in text:
            return "签到入口不可用"
        return "状态未知（请在网页查看）"

    async def _check_muanyun(self) -> str:
        """Check the current plugin's activity log before sending a sign-in request."""
        page_url = urljoin(BASE, "plugin.php?id=muanyun_053&mobile=no")
        page = await self.http.get(page_url)
        page.raise_for_status()
        soup = BeautifulSoup(page.text, "html.parser")
        today = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")

        def signed_today(document: BeautifulSoup) -> bool:
            for card in document.select(".muanyun-053-card"):
                activity = card.get_text(" ", strip=True)
                if "最近活动" in activity and re.search(
                    rf"{today}\s+\d{{1,2}}:\d{{2}}\s*签到", activity
                ):
                    return True
            return False

        if signed_today(soup):
            return "今日已签"
        if not soup.select_one(".muanyun-053-card"):
            return "状态未知（签到页异常）"

        action_url = urljoin(BASE, "plugin.php?id=muanyun_053&op=checkin&mobile=no")
        result = await self.http.get(action_url)
        result.raise_for_status()
        result_soup = BeautifulSoup(result.text, "html.parser")
        if signed_today(result_soup):
            return "签到成功"
        result_text = result_soup.get_text(" ", strip=True)
        if re.search(r"签到成功|成功签到", result_text):
            return "签到成功"
        if re.search(r"今日已签|今天已经签到|已经签到|签到过", result_text):
            return "今日已签"
        if re.search(r"请(?:先)?登录|尚未登录|需要登录|未登录", result_text):
            return "未登录"

        # The action may redirect to a page without a success message.
        page = await self.http.get(page_url)
        page.raise_for_status()
        if signed_today(BeautifulSoup(page.text, "html.parser")):
            return "签到成功"
        return "状态未知（请在网页查看）"

    async def image(self, url: str, limit: int = 4 * 1024 * 1024) -> bytes:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
            raise ValueError("不支持的图片地址")
        host = parsed.hostname.casefold().rstrip(".")
        if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
            raise ValueError("拒绝访问本机地址")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address and not address.is_global:
            raise ValueError("拒绝访问非公网地址")
        if address is None:
            records = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
            resolved = {ipaddress.ip_address(record[4][0]) for record in records}
            # Some managed proxy/VPN DNS setups map public hosts into RFC 2544's
            # 198.18.0.0/15 range. Permit that synthetic route only for known
            # Stage1st and S1 attachment hosts; reject other non-public answers.
            synthetic_proxy = ipaddress.ip_network("198.18.0.0/15")
            trusted_image_host = (
                host == "stage1st.com" or host.endswith(".stage1st.com") or
                host == "sda1.dev" or host.endswith(".sda1.dev")
            )
            if not resolved or any(
                not item.is_global and not (trusted_image_host and item in synthetic_proxy)
                for item in resolved
            ):
                raise ValueError("图片地址解析到非公网网络")

        chunks: list[bytes] = []
        size = 0
        async with self.image_http.stream("GET", url, follow_redirects=False, timeout=8.0) as response:
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
            if content_type not in {"image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp"}:
                raise ValueError("链接返回的不是图片")
            declared = int(response.headers.get("content-length", "0") or 0)
            if declared > limit:
                raise ValueError("图片超过 4 MiB 限制")
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > limit:
                    raise ValueError("图片超过 4 MiB 限制")
                chunks.append(chunk)
        return b"".join(chunks)

    async def close(self) -> None:
        await self.http.aclose()
        await self.image_http.aclose()
