from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .constants import BASE


@dataclass
class Forum:
    title: str
    url: str


@dataclass
class Thread:
    title: str
    url: str
    author: str = ""
    replies: str = ""
    updated: str = ""


@dataclass
class Post:
    author: str
    floor: str
    content: str
    images: list[tuple[str | None, str]]


def parse_forums(html: str) -> list[Forum]:
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, Forum] = {}
    for anchor in soup.select(".fl_tb a[href^='forum-']"):
        title = anchor.get_text(" ", strip=True) or anchor.get("title", "")
        href = anchor.get("href", "")
        if title and href:
            found[href] = Forum(title, urljoin(BASE, href))
    return list(found.values())


def parse_total_pages(soup: BeautifulSoup) -> int:
    pagination = soup.select_one(".pg")
    if pagination is None:
        return 1
    label = pagination.select_one("label span")
    if label:
        numbers = re.findall(r"\d+", label.get_text(" ", strip=True))
        if numbers:
            return max(1, int(numbers[-1]))
    last = pagination.select_one("a.last")
    if last:
        numbers = re.findall(r"\d+", last.get_text(" ", strip=True))
        if numbers:
            return max(1, int(numbers[-1]))
    numbers = [int(node.get_text(strip=True)) for node in pagination.select("a, strong")
               if node.get_text(strip=True).isdigit()]
    return max(numbers, default=1)


def parse_threads(html: str) -> tuple[list[Thread], int]:
    soup = BeautifulSoup(html, "html.parser")
    result: list[Thread] = []
    for row in soup.select("tbody[id^='normalthread_']"):
        link = row.select_one("th a.s.xst") or row.select_one("th a[href^='thread-']")
        if not link:
            continue
        author = row.select_one("td.by cite")
        replies = row.select_one("td.num a")
        updated = row.select_one("td.by em a") or row.select_one("td.by em span")
        result.append(Thread(
            link.get_text(" ", strip=True), urljoin(BASE, link.get("href", "")),
            author.get_text(" ", strip=True) if author else "",
            replies.get_text(" ", strip=True) if replies else "",
            updated.get_text(" ", strip=True) if updated else "",
        ))
    return result, parse_total_pages(soup)


def parse_posts(html: str, page_url: str) -> tuple[str, list[Post], int]:
    soup = BeautifulSoup(html, "html.parser")
    title_node = soup.select_one("#thread_subject")
    posts: list[Post] = []
    for node in soup.select("div[id^='post_']"):
        author = node.select_one(".authi .xw1") or node.select_one(".authi a")
        content = node.select_one("td.t_f")
        if not content:
            continue
        # Replace image-only content with a readable marker and remove scripts/styles.
        for junk in content.select("script, style, .aimg_tip"):
            junk.decompose()
        images: list[tuple[str | None, str]] = []
        for image in content.select("img"):
            alt = image.get("alt") or "图片"
            source = (image.get("file") or image.get("zoomfile") or
                      image.get("data-src") or image.get("src"))
            source = urljoin(page_url, source) if source else None
            if source and source.startswith("data:"):
                source = None
            if source and "/image/smiley/" in source:
                image.replace_with("☺")
                continue
            index = len(images)
            images.append((source, alt))
            image.replace_with(f"\n[[S1TUI_IMAGE_{index}]]\n")
        text = content.get_text("\n", strip=True)
        if text:
            floor_node = node.select_one(".pi em")
            floor = floor_node.get_text(" ", strip=True) if floor_node else "主楼"
            posts.append(Post(author.get_text(" ", strip=True) if author else "匿名", floor, text, images))
    return title_node.get_text(" ", strip=True) if title_node else page_url, posts, parse_total_pages(soup)
