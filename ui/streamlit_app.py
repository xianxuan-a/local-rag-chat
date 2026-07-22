"""Local RAG Chat 的 Streamlit 入口。"""

from __future__ import annotations

import streamlit as st

from ui.api_client import ApiClient, ApiClientError, api_client_from_env
from ui.components.chat_panel import render_chat_panel
from ui.components.file_uploader import render_file_uploader
from ui.components.sidebar import render_sidebar


def main() -> None:
    st.set_page_config(
        page_title="Local RAG Chat",
        page_icon="📚",
        layout="wide",
    )
    st.title("📚 Local RAG Chat")
    st.caption("本地知识库问答系统 · 工程初始化版本")

    backend_available = False
    configuration_error: str | None = None
    try:
        client = api_client_from_env()
    except ApiClientError as exc:
        configuration_error = str(exc)
        client = ApiClient("http://localhost:8000", 3.0)

    if configuration_error:
        st.error(f"系统状态：{configuration_error}")
    else:
        try:
            health = client.health()
        except ApiClientError as exc:
            st.error(f"系统状态：后端不可用。{exc}")
        else:
            backend_available = health.get("status") == "ok"
            if backend_available:
                st.success(f"系统状态：后端运行正常（{client.base_url}）")
            else:
                st.warning("系统状态：后端健康检查未返回 ok。")

    selected_knowledge_base_id, _ = render_sidebar(
        client=client,
        backend_available=backend_available,
    )

    chat_tab, files_tab = st.tabs(["问答", "知识库文件"])
    with chat_tab:
        render_chat_panel(
            client=client,
            knowledge_base_id=selected_knowledge_base_id,
            backend_available=backend_available,
        )
    with files_tab:
        render_file_uploader(
            client=client,
            knowledge_base_id=selected_knowledge_base_id,
            backend_available=backend_available,
        )

    st.divider()
    st.caption("完整文档解析、向量检索、会话持久化和模型问答尚未实现。")


if __name__ == "__main__":
    main()
