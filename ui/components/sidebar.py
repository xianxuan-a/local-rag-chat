"""知识库与持久化会话的侧栏管理。"""

from __future__ import annotations

from typing import Any

import streamlit as st

from ui.api_client import ApiClient, ApiClientError


def _knowledge_base_label(item: dict[str, Any]) -> str:
    return str(item.get("name") or item.get("id") or "未命名知识库")


def _session_label(item: dict[str, Any]) -> str:
    title = str(item.get("title") or "未命名会话")
    updated_at = str(item.get("updated_at") or "")
    if updated_at:
        return f"{title} · {updated_at[:16].replace('T', ' ')}"
    return title


def _clear_knowledge_base_state() -> None:
    for key in (
        "session_selector",
        "selected_session_id",
        "loaded_chat_session_id",
        "loaded_chat_knowledge_base_id",
        "chat_messages",
        "sessions",
        "files",
        "processing_file_ids",
        "last_uploaded_file",
        "chat_session_load_failed",
    ):
        st.session_state.pop(key, None)


def render_sidebar(
    client: ApiClient, backend_available: bool
) -> tuple[str | None, str | None, list[dict[str, Any]]]:
    """返回当前知识库、当前会话以及知识库列表。"""

    with st.sidebar:
        status_columns = st.columns([3, 1])
        with status_columns[0]:
            st.header("知识库")
            if backend_available:
                st.caption("后端连接正常")
            else:
                st.caption("后端连接不可用")
        with status_columns[1]:
            if st.button(
                "刷新",
                key="refresh_backend_and_kb",
                use_container_width=True,
            ):
                st.rerun()

        knowledge_bases: list[dict[str, Any]] = []
        knowledge_base_load_failed = False
        if backend_available:
            try:
                knowledge_bases = client.list_knowledge_bases()
            except ApiClientError as exc:
                knowledge_base_load_failed = True
                st.error(str(exc))
        else:
            st.info("后端不可用，知识库操作暂时停用。")
        st.session_state["knowledge_bases"] = knowledge_bases

        pending_id = st.session_state.pop("pending_knowledge_base_id", None)
        options = [str(item["id"]) for item in knowledge_bases if item.get("id")]
        labels = {
            str(item["id"]): _knowledge_base_label(item)
            for item in knowledge_bases
            if item.get("id")
        }
        if pending_id in options:
            st.session_state["knowledge_base_selector"] = pending_id
        elif options and st.session_state.get(
            "knowledge_base_selector"
        ) not in options:
            st.session_state["knowledge_base_selector"] = options[0]

        selected_id: str | None = None
        if options:
            selected_id = st.selectbox(
                "选择知识库",
                options=options,
                format_func=lambda item_id: labels.get(item_id, item_id),
                key="knowledge_base_selector",
            )
        elif backend_available and not knowledge_base_load_failed:
            st.caption("尚无知识库，请先创建一个。")

        previous_selected_id = st.session_state.get("selected_kb_id")
        if previous_selected_id != selected_id:
            _clear_knowledge_base_state()
        st.session_state["selected_kb_id"] = selected_id

        with st.expander("新建知识库", expanded=not options):
            with st.form("create_knowledge_base_form", clear_on_submit=True):
                name = st.text_input(
                    "名称",
                    max_chars=100,
                    placeholder="例如：产品文档",
                )
                description = st.text_area(
                    "描述（可选）",
                    max_chars=1000,
                    placeholder="简要说明知识库用途",
                )
                create_submitted = st.form_submit_button(
                    "创建知识库",
                    disabled=not backend_available,
                    use_container_width=True,
                )

            if create_submitted:
                normalized_name = name.strip()
                if not normalized_name:
                    st.warning("知识库名称不能为空。")
                else:
                    try:
                        created = client.create_knowledge_base(
                            normalized_name,
                            description.strip() or None,
                        )
                    except ApiClientError as exc:
                        st.error(str(exc))
                    else:
                        created_id = created.get("id")
                        if created_id:
                            st.session_state["pending_knowledge_base_id"] = str(
                                created_id
                            )
                        st.success("知识库创建成功。")
                        st.rerun()

        if selected_id:
            selected_name = labels.get(selected_id, selected_id)
            with st.expander("删除当前知识库"):
                st.warning(
                    "只能删除不含文件和会话的知识库；删除操作无法由前端撤销。"
                )
                confirm_kb_delete = st.checkbox(
                    f"确认删除“{selected_name}”",
                    key=f"confirm_delete_kb_{selected_id}",
                )
                if st.button(
                    "确认删除知识库",
                    disabled=not confirm_kb_delete,
                    key=f"delete_kb_{selected_id}",
                    use_container_width=True,
                ):
                    try:
                        client.delete_knowledge_base(selected_id)
                    except ApiClientError as exc:
                        st.error(str(exc))
                    else:
                        _clear_knowledge_base_state()
                        st.session_state.pop("knowledge_base_selector", None)
                        st.session_state.pop("selected_kb_id", None)
                        st.rerun()

            st.caption("文件上传、处理和删除位于主内容区“知识库文件”。")

        st.divider()
        st.subheader("会话列表")
        selected_session_id: str | None = None
        sessions: list[dict[str, Any]] = []

        if backend_available and selected_id:
            try:
                sessions = client.list_sessions(selected_id)
            except ApiClientError as exc:
                st.error(str(exc))
            st.session_state["sessions"] = sessions

            if st.button(
                "新建会话",
                use_container_width=True,
                key="create_chat_session",
            ):
                try:
                    created_session = client.create_session(selected_id)
                except ApiClientError as exc:
                    st.error(str(exc))
                else:
                    created_session_id = created_session.get("id")
                    if created_session_id:
                        st.session_state["pending_session_id"] = str(
                            created_session_id
                        )
                    st.rerun()

            session_options = [
                str(item["id"]) for item in sessions if item.get("id")
            ]
            session_labels = {
                str(item["id"]): _session_label(item)
                for item in sessions
                if item.get("id")
            }
            pending_session_id = st.session_state.pop(
                "pending_session_id",
                None,
            )
            current_session_id = st.session_state.get("session_selector")
            if pending_session_id in session_options:
                st.session_state["session_selector"] = pending_session_id
            elif (
                session_options
                and current_session_id not in session_options
            ):
                st.session_state["session_selector"] = session_options[0]

            if session_options:
                selected_session_id = st.selectbox(
                    "选择会话",
                    options=session_options,
                    format_func=lambda session_id: session_labels.get(
                        session_id,
                        session_id,
                    ),
                    key="session_selector",
                )
                st.session_state["selected_session_id"] = selected_session_id
                with st.expander("删除当前会话"):
                    selected_session_label = session_labels.get(
                        selected_session_id,
                        selected_session_id,
                    )
                    st.warning("会话及其全部历史消息将被删除，且无法由前端撤销。")
                    confirm_session_delete = st.checkbox(
                        f"确认删除“{selected_session_label}”",
                        key=f"confirm_delete_session_{selected_session_id}",
                    )
                    if st.button(
                        "确认删除会话",
                        use_container_width=True,
                        disabled=not confirm_session_delete,
                        key=f"delete_chat_session_{selected_session_id}",
                    ):
                        try:
                            client.delete_session(
                                selected_id,
                                selected_session_id,
                            )
                        except ApiClientError as exc:
                            st.error(str(exc))
                        else:
                            st.session_state.pop("session_selector", None)
                            st.session_state.pop(
                                "selected_session_id",
                                None,
                            )
                            st.session_state.pop(
                                "loaded_chat_session_id",
                                None,
                            )
                            st.session_state["chat_messages"] = []
                            st.rerun()
            else:
                st.session_state.pop("selected_session_id", None)
                st.caption("当前知识库尚无会话。")
        elif backend_available:
            st.session_state["sessions"] = []
            st.caption("选择知识库后可创建会话。")
        else:
            st.info("后端不可用，会话操作暂时停用。")

    return selected_id, selected_session_id, knowledge_bases
