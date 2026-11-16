# Stage1stForumTUI

Stage1st 论坛的非官方终端浏览器，基于 Python + Textual。支持浏览版面、主题和帖子；站点提供签到入口时可在登录后自动签到。

## 项目声明

本项目以 Vibe Coding 的方式开发，代码由 AI 生成并经人工提出需求、审阅和调整。它是社区第三方项目，与 Stage1st 论坛及其运营方没有官方关联，也不代表其立场。

论坛帖子、图片及商标等内容归各自权利人所有。本程序仅在用户使用时读取公开网页；请遵守论坛规则，并尊重内容作者的权益。

## 运行

需要 [uv](https://docs.astral.sh/uv/getting-started/installation/)。在项目根目录执行以下命令；uv 会选用 Python 3.11 创建 `.venv`，并把本项目及依赖安装到这个虚拟环境。无需激活环境。

Windows（PowerShell）：

```powershell
uv venv --python 3.11 .venv
uv pip install --python .venv\Scripts\python.exe -e .
.\.venv\Scripts\s1tui.exe
```

macOS / Linux（bash / zsh）：

```bash
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -e .
./.venv/bin/s1tui
```

安装完成后，日常启动只需运行对应平台的最后一行。也可以通过虚拟环境的 Python 运行：Windows 用 `.\.venv\Scripts\python.exe -m s1tui`，macOS / Linux 用 `./.venv/bin/python -m s1tui`。旧命令 `s1-forum-tui` 和 `s1tui` 仍可使用。

TUI 需要一个真正的终端窗口（Windows Terminal、VS Code 集成终端均可），在纯重定向输出的环境里启动没有意义。

连接问题可用 `--debug` 启动，例如 `./.venv/bin/s1tui --debug`；Windows 在上方启动命令后追加 `--debug`。日志写入当前目录的 `s1tui-debug.log`；也可用 `--debug-log 路径` 指定文件。日志记录会话恢复、论坛请求的路径/状态/耗时、解析结果和异常，不记录密码、Cookie 或网页正文。复现后退出程序，查看或提供日志末尾的记录。

如果日志显示请求经由 HTTP 代理，并在 TLS 握手时报 `httpx.ConnectError`，可用 `./.venv/bin/s1tui --debug --no-proxy` 尝试直连。`--no-proxy` 会忽略 HTTPX 使用的环境代理和 TLS 证书设置；若所在网络必须使用代理，应修复代理配置后再正常启动。

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

**`uv` 提示找不到命令**

按 [uv 安装说明](https://docs.astral.sh/uv/getting-started/installation/)安装后，重新打开终端并运行 `uv --version` 确认命令可用。

**已有 `.venv`，但虚拟环境的 Python 版本不符合要求**

项目需要 Python 3.10 或更新版本。若现有 `.venv` 是用较旧版本创建的，先保存其中需要保留的自定义内容，再在项目根目录用 `uv venv --python 3.11 --clear .venv` 重建环境，并重新执行上方对应平台的第二条命令安装依赖。`--clear` 会清空原虚拟环境。

**启动时报 `ImportError: cannot import name '_imaging' from 'PIL'`**

Pillow 的已安装文件可能与当前虚拟环境不匹配。在项目根目录重新安装 Pillow：

Windows（PowerShell）：

```powershell
uv pip install --python .venv\Scripts\python.exe --reinstall --no-cache "Pillow>=10.0"
```

macOS / Linux（bash / zsh）：

```bash
uv pip install --python .venv/bin/python --reinstall --no-cache "Pillow>=10.0"
```

**`ModuleNotFoundError: No module named 'textual'`（或 httpx、PIL 等）**

在项目根目录重新执行上方对应平台的第二条命令，确认依赖已安装到项目的 `.venv`。启动时使用 `.venv` 中的 `s1tui` 或 Python 路径。
