# Stage1stForumTUI

Stage1st 论坛的非官方终端浏览器，基于 Python + Textual。支持浏览版面、主题和帖子；站点提供签到入口时可在登录后自动签到。

## 项目声明

本项目以 Vibe Coding 的方式开发，代码由 AI 生成并经人工提出需求、审阅和调整。它是社区第三方项目，与 Stage1st 论坛及其运营方没有官方关联，也不代表其立场。

论坛帖子、图片及商标等内容归各自权利人所有。本程序仅在用户使用时读取公开网页；请遵守论坛规则，并尊重内容作者的权益。

## 运行

需要 Python 3.10 或更新版本。在项目根目录执行：

Windows（PowerShell）：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\s1tui.exe
```

macOS / Linux（bash / zsh）：

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -e .
./.venv/bin/s1tui
```

已有 `.venv` 并安装过依赖时，只需运行最后一行；等价的写法分别是 `.\.venv\Scripts\python.exe -m s1tui` 和 `./.venv/bin/python -m s1tui`。也可以先激活虚拟环境：Windows 执行 `.\.venv\Scripts\Activate.ps1`，macOS / Linux 执行 `source .venv/bin/activate`，然后运行 `python -m s1tui` 或 `stage1st-forum-tui`。旧命令 `s1-forum-tui` 和 `s1tui` 仍可使用。

这里用 `python` / `python3` 而非 `py`：部分环境（含通过 uv 或独立安装器装的 Python）没有 `py` 启动器，`py -m venv` 会直接报「找不到命令」。macOS 自带的 `/usr/bin/python3` 通常是 3.9，低于要求；请改用 3.10+ 的解释器创建虚拟环境，例如 `python3.12 -m venv .venv`（Homebrew）或 `uv venv --python 3.11 .venv`。若 `python` / `python3` 也不在 PATH 上，换成解释器的完整路径即可。同理，未激活虚拟环境时用系统 Python 跑 `python -m s1tui` 会因版本过低或缺少依赖报错——务必指向 `.venv` 里的解释器。

TUI 需要一个真正的终端窗口（Windows Terminal、VS Code 集成终端均可），在纯重定向输出的环境里启动没有意义。

## 操作

按 `?` 可在程序内查看完整快捷键。底部只显示常用操作提示。

- `j` / `k`：在版面/主题列表中下移/上移；阅读帖子时向下/上滚动约三分之一屏
- `↑` / `↓` / `←` / `→`：分别与 `k` / `j` / `h` / `l` 相同；方向键不会占用界面底部的快捷键提示
- `g` / `G`（`Shift+g`）：跳到当前列表首项/末项；阅读帖子时跳到本页顶部/底部
- `Tab`：在版面栏和主题栏之间切换焦点；阅读帖子时按 `Tab` 关闭帖子并将焦点移到版面栏；`Enter` 打开当前栏选中的版面或主题
- `h` / `l`：上一页/下一页，`Enter`：打开
- `p`：输入页码并按 `Enter` 直达；`Esc` 取消。标题显示当前页/总页数，最后一页不会继续翻页
- `Shift+L`：登录；输入用户名并按 `Enter` 切到密码，输入密码后按 `Enter` 提交；`Esc` 取消
- `Shift+X`：清除本机登录会话
- `Shift+R`：阅读帖子时写纯文本回复；在编辑框按 `Tab` 切换到按钮并发送，`Esc` 取消
- `i`：切换图片预览（需要终端支持 Kitty graphics protocol）；不支持时按 `i` 会在底部提示
- `Backspace` / `Esc`：返回
- `r`：刷新，`o`：在系统浏览器打开当前帖子，`q`：退出

图片预览通过 [Kitty graphics protocol](https://sw.kovidgoyal.net/kitty/graphics-protocol/) 的 Unicode placeholders 显示真实位图：图片数据只在首次渲染时传输一次，屏幕上用普通占位字符格承载，因此滚动、裁剪和刷新都由 Textual 正常处理。默认只显示占位文字，`i` 开启后每页最多预览 8 张；每张图片最多下载 4 MiB，单张尺寸限制为 2000 万像素。若图片源不可达或格式不支持，会显示失败占位。

支持 Kitty Unicode placeholders 的终端包括 Kitty、Ghostty、WezTerm；macOS 自带的 Terminal.app、Alacritty 不支持，iTerm2 走的是 OSC 1337 内联图片而非占位符路径，因此本实现也不支持。在这些终端里按 `i` 会提示改用上述终端或按 `o` 在浏览器打开。tmux 默认判定为不支持（会丢弃图形转义序列），可用 `S1TUI_KITTY=1` 强制尝试，但需要 tmux 配置 `allow-passthrough` 且终端支持透传；`S1TUI_KITTY=0` 可强制关闭检测。

阅读帖子时，右侧内容区会占满可用高度并显示独立滚动条；`j` / `k` 每次滚动约三分之一屏。

登录成功后仅将论坛会话 Cookie 保存在系统凭据库，不保存密码。下次启动时若会话仍有效，程序会检查新版 `muanyun_053` 签到页的今日记录，并在尚未签到时尝试自动签到；首次登录后也会执行一次检查。底部持续显示账号和签到状态；只有论坛明确返回成功或今日已签才显示对应状态。若登录后的页面没有签到入口，程序会显示“状态未知（未找到签到入口）”。纯文本回复会通过当前帖子页面的快速回帖表单提交；提交失败时编辑框保留草稿。若论坛要求验证码或安全提问，请在网页中操作。当前版本尚不支持发新帖或收藏。论坛访问策略、HTML 结构或网络限制变化时，登录、签到和回帖逻辑可能需要调整。

## 常见问题

**启动时报 `ImportError: cannot import name '_imaging' from 'PIL'`**

`.venv` 的 `site-packages` 里混入了别的 Python 版本编译的 Pillow（扩展名形如 `_imaging.cp311-win_amd64.pyd`，与当前解释器版本不符）。按当前解释器重装一次即可：

```powershell
.\.venv\Scripts\python.exe -m pip install --force-reinstall --no-cache-dir "Pillow>=10.0"
```

安装完成后 `.venv\Lib\site-packages\PIL\` 下的 `.pyd` 应带有与解释器一致的版本标记（例如 3.13 对应 `cp313`）。

**`py` 或 `python` 提示找不到命令**

`py` 启动器并非所有环境都有；`python` 也可能不在 PATH 上。先在终端执行 `python -V` 确认版本不低于 3.10，找不到就改用解释器的完整路径。

**`ModuleNotFoundError: No module named 'textual'`（或 httpx、PIL 等）**

用系统 Python 跑了程序，而不是 `.venv` 里的。改用 `.\.venv\Scripts\python.exe -m s1tui`，或先激活虚拟环境。
