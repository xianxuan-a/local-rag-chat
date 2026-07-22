"""知识库选择、新建和会话占位区域。"""

from __future__ import annotations

from typing import Any

import streamlit as st

from ui.api_client import ApiClient, ApiClientError


def _knowledge_base_label(item: dict[str, Any]) -> str:
    return str(item.get("name") or item.get("id") or "未命名知识库")


def render_sidebar(
    client: ApiClient, backend_available: bool
) -> tuple[str | None, list[dict[str, Any]]]:
    """渲染侧栏，返回当前知识库 ID 和本次获取到的列表。"""

    with st.sidebar:
        st.header("知识库")
        knowledge_bases: list[dict[str, Any]] = []
        if backend_available:
            try:
                knowledge_bases = client.list_knowledge_bases()
            except ApiClientError as exc:
                st.error(str(exc))
        else:
            st.info("后端不可用，知识库操作暂时停用。")

        pending_id = st.session_state.pop("pending_knowledge_base_id", None)
        options = [str(item["id"]) for item in knowledge_bases if item.get("id")]
        labels = {
            str(item["id"]): _knowledge_base_label(item)
            for item in knowledge_bases
            if item.get("id")
        }
        if pending_id in options:
            st.session_state["knowledge_base_selector"] = pending_id

        selected_id: str | None = None
        if options:
            selected_id = st.selectbox(
                "选择知识库",
                options=options,
                format_func=lambda item_id: labels.get(item_id, item_id),
                key="knowledge_base_selector",
            )
        elif backend_available:
            st.caption("尚无知识库，请先创建一个。")

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

        st.divider()
        st.subheader("会话列表")
        st.info("会话创建、历史记录与删除功能将在后续阶段实现。")

    return selected_id, knowledge_bases
