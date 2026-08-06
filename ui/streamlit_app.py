"""Local RAG Chat 的 Streamlit 入口。"""

from __future__ import annotations

import streamlit as st

from ui.api_client import ApiClient, ApiClientError, api_client_from_env
from ui.components.chat_panel import render_chat_panel
from ui.components.file_uploader import render_file_uploader
from ui.components.sidebar import render_sidebar


def _initialize_state() -> None:
    defaults = {
        "selected_kb_id": None,
        "selected_session_id": None,
        "knowledge_bases": [],
        "files": [],
        "sessions": [],
        "chat_messages": [],
        "processing_file_ids": [],
        "streaming": False,
        "last_error": None,
        "access_token": None,
        "current_user": None,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def main() -> None:
    st.set_page_config(
        page_title="Local RAG Chat",
        page_icon="📚",
        layout="wide",
    )
    _initialize_state()
    st.title("📚 Local RAG Chat")
    st.caption("本地知识库文件管理、会话历史与流式 RAG 问答")

    backend_available = False
    configuration_error: str | None = None
    try:
        client = api_client_from_env()
    except ApiClientError as exc:
        configuration_error = str(exc)
        client = ApiClient("http://localhost:8000", 3.0)

    if configuration_error:
        st.session_state["last_error"] = configuration_error
        st.error(f"系统状态：{configuration_error}")
    else:
        try:
            health = client.health()
        except ApiClientError as exc:
            st.session_state["last_error"] = str(exc)
            st.error(f"系统状态：后端不可用。{exc}")
        else:
            backend_available = health.get("status") == "ok"
            if backend_available:
                st.success(f"系统状态：后端运行正常（{client.base_url}）")
            else:
                st.warning("系统状态：后端健康检查未返回 ok。")

    if backend_available:
        def clear_expired_authentication() -> None:
            st.session_state["access_token"] = None
            st.session_state["current_user"] = None

        client.set_auth_failure_handler(clear_expired_authentication)
        token = st.session_state.get("access_token")
        if isinstance(token, str) and token:
            client.set_access_token(token)
            try:
                st.session_state["current_user"] = client.me()
            except ApiClientError:
                client.set_access_token(None)
                st.session_state["access_token"] = None
                st.session_state["current_user"] = None

        if not st.session_state.get("current_user"):
            st.subheader("登录")
            with st.form("login_form"):
                identity = st.text_input("用户名或邮箱")
                password = st.text_input("密码", type="password")
                submitted = st.form_submit_button("登录", type="primary")
            if submitted:
                try:
                    result = client.login(identity, password)
                except ApiClientError as exc:
                    st.error(str(exc))
                else:
                    st.session_state["access_token"] = result["access_token"]
                    st.session_state["current_user"] = result.get("user")
                    st.rerun()
            st.caption(
                "本阶段退出登录只清除浏览器会话中的 Token；"
                "服务端未实现 jti 撤销表。"
            )
            return

        current_user = st.session_state["current_user"]
        user_column, logout_column = st.columns([5, 1])
        user_column.caption(
            f"当前用户：{current_user.get('username')} · "
            f"{current_user.get('role')}"
        )
        if logout_column.button("退出登录", use_container_width=True):
            client.set_access_token(None)
            st.session_state["access_token"] = None
            st.session_state["current_user"] = None
            st.rerun()

    selected_knowledge_base_id, selected_session_id, _ = render_sidebar(
        client=client,
        backend_available=backend_available,
    )

    chat_tab, files_tab = st.tabs(["RAG 问答", "知识库文件"])
    with chat_tab:
        render_chat_panel(
            client=client,
            knowledge_base_id=selected_knowledge_base_id,
            session_id=selected_session_id,
            backend_available=backend_available,
        )
    with files_tab:
        render_file_uploader(
            client=client,
            knowledge_base_id=selected_knowledge_base_id,
            backend_available=backend_available,
        )

    st.divider()
    st.caption("文档索引、RAG 问答与会话历史均保存在本地服务中。")


if __name__ == "__main__":
    main()
