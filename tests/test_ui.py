"""Web UI serving + capability discovery (no LLM/DB needed)."""

from __future__ import annotations

from tests.conftest import make_fake


def test_ui_index_is_served(client_factory):
    client = client_factory(make_fake())
    resp = client.get("/ui/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    body = resp.text
    assert "Support" in body
    assert 'id="app"' in body  # the shell the frontend renders into


def test_root_redirects_to_ui(client_factory):
    client = client_factory(make_fake())
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == "/ui/"


def test_capabilities_reports_core_runtime(client_factory):
    client = client_factory(make_fake())
    resp = client.get("/capabilities")
    assert resp.status_code == 200
    body = resp.json()
    assert "core" in body["runtimes"]
    assert "confidence_threshold" in body
    # active_model may be None when no key is configured, but the key must be present.
    assert "active_model" in body


def test_js_modules_have_javascript_mime(client_factory):
    """Guards the Windows regression where `.js` is served as text/plain, which
    breaks native ES module loading (`<script type="module">`)."""
    client = client_factory(make_fake())
    resp = client.get("/ui/js/app.js")
    assert resp.status_code == 200
    assert "javascript" in resp.headers["content-type"]
