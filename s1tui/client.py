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

    async def reply(self, thread: Thread, message: str) -> None:
        """Submit plain text through this thread's current fast-reply form."""
        if not message.strip():
            raise ValueError("回复内容不能为空")
        thread_url = urlsplit(thread.url)
        thread_match = re.fullmatch(r"/2b/thread-(\d+)-\d+-\d+\.html", thread_url.path)
        if (thread_url.scheme != "https" or thread_url.hostname != "stage1st.com" or
                not thread_match):
            raise ValueError("帖子地址异常")
        thread_id = thread_match.group(1)

        page = await self.http.get(thread.url)
        page.raise_for_status()
        form = BeautifulSoup(page.text, "html.parser").select_one("#fastpostform")
        if form is None or form.get("method", "").lower() != "post":
            raise ValueError("当前帖子没有可用的回帖表单")
        if form.select_one("[name='seccodeverify'], [name='secanswer'], .seccheck"):
            raise ValueError("论坛要求验证码或安全提问，请在网页中回帖")
        if form.select_one("textarea[name='message']") is None:
            raise ValueError("回帖表单缺少正文输入框")
        action = urljoin(BASE, form.get("action", ""))
        parsed = urlsplit(action)
        params = dict(parse_qsl(parsed.query))
        if (parsed.scheme != "https" or parsed.hostname != "stage1st.com" or
                parsed.path != "/2b/forum.php" or params.get("mod") != "post" or
                params.get("action") != "reply" or params.get("tid") != thread_id or
                not params.get("fid", "").isdigit() or params.get("replysubmit") != "yes"):
            raise ValueError("回帖表单地址异常")
        formhash = form.select_one("input[name='formhash'][value]")
        if formhash is None or not formhash.get("value"):
            raise ValueError("回帖表单缺少 formhash")
        payload = {"formhash": formhash["value"], "message": message}
        for field in ("posttime", "usesig", "subject"):
            node = form.select_one(f"input[name='{field}']")
            if node is not None:
                payload[field] = node.get("value", "")
        submit = form.select_one("[name='replysubmit']")
        if submit is not None:
            payload["replysubmit"] = submit.get("value", "replysubmit")
        response = await self.http.post(action, data=payload, headers={"Referer": thread.url},
                                        follow_redirects=False)
        response.raise_for_status()
        result = BeautifulSoup(response.text, "html.parser")
        notice = result.select_one("#messagetext p, .alert_error, .alert_info")
        result_text = (notice or result).get_text(" ", strip=True)
        if re.search(r"回复发布成功|回复成功|发表回复成功|回帖成功", result_text):
            return
        if response.is_redirect:
            redirect = urlsplit(urljoin(action, response.headers.get("location", "")))
            redirect_params = dict(parse_qsl(redirect.query))
            same_thread = (
                re.fullmatch(rf"/2b/thread-{thread_id}-\d+-\d+\.html", redirect.path) or
                (redirect.path == "/2b/forum.php" and
                 (redirect_params.get("tid") == thread_id or
                  redirect_params.get("ptid") == thread_id))
            )
            if redirect.scheme == "https" and redirect.hostname == "stage1st.com" and same_thread:
                return
        detail = re.sub(r"\s+", " ", result_text)[:120] or "论坛未确认提交结果"
        raise ValueError(f"回帖未确认：{detail}")

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

    async def check_in(self) -> str:
        """Check today's activity, then submit the current daily check-in form if needed."""
        page_url = urljoin(BASE, "muanyun_053-muanyun_053.html?mobile=no")
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
        form = soup.select_one("form[action*='op=checkin']")
        if form is None or form.get("method", "").lower() != "post":
            return "状态未知（未找到签到表单）"
        button = form.select_one("button[type='submit'].muanyun-053-btn-success")
        if button is None or button.has_attr("disabled") or "每日签到" not in button.get_text(" ", strip=True):
            return "状态未知（签到按钮不可用）"
        formhash = form.select_one("input[name='formhash'][value]")
        submit = form.select_one("input[name='checkinsubmit'][value]")
        if formhash is None or submit is None:
            return "状态未知（签到表单缺少必要字段）"
        action_url = urljoin(BASE, form.get("action", ""))
        action = urlsplit(action_url)
        params = dict(parse_qsl(action.query))
        if (action.scheme != "https" or action.hostname != "stage1st.com" or
                action.path != "/2b/plugin.php" or params.get("id") != "muanyun_053" or
                params.get("op") != "checkin"):
            return "状态未知（签到表单地址异常）"
        params["mobile"] = "no"
        action_url = urlunsplit((action.scheme, action.netloc, action.path, urlencode(params), ""))
        result = await self.http.post(
            action_url,
            data={"formhash": formhash["value"], "checkinsubmit": submit["value"]},
            headers={"Referer": page_url},
            follow_redirects=False,
        )
        result.raise_for_status()
        result_soup = BeautifulSoup(result.text, "html.parser")
        if signed_today(result_soup):
            return "签到成功"
        notice = result_soup.select_one("#messagetext p, .alert_error, .alert_info")
        result_text = (notice or result_soup).get_text(" ", strip=True)
        if re.search(r"签到成功|成功签到", result_text):
            return "签到成功"
        if re.search(r"今日已签|今天已经签到|已经签到|签到过", result_text):
            return "今日已签"
        if re.search(r"请(?:先)?登录|尚未登录|需要登录|未登录", result_text):
            return "未登录"

        # A successful form submission may redirect without a readable message.
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
