"""The tag language used in report templates.

Staff write section text that mixes fixed wording with tags, and the
report generator fills the tags from a context dictionary::

    This report was generated for {customerName} on {dateTime}.

Syntax
  {path}                  value at a dotted path, e.g. {metrics.alerts.total}
  {path|filter|filter}    filters: round:N  default:text  date  upper  lower
  {#each path} … {/each}  repeat for every item of a list; inside, an
                          item's own keys come first ({name}), then the
                          outer context; {this} is the item, {index} is
                          its 1-based position
  {#if path} … {/if}      include only when the value is present / truthy
  {#else}                 inside either block: the "empty list" or
                          "otherwise" branch

Anything in braces that is not one of these is left exactly as written.
A tag whose path does not exist is also left as written and reported, so
a typo is visible in the draft instead of silently vanishing.

This is deliberately not Django's template language: templates are edited
by staff in the browser, so the language can only read values — it has no
attribute access, calls, includes or filters with side effects.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

PATH = r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*"
_TOKEN = re.compile(
    r"\{#(?P<open>each|if)\s+(?P<open_path>" + PATH + r")\s*\}"
    r"|\{(?P<else>#else)\}"
    r"|\{/(?P<close>each|if)\}"
    r"|\{(?P<path>" + PATH + r")(?P<filters>(?:\|[^{}|\n]+)*)\}"
)
# A block tag alone on its line should not leave a blank line behind.
_STANDALONE = re.compile(
    r"(?m)^[ \t]*(\{#(?:each|if)\s+" + PATH + r"\s*\}|\{#else\}|\{/(?:each|if)\})[ \t]*\n"
)
FILTERS = ("round", "default", "date", "upper", "lower")
_MISSING = object()


class TemplateError(ValueError):
    """The template text is malformed (e.g. an unclosed {#each})."""


@dataclass
class _Text:
    text: str


@dataclass
class _Tag:
    path: str
    filters: list[tuple[str, str | None]]
    raw: str


@dataclass
class _Block:
    kind: str  # "each" | "if"
    path: str
    body: list = field(default_factory=list)
    otherwise: list = field(default_factory=list)
    in_else: bool = False

    def add(self, node) -> None:
        (self.otherwise if self.in_else else self.body).append(node)


def _parse_filters(spec: str, raw: str) -> list[tuple[str, str | None]]:
    out = []
    for part in spec.split("|")[1:]:
        name, _, arg = part.partition(":")
        name = name.strip()
        if name not in FILTERS:
            raise TemplateError(f"Unknown filter '{name}' in {raw}")
        if name == "round" and not arg.strip().isdigit():
            raise TemplateError(f"round needs a number of decimals, e.g. round:2, in {raw}")
        out.append((name, arg.strip() if arg else None))
    return out


def parse(source: str) -> list:
    source = _STANDALONE.sub(r"\1", source.replace("\r\n", "\n"))
    root: list = []
    stack: list[_Block] = []

    def emit(node) -> None:
        if stack:
            stack[-1].add(node)
        else:
            root.append(node)

    pos = 0
    for m in _TOKEN.finditer(source):
        if m.start() > pos:
            emit(_Text(source[pos : m.start()]))
        pos = m.end()
        if m.group("open"):
            block = _Block(m.group("open"), m.group("open_path"))
            emit(block)
            stack.append(block)
        elif m.group("else"):
            if not stack or stack[-1].in_else:
                raise TemplateError("{#else} must sit inside one {#each} or {#if} block")
            stack[-1].in_else = True
        elif m.group("close"):
            if not stack or stack[-1].kind != m.group("close"):
                expected = f"{{/{stack[-1].kind}}}" if stack else "nothing open"
                raise TemplateError(
                    f"Unexpected {{/{m.group('close')}}} (expected {expected})"
                )
            stack.pop()
        else:
            raw = m.group(0)
            emit(_Tag(m.group("path"), _parse_filters(m.group("filters"), raw), raw))
    if pos < len(source):
        emit(_Text(source[pos:]))
    if stack:
        raise TemplateError(
            f"{{#{stack[-1].kind} {stack[-1].path}}} is never closed with "
            f"{{/{stack[-1].kind}}}"
        )
    return root


def validate(source: str) -> str | None:
    """Return a human-readable problem, or None if the template parses."""
    try:
        parse(source)
    except TemplateError as e:
        return str(e)
    return None


def _lookup(scopes: list[Any], path: str) -> Any:
    """Resolve a dotted path against the innermost scope that has its
    first segment. Only dict keys and list indexes are followed."""
    head, *rest = path.split(".")
    for scope in reversed(scopes):
        if isinstance(scope, dict) and head in scope:
            value: Any = scope[head]
            break
    else:
        return _MISSING
    for part in rest:
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return _MISSING
    return value


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None


def format_value(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    if isinstance(value, (list, tuple)):
        return ", ".join(format_value(v) for v in value)
    if isinstance(value, dict):
        return ", ".join(f"{k}: {format_value(v)}" for k, v in value.items())
    return str(value)


def _apply_filters(value: Any, filters: list[tuple[str, str | None]]) -> Any:
    for name, arg in filters:
        absent = value is _MISSING or value is None or value == ""
        if name == "default":
            if absent:
                value = arg or ""
        elif absent:
            continue
        elif name == "round":
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                value = f"{value:.{int(arg or 0)}f}"
        elif name == "date":
            d = _parse_date(value)
            value = f"{d.day} {d:%b %Y}" if d else value
        elif name == "upper":
            value = format_value(value).upper()
        elif name == "lower":
            value = format_value(value).lower()
    return value


@dataclass
class Rendered:
    text: str
    #: tags that could not be filled, in order of first appearance
    missing: list[str]


class _Writer:
    def __init__(self) -> None:
        self.parts: list[str] = []
        self.line = ""  # text of the output line currently being written

    def write(self, text: str) -> None:
        self.parts.append(text)
        self.line = text.rsplit("\n", 1)[1] if "\n" in text else self.line + text

    def write_value(self, text: str) -> None:
        # A value must not be able to break the table row it lands in.
        text = text.replace("|", "\\|")
        if self.line.lstrip().startswith("|"):
            text = " ".join(text.split())
        self.write(text)


def _render(nodes: list, scopes: list[Any], out: _Writer, missing: list[str]) -> None:
    for node in nodes:
        if isinstance(node, _Text):
            out.write(node.text)
        elif isinstance(node, _Tag):
            value = _apply_filters(_lookup(scopes, node.path), node.filters)
            if value is _MISSING:
                if node.path not in missing:
                    missing.append(node.path)
                out.write(node.raw)
            else:
                out.write_value(format_value(value))
        elif node.kind == "each":
            items = _lookup(scopes, node.path)
            if isinstance(items, list) and items:
                for i, item in enumerate(items, start=1):
                    scope = dict(item) if isinstance(item, dict) else {}
                    scope.setdefault("this", item)
                    scope.setdefault("index", i)
                    _render(node.body, [*scopes, scope], out, missing)
            else:
                if items is _MISSING and node.path not in missing:
                    missing.append(node.path)
                _render(node.otherwise, scopes, out, missing)
        else:  # if
            value = _lookup(scopes, node.path)
            truthy = value is not _MISSING and bool(value)
            _render(node.body if truthy else node.otherwise, scopes, out, missing)


def render(source: str, context: dict) -> Rendered:
    out = _Writer()
    missing: list[str] = []
    _render(parse(source), [context], out, missing)
    return Rendered("".join(out.parts), missing)


def leftover_tags(text: str) -> list[str]:
    """Tags still present in already-rendered text (staff may have typed
    or left one in a draft)."""
    seen: list[str] = []
    for m in _TOKEN.finditer(text):
        if m.group(0) not in seen:
            seen.append(m.group(0))
    return seen
