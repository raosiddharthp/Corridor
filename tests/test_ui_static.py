import asyncio
import re
from pathlib import Path

import httpx

import app.main as main

STATIC = Path(main.STATIC_DIR)


def _call(path):
    async def go():
        transport = httpx.ASGITransport(app=main.create_app({}))
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            return await client.get(path)

    return asyncio.run(go())


def test_the_page_has_no_inline_scripts():
    html = (STATIC / "index.html").read_text()
    assert not re.search(r"<script(?![^>]*\bsrc=)", html)


def test_the_page_has_no_inline_style_attributes():
    html = (STATIC / "index.html").read_text()
    assert not re.search(r"\sstyle\s*=", html)


def test_the_script_never_writes_markup():
    js = (STATIC / "console.js").read_text()
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert banned not in js


def test_the_console_assets_are_served():
    assert "Corridor" in _call("/").text
    assert "javascript" in _call("/console.js").headers["content-type"]
    assert _call("/console.css").status_code == 200


def test_the_served_page_carries_the_content_security_policy():
    assert "script-src 'self'" in _call("/").headers["content-security-policy"]
