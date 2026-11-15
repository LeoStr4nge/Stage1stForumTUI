"""Render images with the Kitty graphics protocol inside Textual widgets.

Uses Unicode placeholders (``U=1``): image data is transmitted once out of band,
then displayed with ordinary printable placeholder cells. Because placeholders
are normal cells, Textual's compositor can diff, scroll, clip and clear them like
any other text -- unlike Sixel / iTerm2 inline images, which are cursor-anchored
objects the compositor cannot see.

Protocol reference: https://sw.kovidgoyal.net/kitty/graphics-protocol/
"""

from __future__ import annotations

import base64
import os
import struct
import sys
from io import BytesIO
from itertools import count
from random import randint

from PIL import Image, ImageOps
from rich.console import Console, ConsoleOptions, RenderResult
from rich.measure import Measurement
from rich.segment import Segment
from rich.style import Style

try:  # POSIX only; Windows terminals fall back to a default cell size.
    import fcntl
    import termios
except ImportError:  # pragma: no cover - platform specific
    fcntl = None
    termios = None

_START = "\x1b_G"
_END = "\x1b\\"
_PLACEHOLDER = 0x10EEEE

# Kitty's placeholder diacritics encode numbers by their index in this list.
# See the "Unicode placeholders" section of the graphics protocol spec.
_NUMBER_TO_DIACRITIC = [
    0x00305, 0x0030D, 0x0030E, 0x00310, 0x00312, 0x0033D, 0x0033E, 0x0033F, 0x00346, 0x0034A, 0x0034B, 0x0034C,
    0x00350, 0x00351, 0x00352, 0x00357, 0x0035B, 0x00363, 0x00364, 0x00365, 0x00366, 0x00367, 0x00368, 0x00369,
    0x0036A, 0x0036B, 0x0036C, 0x0036D, 0x0036E, 0x0036F, 0x00483, 0x00484, 0x00485, 0x00486, 0x00487, 0x00592,
    0x00593, 0x00594, 0x00595, 0x00597, 0x00598, 0x00599, 0x0059C, 0x0059D, 0x0059E, 0x0059F, 0x005A0, 0x005A1,
    0x005A8, 0x005A9, 0x005AB, 0x005AC, 0x005AF, 0x005C4, 0x00610, 0x00611, 0x00612, 0x00613, 0x00614, 0x00615,
    0x00616, 0x00617, 0x00657, 0x00658, 0x00659, 0x0065A, 0x0065B, 0x0065D, 0x0065E, 0x006D6, 0x006D7, 0x006D8,
    0x006D9, 0x006DA, 0x006DB, 0x006DC, 0x006DF, 0x006E0, 0x006E1, 0x006E2, 0x006E4, 0x006E7, 0x006E8, 0x006EB,
    0x006EC, 0x00730, 0x00732, 0x00733, 0x00735, 0x00736, 0x0073A, 0x0073D, 0x0073F, 0x00740, 0x00741, 0x00743,
    0x00745, 0x00747, 0x00749, 0x0074A, 0x007EB, 0x007EC, 0x007ED, 0x007EE, 0x007EF, 0x007F0, 0x007F1, 0x007F3,
    0x00816, 0x00817, 0x00818, 0x00819, 0x0081B, 0x0081C, 0x0081D, 0x0081E, 0x0081F, 0x00820, 0x00821, 0x00822,
    0x00823, 0x00825, 0x00826, 0x00827, 0x00829, 0x0082A, 0x0082B, 0x0082C, 0x0082D, 0x00951, 0x00953, 0x00954,
    0x00F82, 0x00F83, 0x00F86, 0x00F87, 0x0135D, 0x0135E, 0x0135F, 0x017DD, 0x0193A, 0x01A17, 0x01A75, 0x01A76,
    0x01A77, 0x01A78, 0x01A79, 0x01A7A, 0x01A7B, 0x01A7C, 0x01B6B, 0x01B6D, 0x01B6E, 0x01B6F, 0x01B70, 0x01B71,
    0x01B72, 0x01B73, 0x01CD0, 0x01CD1, 0x01CD2, 0x01CDA, 0x01CDB, 0x01CE0, 0x01DC0, 0x01DC1, 0x01DC3, 0x01DC4,
    0x01DC5, 0x01DC6, 0x01DC7, 0x01DC8, 0x01DC9, 0x01DCB, 0x01DCC, 0x01DD1, 0x01DD2, 0x01DD3, 0x01DD4, 0x01DD5,
    0x01DD6, 0x01DD7, 0x01DD8, 0x01DD9, 0x01DDA, 0x01DDB, 0x01DDC, 0x01DDD, 0x01DDE, 0x01DDF, 0x01DE0, 0x01DE1,
    0x01DE2, 0x01DE3, 0x01DE4, 0x01DE5, 0x01DE6, 0x01DFE, 0x020D0, 0x020D1, 0x020D4, 0x020D5, 0x020D6, 0x020D7,
    0x020DB, 0x020DC, 0x020E1, 0x020E7, 0x020E9, 0x020F0, 0x02CEF, 0x02CF0, 0x02CF1, 0x02DE0, 0x02DE1, 0x02DE2,
    0x02DE3, 0x02DE4, 0x02DE5, 0x02DE6, 0x02DE7, 0x02DE8, 0x02DE9, 0x02DEA, 0x02DEB, 0x02DEC, 0x02DED, 0x02DEE,
    0x02DEF, 0x02DF0, 0x02DF1, 0x02DF2, 0x02DF3, 0x02DF4, 0x02DF5, 0x02DF6, 0x02DF7, 0x02DF8, 0x02DF9, 0x02DFA,
    0x02DFB, 0x02DFC, 0x02DFD, 0x02DFE, 0x02DFF, 0x0A66F, 0x0A67C, 0x0A67D, 0x0A6F0, 0x0A6F1, 0x0A8E0, 0x0A8E1,
    0x0A8E2, 0x0A8E3, 0x0A8E4, 0x0A8E5, 0x0A8E6, 0x0A8E7, 0x0A8E8, 0x0A8E9, 0x0A8EA, 0x0A8EB, 0x0A8EC, 0x0A8ED,
    0x0A8EE, 0x0A8EF, 0x0A8F0, 0x0A8F1, 0x0AAB0, 0x0AAB2, 0x0AAB3, 0x0AAB7, 0x0AAB8, 0x0AABE, 0x0AABF, 0x0AAC1,
    0x0FE20, 0x0FE21, 0x0FE22, 0x0FE23, 0x0FE24, 0x0FE25, 0x0FE26, 0x10A0F, 0x10A38, 0x1D185, 0x1D186, 0x1D187,
    0x1D188, 0x1D189, 0x1D1AA, 0x1D1AB, 0x1D1AC, 0x1D1AD, 0x1D242, 0x1D243, 0x1D244,
]

_MAX_CELLS = 40
_MAX_ROWS = 60
_MAX_PIXELS = 20_000_000
_CHUNK = 4096

# IDs stay below 2**24 so the high-byte diacritic is always index 0.
_image_ids = count(randint(1, 0xFFFFFF))


def supported() -> bool:
    """Whether the current terminal can display Kitty placeholder images."""
    override = os.environ.get("S1TUI_KITTY", "").strip().casefold()
    if override in {"1", "true", "yes", "on"}:
        return True
    if override in {"0", "false", "no", "off"}:
        return False

    out = sys.__stdout__
    if out is None or not out.isatty():
        return False
    # tmux strips unknown escape sequences unless allow-passthrough is enabled;
    # require an explicit opt-in there rather than silently showing nothing.
    if os.environ.get("TMUX"):
        return False

    term = os.environ.get("TERM", "").casefold()
    program = os.environ.get("TERM_PROGRAM", "").casefold()
    if term == "xterm-kitty" or os.environ.get("KITTY_WINDOW_ID"):
        return True
    if program in {"ghostty", "wezterm", "kitty"}:
        return True
    if os.environ.get("GHOSTTY_RESOURCES_DIR") or os.environ.get("WEZTERM_PANE"):
        return True
    return False


def unsupported_hint() -> str:
    return ("当前终端不支持 Kitty graphics protocol，无法显示图片；"
            "请改用 Ghostty / Kitty / WezTerm，或按 o 在浏览器打开")


def _write(sequence: str) -> None:
    out = sys.__stdout__
    if out is not None:
        out.write(sequence)
        out.flush()


def _message(payload: str | None = None, **kwargs: int | str | None) -> str:
    params = ",".join(f"{key}={value}" for key, value in kwargs.items() if value is not None)
    return f"{_START}{params}{';' + payload if payload else ''}{_END}"


def _cell_size() -> tuple[int, int]:
    """Return the pixel size of one terminal cell."""
    out = sys.__stdout__
    if fcntl is not None and termios is not None and out is not None:
        try:
            packed = fcntl.ioctl(out.fileno(), termios.TIOCGWINSZ,
                                 struct.pack("HHHH", 0, 0, 0, 0))
            rows, cols, width_px, height_px = struct.unpack("HHHH", packed)
            if rows and cols and width_px and height_px:
                return max(1, width_px // cols), max(1, height_px // rows)
        except (OSError, ValueError, AttributeError):
            pass
    return 10, 20


class KittyImage:
    """A Rich renderable showing a real bitmap via Kitty Unicode placeholders."""

    def __init__(self, data: bytes) -> None:
        with Image.open(BytesIO(data)) as source:
            if source.width * source.height > _MAX_PIXELS:
                raise ValueError("图片分辨率过大")
            source.seek(0)
            image = source.convert("RGB")

        cell_width, cell_height = _cell_size()
        self._cols = _MAX_CELLS
        self._rows = max(1, min(
            _MAX_ROWS,
            round(self._cols * cell_width * image.height / (image.width * cell_height)),
        ))
        scaled = ImageOps.contain(image, (self._cols * cell_width, self._rows * cell_height))
        buffer = BytesIO()
        scaled.save(buffer, format="PNG")
        self._payload = base64.b64encode(buffer.getvalue()).decode("ascii")

        self._image_id = next(_image_ids)
        self._sent = False
        self._closed = False

    def __rich_measure__(self, console: Console, options: ConsoleOptions) -> Measurement:
        return Measurement(1, self._cols)

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        if self._closed:
            return
        if not self._sent:
            self._transmit()
            self._sent = True

        # Narrow terminals simply show fewer placeholder columns; the virtual
        # placement keeps its original size so the remaining cells still line up.
        cols = max(1, min(self._cols, options.max_width or self._cols))
        style = Style(color=(
            f"rgb({(self._image_id >> 16) & 255},"
            f"{(self._image_id >> 8) & 255},"
            f"{self._image_id & 255})"
        ))
        id_char = chr(_NUMBER_TO_DIACRITIC[self._image_id >> 24])
        for row in range(self._rows):
            line = "".join(
                f"{chr(_PLACEHOLDER)}{chr(_NUMBER_TO_DIACRITIC[row])}"
                f"{chr(_NUMBER_TO_DIACRITIC[col])}{id_char}"
                for col in range(cols)
            )
            yield Segment(line + "\n", style=style)

    def _transmit(self) -> None:
        # `a=t` transmits data only. `a=T` would also create a real placement
        # and display the full-size image at the cursor, covering unrelated
        # widgets. The virtual placement below is the only visible one.
        payload = self._payload
        first = True
        while payload:
            chunk, payload = payload[:_CHUNK], payload[_CHUNK:]
            params = ({"a": "t", "i": self._image_id, "f": 100, "q": 2}
                      if first else {"q": 2})
            params["m"] = 1 if payload else 0
            _write(_message(payload=chunk, **params))
            first = False
        _write(_message(a="p", i=self._image_id, c=self._cols, r=self._rows, U=1, q=2))

    def cleanup(self) -> None:
        """Free the image data held by the terminal."""
        if not self._closed:
            _write(_message(a="d", d="I", i=self._image_id, q=2))
            self._closed = True
