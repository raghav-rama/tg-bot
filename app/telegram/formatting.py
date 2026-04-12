from __future__ import annotations

import html
import re

_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(?P<content>.+?)\s*$")
_ORDERED_LIST_RE = re.compile(r"^(?P<prefix>\s*\d+\.\s+)(?P<content>.*)$")
_UNORDERED_LIST_RE = re.compile(r"^(?P<prefix>\s*[-*]\s+)(?P<content>.*)$")
_BLOCKQUOTE_RE = re.compile(r"^(?P<prefix>\s*>\s?)(?P<content>.*)$")
_FENCE_RE = re.compile(r"^```(?:[\w#+.-]+)?\s*$")


def render_telegram_html(text: str) -> str:
    """Convert a safe subset of model markdown into Telegram HTML."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    rendered_lines: list[str] = []
    code_lines: list[str] = []
    in_code_block = False

    for line in normalized.split("\n"):
        stripped = line.strip()
        if in_code_block:
            if _FENCE_RE.match(stripped):
                rendered_lines.append(_render_code_block(code_lines))
                code_lines = []
                in_code_block = False
                continue
            code_lines.append(line)
            continue

        if _FENCE_RE.match(stripped):
            in_code_block = True
            code_lines = []
            continue

        rendered_lines.append(_render_text_line(line))

    if in_code_block:
        rendered_lines.append(_render_code_block(code_lines))

    return "\n".join(rendered_lines)


def _render_code_block(lines: list[str]) -> str:
    code = "\n".join(lines)
    return f"<pre>{html.escape(code, quote=False)}</pre>"


def _render_text_line(line: str) -> str:
    if line == "":
        return ""

    heading_match = _HEADING_RE.match(line)
    if heading_match:
        return f"<b>{_render_inline(heading_match.group('content'))}</b>"

    for pattern in (_ORDERED_LIST_RE, _UNORDERED_LIST_RE, _BLOCKQUOTE_RE):
        match = pattern.match(line)
        if match:
            prefix = html.escape(match.group("prefix"), quote=False)
            content = _render_inline(match.group("content"))
            return f"{prefix}{content}"

    return _render_inline(line)


def _render_inline(text: str) -> str:
    parts: list[str] = []
    index = 0

    while index < len(text):
        link = _parse_link(text, index)
        if link is not None:
            label, url, end_index = link
            parts.append(
                f'<a href="{html.escape(url, quote=True)}">'
                f"{html.escape(label, quote=False)}</a>"
            )
            index = end_index
            continue

        if text[index] == "`":
            closing = text.find("`", index + 1)
            if closing > index + 1:
                code = text[index + 1 : closing]
                parts.append(f"<code>{html.escape(code, quote=False)}</code>")
                index = closing + 1
                continue

        for delimiter, tag in (("**", "b"), ("__", "b"), ("~~", "s")):
            if text.startswith(delimiter, index):
                closing = _find_wrapped_segment(text, delimiter, index + len(delimiter))
                if closing != -1:
                    inner = text[index + len(delimiter) : closing]
                    parts.append(f"<{tag}>{_render_inline(inner)}</{tag}>")
                    index = closing + len(delimiter)
                    break
        else:
            if text[index] in {"*", "_"} and _can_open_italic(text, index):
                delimiter = text[index]
                closing = _find_wrapped_segment(text, delimiter, index + 1)
                if closing != -1 and _can_close_italic(text, closing):
                    inner = text[index + 1 : closing]
                    parts.append(f"<i>{_render_inline(inner)}</i>")
                    index = closing + 1
                    continue

            parts.append(html.escape(text[index], quote=False))
            index += 1
            continue

        continue

    return "".join(parts)


def _find_wrapped_segment(text: str, delimiter: str, start: int) -> int:
    search_from = start
    while True:
        closing = text.find(delimiter, search_from)
        if closing == -1:
            return -1
        inner = text[start:closing]
        if inner and not inner[0].isspace() and not inner[-1].isspace():
            return closing
        search_from = closing + len(delimiter)


def _can_open_italic(text: str, index: int) -> bool:
    if index + 1 >= len(text) or text[index + 1].isspace():
        return False
    if text[index] == "_" and index > 0 and text[index - 1].isalnum():
        return False
    return True


def _can_close_italic(text: str, index: int) -> bool:
    if index == 0 or text[index - 1].isspace():
        return False
    if text[index] == "_" and index + 1 < len(text) and text[index + 1].isalnum():
        return False
    return True


def _parse_link(text: str, start: int) -> tuple[str, str, int] | None:
    if text[start] != "[":
        return None
    label_end = text.find("](", start + 1)
    if label_end == -1:
        return None
    url_end = text.find(")", label_end + 2)
    if url_end == -1:
        return None

    label = text[start + 1 : label_end]
    url = text[label_end + 2 : url_end].strip()
    if not label or not url or any(char.isspace() for char in url):
        return None
    if not (
        url.startswith("http://")
        or url.startswith("https://")
        or url.startswith("tg://")
    ):
        return None

    return label, url, url_end + 1
