from __future__ import annotations

import ipaddress
import socket
from html.parser import HTMLParser
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlsplit

import httpx
from langchain_core.tools import tool

if TYPE_CHECKING:
    from agent.config import Settings


_MAX_RESPONSE_BYTES = 2_000_000
_MAX_REDIRECTS = 3
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_TEXT_CONTENT_TYPES = {
    "application/json",
    "application/ld+json",
    "application/xhtml+xml",
    "application/xml",
}


class WebFetchError(RuntimeError):
    pass


class _ReadableHTMLParser(HTMLParser):
    _SKIP_TAGS = {"script", "style", "noscript", "svg"}
    _BLOCK_TAGS = {
        "article",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "figcaption",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "li",
        "main",
        "nav",
        "p",
        "pre",
        "section",
        "table",
        "td",
        "th",
        "tr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        del attrs
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        elif not self._skip_depth and tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif not self._skip_depth and tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._parts.append(data)

    def text(self) -> str:
        lines = (" ".join(line.split()) for line in "".join(self._parts).splitlines())
        return "\n".join(line for line in lines if line)


def _allowed_host(host: str, allowed_hosts: tuple[str, ...]) -> bool:
    if not allowed_hosts:
        return True
    for rule in allowed_hosts:
        if rule.startswith("*."):
            suffix = rule[1:]
            if host.endswith(suffix) and host != suffix[1:]:
                return True
        elif host == rule:
            return True
    return False


def _parse_allowed_hosts(value: str) -> tuple[str, ...]:
    return tuple(part.strip().lower().rstrip(".") for part in value.split(",") if part.strip())


def _validate_public_url(url: str, allowed_hosts: tuple[str, ...]) -> str:
    parsed = urlsplit(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise WebFetchError("only http:// and https:// URLs are allowed")
    if parsed.username or parsed.password:
        raise WebFetchError("URLs containing credentials are not allowed")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise WebFetchError("URL has no hostname")
    if not _allowed_host(host, allowed_hosts):
        raise WebFetchError(f"host is not allowlisted: {host}")

    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (OSError, ValueError) as exc:
        raise WebFetchError(f"cannot resolve host {host}: {exc}") from exc
    if not addresses:
        raise WebFetchError(f"cannot resolve host {host}")
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise WebFetchError(f"host resolves to a non-public address: {host}")
    return parsed.geturl()


def _decode_content(content: bytes, encoding: str | None) -> str:
    try:
        return content.decode(encoding or "utf-8", errors="replace")
    except LookupError:
        return content.decode("utf-8", errors="replace")


def _read_response(response: httpx.Response) -> tuple[bytes, bool]:
    body = bytearray()
    truncated = False
    for chunk in response.iter_bytes():
        remaining = _MAX_RESPONSE_BYTES - len(body)
        if remaining <= 0:
            truncated = True
            break
        body.extend(chunk[:remaining])
        if len(chunk) > remaining:
            truncated = True
            break
    return bytes(body), truncated


def fetch_web_page(
    url: str,
    *,
    timeout_sec: int = 20,
    max_chars: int = 30_000,
    allowed_hosts: tuple[str, ...] = (),
) -> str:
    """Fetch one known public URL and return bounded plain text.

    This is retrieval, not web search. Every redirect is revalidated to prevent a
    public URL from redirecting the agent into a private network.
    """
    try:
        current_url = _validate_public_url(url, allowed_hosts)
        with httpx.Client(timeout=timeout_sec, follow_redirects=False, trust_env=False) as client:
            for redirect_no in range(_MAX_REDIRECTS + 1):
                with client.stream(
                    "GET",
                    current_url,
                    headers={"User-Agent": "jetson-bsp-agent-web-fetch/1.0"},
                ) as response:
                    if response.status_code in _REDIRECT_STATUSES:
                        location = response.headers.get("location")
                        if not location:
                            raise WebFetchError("redirect response has no Location header")
                        if redirect_no == _MAX_REDIRECTS:
                            raise WebFetchError("too many redirects")
                        current_url = _validate_public_url(
                            urljoin(current_url, location), allowed_hosts
                        )
                        continue

                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").split(";", 1)[0]
                    content_type = content_type.strip().lower()
                    if not (
                        content_type.startswith("text/")
                        or content_type in _TEXT_CONTENT_TYPES
                    ):
                        raise WebFetchError(
                            f"unsupported content type: {content_type or 'unknown'}"
                        )
                    raw, byte_truncated = _read_response(response)
                    text = _decode_content(raw, response.encoding)
                    if content_type in {"text/html", "application/xhtml+xml"}:
                        parser = _ReadableHTMLParser()
                        parser.feed(text)
                        text = parser.text()
                    else:
                        text = text.strip()

                    char_truncated = len(text) > max_chars
                    text = text[:max_chars]
                    suffix = "\n\n... (content truncated)" if byte_truncated or char_truncated else ""
                    return f"Source: {current_url}\n\n{text}{suffix}"
    except (WebFetchError, httpx.HTTPError) as exc:
        return f"(error: {exc})"

    return "(error: fetch ended without a response)"


def build_web_fetch_tool(settings: "Settings"):
    allowed_hosts = _parse_allowed_hosts(settings.web_fetch_allowed_hosts)

    @tool("fetch_web_page")
    def fetch_web_page_tool(url: str) -> str:
        """Fetch and read one known public HTTP(S) URL.

        This does not search the web. Use only URLs supplied by the issue, repository,
        loaded skills, or an already fetched official documentation page.
        """
        return fetch_web_page(
            url,
            timeout_sec=settings.web_fetch_timeout_sec,
            max_chars=settings.web_fetch_max_chars,
            allowed_hosts=allowed_hosts,
        )

    return fetch_web_page_tool
