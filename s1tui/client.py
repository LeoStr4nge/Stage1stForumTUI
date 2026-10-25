from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import httpx

from .constants import BASE
from .parser import Forum, Post, Thread, parse_forums, parse_posts, parse_threads


class ForumClient:
    def __init__(self) -> None:
        self.http = httpx.AsyncClient(
            headers={"User-Agent": "S1ForumTUI/0.1 (unofficial read-only forum client)"},
            follow_redirects=True,
            timeout=20.0,
        )

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
        async with self.http.stream("GET", url, follow_redirects=False, timeout=8.0) as response:
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
