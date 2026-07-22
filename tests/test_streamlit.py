"""Headless Streamlit rendering smoke test."""

from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_streamlit_renders_when_backend_is_unavailable(monkeypatch) -> None:
    monkeypatch.setenv("API_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("API_TIMEOUT_SECONDS", "0.1")
    app_path = Path(__file__).resolve().parents[1] / "ui" / "streamlit_app.py"

    rendered = AppTest.from_file(str(app_path), default_timeout=10).run()

    assert not rendered.exception
    assert any("Local RAG Chat" in title.value for title in rendered.title)
