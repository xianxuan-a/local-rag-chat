"""聊天消息与初始化占位问答组件。"""

from __future__ import annotations

from typing import Any

import streamlit as st

from ui.api_client import ApiClient, ApiClientError


def _render_sources(sources: Any) -> None:
    if not isinstance(sources, list) or not sources:
        return
    with st.expander("来源"):
        for index, source in enumerate(sources, start=1):
            if not isinstance(source, dict):
                continue
            name = source.get("file_name") or source.get("file_id") or f"来源 {index}"
            summary = source.get("content_preview") or source.get("content") or ""
            score = source.get("score")
            score_text = (
                f" · 分数 {score:.3f}"
                if isinstance(score, (int, float)) and not isinstance(score, bool)
                else ""
            )
            st.markdown(f"**{name}**{score_text}")
            if summary:
                st.caption(str(summary))


def render_chat_panel(
    client: ApiClient,
    knowledge_base_id: str | None,
    backend_available: bool,
) -> None:
    """调用当前阶段的聊天占位接口，并在页面内保存临时显示消息。"""

    st.subheader("知识库问答")
    st.caption("当前接口仅返回初始化占位答案，不会调用 Embedding 或大语言模型。")

    previous_kb_id = st.session_state.get("chat_knowledge_base_id")
    if previous_kb_id != knowledge_base_id:
        st.session_state["chat_knowledge_base_id"] = knowledge_base_id
        st.session_state["chat_messages"] = []

    messages = st.session_state.setdefault("chat_messages", [])
    for message in messages:
        role = message.get("role", "assistant")
        with st.chat_message(role):
            st.markdown(str(message.get("content", "")))
            _render_sources(message.get("sources"))

    if not messages:
        st.info("还没有消息。选择知识库后可发送一个问题体验占位接口。")

    with st.form("chat_form", clear_on_submit=True):
        question = st.text_area(
            "问题",
            max_chars=4000,
            placeholder="请输入你想询问的问题",
            disabled=not backend_available or knowledge_base_id is None,
        )
        send_submitted = st.form_submit_button(
            "发送",
            type="primary",
            disabled=not backend_available or knowledge_base_id is None,
        )

    if send_submitted and knowledge_base_id:
        normalized_question = question.strip()
        if not normalized_question:
            st.warning("问题不能为空。")
            return

        messages.append({"role": "user", "content": normalized_question})
        try:
            response = client.chat(
                knowledge_base_id=knowledge_base_id,
                question=normalized_question,
                session_id=None,
                top_k=4,
            )
        except ApiClientError as exc:
            messages.append(
                {
                    "role": "assistant",
                    "content": f"请求失败：{exc}",
                    "sources": [],
                }
            )
        else:
            messages.append(
                {
                    "role": "assistant",
                    "content": str(
                        response.get("answer")
                        or "RAG 问答服务尚未完成初始化"
                    ),
                    "sources": response.get("sources", []),
                }
            )
        st.rerun()
