from __future__ import annotations

import socket

import httpx

from agent.config import Settings
from agent.tools.web_tools import build_web_fetch_tool, fetch_web_page


def _public_dns(*args, **kwargs):
    del args, kwargs
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]


def _private_dns(*args, **kwargs):
    del args, kwargs
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))]


def _install_transport(monkeypatch, handler) -> None:
    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def client(**kwargs):
        kwargs["transport"] = transport
        return real_client(**kwargs)

    monkeypatch.setattr("agent.tools.web_tools.httpx.Client", client)


def test_fetch_web_page_extracts_html_and_caps_output(monkeypatch) -> None:
    monkeypatch.setattr("agent.tools.web_tools.socket.getaddrinfo", _public_dns)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text="<html><style>hidden</style><h1>Jetson BSP</h1><p>Camera guide text</p></html>",
            request=request,
        )

    _install_transport(monkeypatch, handler)
    result = fetch_web_page(
        "https://docs.nvidia.com/guide",
        max_chars=18,
        allowed_hosts=("docs.nvidia.com",),
    )

    assert "Jetson BSP" in result
    assert "hidden" not in result
    assert "content truncated" in result


def test_fetch_web_page_rejects_private_and_unapproved_hosts(monkeypatch) -> None:
    monkeypatch.setattr("agent.tools.web_tools.socket.getaddrinfo", _private_dns)

    private = fetch_web_page("http://localhost/admin")
    disallowed = fetch_web_page(
        "https://example.com/docs",
        allowed_hosts=("docs.nvidia.com",),
    )

    assert "error" in private
    assert "non-public address" in private
    assert "error" in disallowed
    assert "not allowlisted" in disallowed


def test_fetch_web_page_revalidates_redirect_target(monkeypatch) -> None:
    def dns(host, *args, **kwargs):
        del args, kwargs
        ip = "127.0.0.1" if host == "internal.example" else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]

    monkeypatch.setattr("agent.tools.web_tools.socket.getaddrinfo", dns)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"location": "http://internal.example/secrets"},
            request=request,
        )

    _install_transport(monkeypatch, handler)
    result = fetch_web_page("https://docs.nvidia.com/redirect")

    assert "error" in result
    assert "non-public address" in result


def test_fetch_web_page_rejects_non_text_content(monkeypatch) -> None:
    monkeypatch.setattr("agent.tools.web_tools.socket.getaddrinfo", _public_dns)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/octet-stream"},
            content=b"binary",
            request=request,
        )

    _install_transport(monkeypatch, handler)
    result = fetch_web_page("https://docs.nvidia.com/archive.bin")

    assert "error" in result
    assert "unsupported content type" in result


def test_build_web_fetch_tool_uses_settings(monkeypatch, tmp_path) -> None:
    settings = Settings(
        WEB_FETCH_ENABLED=True,
        WEB_FETCH_ALLOWED_HOSTS="docs.nvidia.com,*.example.com",
        WEB_FETCH_TIMEOUT_SEC=7,
        WEB_FETCH_MAX_CHARS=123,
        runs_dir=tmp_path / "runs",
    )
    captured = {}

    def fake_fetch(url, **kwargs):
        captured.update(url=url, **kwargs)
        return "page"

    monkeypatch.setattr("agent.tools.web_tools.fetch_web_page", fake_fetch)
    web_tool = build_web_fetch_tool(settings)

    assert web_tool.name == "fetch_web_page"
    assert web_tool.invoke({"url": "https://docs.nvidia.com/guide"}) == "page"
    assert captured == {
        "url": "https://docs.nvidia.com/guide",
        "timeout_sec": 7,
        "max_chars": 123,
        "allowed_hosts": ("docs.nvidia.com", "*.example.com"),
    }
