from __future__ import annotations

import asyncio
import re
from contextlib import suppress
from io import BytesIO

from PIL import Image, ImageOps
from rich.console import Group
from rich.text import Text
from rich_pixels import Pixels
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Footer, Header, Input, ListItem, ListView, Static

from .client import ForumClient
from .parser import Forum, Thread


class Entry(ListItem):
    def __init__(self, label: str, value: object) -> None:
        super().__init__(Static(label))
        self.value = value


class S1Tui(App[None]):
    """Read-only Stage1st browser. Enter drills in, Backspace returns."""

    TITLE = "Stage1stForumTUI · 非官方只读浏览器"
    CSS = """
    Screen { layout: vertical; }
    #body { height: 1fr; }
    #sidebar { width: 30%; min-width: 24; border: round $accent; }
    #main { width: 1fr; border: round $primary; }
    #heading { height: 3; padding: 1; text-style: bold; }
    ListView { height: 1fr; }
    #detail-scroll { height: 1fr; overflow-y: scroll; scrollbar-size-vertical: 1; }
    #detail-content { width: 100%; height: auto; padding: 1 2; }
    #page-input { display: none; }
    #status { height: 1; dock: bottom; padding-left: 1; color: $text-muted; }
    """
    BINDINGS = [("q", "quit", "退出"), ("backspace,escape", "back", "返回"),
                ("r", "refresh", "刷新"), ("l", "next_page", "下一页"),
                ("h", "prev_page", "上一页"), ("j", "cursor_down", "向下"),
                ("k", "cursor_up", "向上"), ("i", "toggle_images", "图片预览"),
                Binding("left", "arrow_left", show=False, priority=True),
                Binding("down", "arrow_down", show=False, priority=True),
                Binding("up", "arrow_up", show=False, priority=True),
                Binding("right", "arrow_right", show=False, priority=True),
                ("g", "jump_start", "页首"), ("G", "jump_end", "页尾"),
                ("p", "page_input", "跳到页码"),
                Binding("tab", "switch_pane", "切换栏", priority=True),
                ("o", "open_web", "浏览器打开")]

    def __init__(self) -> None:
        super().__init__()
        self.client = ForumClient()
        self.forums: list[Forum] = []
        self.threads: list[Thread] = []
        self.page = 1
        self.total_pages = 1
        self.thread_page = 1
        self.mode = "forums"
        self.selected_forum: Forum | None = None
        self.selected_thread: Thread | None = None
        self.current_posts = []
        self.image_preview = False
        self.image_cache: dict[str, Pixels | None] = {}
        self.image_task: asyncio.Task[None] | None = None
        self.max_previews_per_page = 8

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield Static("版面", id="heading")
                yield ListView(id="forums")
            with Vertical(id="main"):
                yield Static("正在连接 Stage1st…", id="main-heading")
                yield ListView(id="items")
                with VerticalScroll(id="detail-scroll"):
                    yield Static("", id="detail-content")
                yield Input(placeholder="输入页码，Enter 跳转，Esc 取消", type="integer",
                            restrict=r"[0-9]*", id="page-input")
        yield Static("连接中…", id="status")
        yield Footer()

    async def on_mount(self) -> None:
        await self.load_forums()

    async def on_unmount(self) -> None:
        task = self.image_task
        self.cancel_image_task()
        if task:
            with suppress(asyncio.CancelledError):
                await task
        await self.client.close()

    def cancel_image_task(self) -> None:
        if self.image_task and not self.image_task.done():
            self.image_task.cancel()
        self.image_task = None

    def status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)

    async def load_forums(self) -> None:
        self.status("读取版面列表…")
        try:
            self.forums = await self.client.forums()
            listing = self.query_one("#forums", ListView)
            listing.clear()
            for forum in self.forums:
                await listing.append(Entry(forum.title, forum))
            self.status(f"加载了 {len(self.forums)} 个版面 · 只读模式")
            if self.forums:
                listing.index = 0
                await self.show_forum(self.forums[0])
        except Exception as exc:
            self.status(f"连接失败：{exc}")

    async def show_forum(self, forum: Forum) -> None:
        self.cancel_image_task()
        self.mode, self.selected_forum, self.page = "threads", forum, 1
        self.total_pages = 1
        await self.load_threads()

    async def load_threads(self, page: int | None = None) -> bool:
        assert self.selected_forum
        target = self.page if page is None else page
        self.status(f"读取 {self.selected_forum.title} · 第 {target} 页…")
        try:
            threads, total = await self.client.threads(self.selected_forum, target)
            if target > total:
                self.status(f"页码超出范围：共 {total} 页")
                return False
            self.threads = threads
            self.page, self.total_pages = target, total
            listing = self.query_one("#items", ListView)
            listing.styles.display = "block"
            self.query_one("#detail-scroll", VerticalScroll).styles.display = "none"
            listing.clear()
            for thread in self.threads:
                label = f"{thread.title}\n{thread.author} · 回复 {thread.replies} · {thread.updated}"
                await listing.append(Entry(label, thread))
            self.query_one("#main-heading", Static).update(
                f"{self.selected_forum.title} · 第 {self.page}/{self.total_pages} 页"
            )
            self.query_one("#detail-content", Static).update("")
            self.status(f"{len(self.threads)} 个主题 · 第 {self.page}/{self.total_pages} 页 · h/l 翻页 · p 跳页")
            if self.threads:
                listing.index = 0
            listing.focus()
            return True
        except Exception as exc:
            self.status(f"读取主题失败：{exc}")
            return False

    async def show_thread(self, thread: Thread) -> None:
        self.thread_page = self.page
        self.mode, self.selected_thread, self.page = "posts", thread, 1
        self.total_pages = 1
        await self.load_posts()

    async def load_posts(self, page: int | None = None) -> bool:
        assert self.selected_thread
        target = self.page if page is None else page
        self.status(f"读取帖子第 {target} 页…")
        try:
            title, posts, total = await self.client.posts(self.selected_thread, target)
            if target > total:
                self.status(f"页码超出范围：共 {total} 页")
                return False
            self.cancel_image_task()
            self.page, self.total_pages = target, total
            self.query_one("#main-heading", Static).update(
                f"{title} · 第 {self.page}/{self.total_pages} 页"
            )
            listing = self.query_one("#items", ListView)
            listing.styles.display = "none"
            self.query_one("#detail-scroll", VerticalScroll).styles.display = "block"
            listing.clear()
            self.current_posts = posts
            await self.render_posts(title)
            self.query_one("#detail-scroll", VerticalScroll).scroll_home(
                animate=False, immediate=True
            )
            self.status(f"{len(posts)} 条回复 · 第 {self.page}/{self.total_pages} 页 · h/l 翻页 · p 跳页")
            return True
        except Exception as exc:
            self.status(f"读取帖子失败：{exc}")
            return False

    async def render_posts(self, title: str = "") -> None:
        parts = []
        image_count = 0
        pending: list[str] = []
        for post in self.current_posts:
            parts.append(Text(f"── {post.floor} · {post.author} ──\n", style="bold cyan"))
            chunks = re.split(r"(\[\[S1TUI_IMAGE_\d+\]\])", post.content)
            for chunk in chunks:
                match = re.fullmatch(r"\[\[S1TUI_IMAGE_(\d+)\]\]", chunk)
                if not match:
                    if chunk:
                        parts.append(Text(chunk))
                    continue
                index = int(match.group(1))
                url, alt = post.images[index]
                image_count += 1
                if self.image_preview and url and image_count <= self.max_previews_per_page:
                    if url not in self.image_cache:
                        if url not in pending:
                            pending.append(url)
                        parts.append(Text(f"\n[{alt} · 加载中…]\n", style="dim"))
                        continue
                    rendered = self.image_cache[url]
                    if rendered is not None:
                        parts.extend([Text(f"\n[{alt}]\n", style="dim"), rendered, Text("\n")])
                    else:
                        parts.append(Text(f"\n[图片预览失败：{alt}]\n", style="yellow"))
                else:
                    note = "本页预览数量已达上限" if self.image_preview and url else alt
                    parts.append(Text(f"\n[图片：{note}]\n", style="dim"))
            parts.append(Text("\n"))
        if not parts:
            parts.append(Text("本页没有可显示的回复"))
        self.query_one("#detail-content", Static).update(Group(*parts))
        self.status(
            f"{len(self.current_posts)} 条回复 · 第 {self.page}/{self.total_pages} 页 · "
            f"{image_count} 张图 · 图片预览{'开' if self.image_preview else '关'} · 按 i 切换"
        )
        if pending:
            self.prefetch_images(pending)

    def prefetch_images(self, urls: list[str]) -> None:
        """Download previews in the background so the UI stays responsive."""
        self.cancel_image_task()
        self.image_task = asyncio.create_task(self._load_images(urls))

    async def _load_images(self, urls: list[str]) -> None:
        # Limit downloads and decoding together to bound memory use.
        semaphore = asyncio.Semaphore(2)

        async def fetch_one(url: str) -> tuple[str, Pixels | None]:
            try:
                async with semaphore:
                    data = await self.client.image(url)
                    return url, await asyncio.to_thread(self._pixels_from_bytes, data)
            except asyncio.CancelledError:
                raise
            except Exception:
                return url, None

        results = await asyncio.gather(*(fetch_one(url) for url in urls))
        if len(self.image_cache) + len(results) > 32:
            self.image_cache.clear()
        for url, pixels in results:
            self.image_cache[url] = pixels
        if self.image_preview and self.mode == "posts":
            await self.render_posts()

    @staticmethod
    def _pixels_from_bytes(data: bytes) -> Pixels:
        with Image.open(BytesIO(data)) as source:
            if source.width * source.height > 20_000_000:
                raise ValueError("图片分辨率过大")
            source.seek(0)
            image = source.convert("RGB")
            image = ImageOps.contain(image, (64, 40))
            return Pixels.from_image(image)

    @on(ListView.Selected)
    async def selected(self, event: ListView.Selected) -> None:
        if not isinstance(event.item, Entry):
            return
        value = event.item.value
        if event.list_view.id == "forums" and isinstance(value, Forum):
            await self.show_forum(value)
        elif self.mode == "threads" and isinstance(value, Thread):
            await self.show_thread(value)

    async def action_back(self) -> None:
        page_input = self.query_one("#page-input", Input)
        if page_input.styles.display != "none":
            page_input.styles.display = "none"
            if self.mode == "threads":
                self.active_list().focus()
            self.status("已取消跳页")
            return
        if self.mode == "posts":
            self.cancel_image_task()
            self.mode = "threads"
            self.selected_thread = None
            self.query_one("#detail-content", Static).update("")
            self.page = self.thread_page
            await self.load_threads()
        else:
            self.query_one("#forums", ListView).focus()

    async def action_switch_pane(self) -> None:
        if self.page_input_open():
            return
        if self.mode == "posts":
            # 阅读界面：切回主题列表
            self.cancel_image_task()
            self.mode = "threads"
            self.selected_thread = None
            self.query_one("#detail-content", Static).update("")
            self.page = self.thread_page
            await self.load_threads()
            return
        if self.mode != "threads":
            return
        forums = self.query_one("#forums", ListView)
        topics = self.query_one("#items", ListView)
        if forums.has_focus:
            topics.focus()
            self.status("焦点：主题 · j/k 选择主题 · Enter 阅读 · Tab 切换栏")
        else:
            forums.focus()
            self.status("焦点：版面 · j/k 选择版面 · Enter 打开 · Tab 切换栏")

    def page_input_open(self) -> bool:
        return self.query_one("#page-input", Input).styles.display != "none"

    def action_arrow_down(self) -> None:
        if not self.page_input_open():
            self.action_cursor_down()

    def action_arrow_up(self) -> None:
        if not self.page_input_open():
            self.action_cursor_up()

    async def action_arrow_left(self) -> None:
        if self.page_input_open():
            self.query_one("#page-input", Input).action_cursor_left()
        else:
            await self.action_prev_page()

    async def action_arrow_right(self) -> None:
        if self.page_input_open():
            self.query_one("#page-input", Input).action_cursor_right()
        else:
            await self.action_next_page()

    def action_cursor_down(self) -> None:
        if self.mode == "posts":
            view = self.query_one("#detail-scroll", VerticalScroll)
            view.scroll_relative(y=max(3, view.size.height // 3), animate=False, immediate=True)
            return
        listing = self.active_list()
        if listing.children:
            listing.index = min((listing.index or 0) + 1, len(listing.children) - 1)

    def action_cursor_up(self) -> None:
        if self.mode == "posts":
            view = self.query_one("#detail-scroll", VerticalScroll)
            view.scroll_relative(y=-max(3, view.size.height // 3), animate=False, immediate=True)
            return
        listing = self.active_list()
        if listing.children:
            listing.index = max((listing.index or 0) - 1, 0)

    def active_list(self) -> ListView:
        forums = self.query_one("#forums", ListView)
        return forums if self.mode == "forums" or forums.has_focus else self.query_one("#items", ListView)

    def action_jump_start(self) -> None:
        if self.mode == "posts":
            self.query_one("#detail-scroll", VerticalScroll).scroll_to(
                y=0, animate=False, immediate=True
            )
            return
        listing = self.active_list()
        if listing.children:
            listing.index = 0

    def action_jump_end(self) -> None:
        if self.mode == "posts":
            view = self.query_one("#detail-scroll", VerticalScroll)
            view.scroll_to(y=view.max_scroll_y, animate=False, immediate=True)
            return
        listing = self.active_list()
        if listing.children:
            listing.index = len(listing.children) - 1

    async def action_refresh(self) -> None:
        if self.mode == "threads":
            await self.load_threads()
        elif self.mode == "posts":
            await self.load_posts()
        else:
            await self.load_forums()

    async def action_next_page(self) -> None:
        if self.mode in ("threads", "posts"):
            if self.page >= self.total_pages:
                self.status(f"已是最后一页：{self.page}/{self.total_pages}")
                return
            target = self.page + 1
            await (self.load_posts(target) if self.mode == "posts" else self.load_threads(target))

    async def action_prev_page(self) -> None:
        if self.mode in ("threads", "posts"):
            if self.page <= 1:
                self.status(f"已是第一页：{self.page}/{self.total_pages}")
                return
            target = self.page - 1
            await (self.load_posts(target) if self.mode == "posts" else self.load_threads(target))

    def action_page_input(self) -> None:
        if self.mode not in ("threads", "posts"):
            return
        page_input = self.query_one("#page-input", Input)
        page_input.value = ""
        page_input.placeholder = f"输入页码 (1-{self.total_pages})，Enter 跳转，Esc 取消"
        page_input.styles.display = "block"
        page_input.focus()

    @on(Input.Submitted, "#page-input")
    async def submit_page(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        if not re.fullmatch(r"[0-9]+", value):
            self.status("请输入有效页码")
            return
        target = int(value)
        if not 1 <= target <= self.total_pages:
            self.status(f"页码范围：1-{self.total_pages}")
            return
        self.query_one("#page-input", Input).styles.display = "none"
        if target == self.page:
            self.status(f"当前是第 {self.page}/{self.total_pages} 页")
            if self.mode == "threads":
                self.active_list().focus()
            return
        await (self.load_posts(target) if self.mode == "posts" else self.load_threads(target))

    async def action_toggle_images(self) -> None:
        if self.mode != "posts":
            return
        self.image_preview = not self.image_preview
        if not self.image_preview:
            self.cancel_image_task()
        self.status("正在加载图片预览…" if self.image_preview else "已关闭图片预览")
        await self.render_posts()

    def action_open_web(self) -> None:
        import webbrowser
        if self.selected_thread:
            webbrowser.open(self.selected_thread.url)


def main() -> None:
    S1Tui().run()


if __name__ == "__main__":
    main()
