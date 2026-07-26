"""持久化会话消息与 RAG 问答组件。"""

from __future__ import annotations

from typing import Any

import streamlit as st

from ui.api_client import ApiClient, ApiClientError


def _render_sources(sources: Any) -> None:
    if not isinstance(sources, list) or not sources:
        return
    with st.expander(f"参考来源（{len(sources)}）"):
        for index, source in enumerate(sources, start=1):
            if not isinstance(source, dict):
                continue
            name = source.get("file_name") or source.get("file_id") or f"来源 {index}"
            summary = str(
                source.get("content_preview") or source.get("content") or ""
            )[:1000]
            score = source.get("score")
            score_text = (
                f"{score:.4f}"
                if isinstance(score, (int, float)) and not isinstance(score, bool)
                else "—"
            )
            st.markdown(f"**来源 {index}：{name}**")
            st.caption(
                f"分块：{source.get('chunk_id') or '—'} · "
                f"相关度：{score_text} · "
                f"文件 ID：{source.get('file_id') or '—'}"
            )
            if summary:
                st.text(summary)


def render_chat_panel(
    client: ApiClient,
    knowledge_base_id: str | None,
    session_id: str | None,
    backend_available: bool,
) -> None:
    """加载历史消息并在当前知识库所属会话中继续提问。"""

    st.subheader("知识库问答")
    st.caption("回答来自服务端真实流式生成，完成后会持久化到当前会话。")

    loaded_session_id = st.session_state.get("loaded_chat_session_id")
    loaded_knowledge_base_id = st.session_state.get(
        "loaded_chat_knowledge_base_id"
    )
    if (
        loaded_session_id != session_id
        or loaded_knowledge_base_id != knowledge_base_id
    ):
        st.session_state["loaded_chat_session_id"] = session_id
        st.session_state["loaded_chat_knowledge_base_id"] = knowledge_base_id
        st.session_state["chat_messages"] = []
        st.session_state["chat_session_load_failed"] = False
        if backend_available and knowledge_base_id and session_id:
            try:
                with st.spinner("正在恢复历史消息…"):
                    client.get_session(knowledge_base_id, session_id)
                    st.session_state["chat_messages"] = client.list_messages(
                        knowledge_base_id,
                        session_id,
                    )
            except ApiClientError as exc:
                st.session_state["chat_session_load_failed"] = True
                st.session_state["last_error"] = str(exc)
                st.error(str(exc))

    messages = st.session_state.setdefault("chat_messages", [])
    for message in messages:
        role = str(message.get("role") or "")
        if role == "system":
            st.info(str(message.get("content", "")))
            continue
        if role not in {"user", "assistant"}:
            st.warning("历史消息包含无法识别的角色，已跳过。")
            continue
        with st.chat_message(role):
            st.markdown(str(message.get("content", "")))
            _render_sources(
                message.get("references")
                if "references" in message
                else message.get("sources")
            )

    if not messages:
        if session_id:
            st.info("当前会话还没有消息。")
        else:
            st.info("请先在侧栏创建或选择一个会话。")

    streaming = bool(st.session_state.get("streaming", False))
    load_failed = bool(
        st.session_state.get("chat_session_load_failed", False)
    )
    with st.form("chat_form", clear_on_submit=True):
        question = st.text_area(
            "问题",
            max_chars=4000,
            placeholder="请输入你想询问的问题",
            disabled=(
                not backend_available
                or knowledge_base_id is None
                or session_id is None
                or streaming
                or load_failed
            ),
        )
        send_submitted = st.form_submit_button(
            "发送",
            type="primary",
            disabled=(
                not backend_available
                or knowledge_base_id is None
                or session_id is None
                or streaming
                or load_failed
            ),
        )

    if send_submitted and knowledge_base_id and session_id:
        normalized_question = question.strip()
        if not normalized_question:
            st.warning("问题不能为空。")
            return

        user_message = {
            "role": "user",
            "content": normalized_question,
            "references": [],
        }
        messages.append(user_message)
        st.session_state["streaming"] = True
        st.session_state["last_error"] = None
        completed = False
        answer = ""
        sources: list[dict[str, Any]] = []
        try:
            with st.chat_message("user"):
                st.markdown(normalized_question)
            with st.chat_message("assistant"):
                answer_placeholder = st.empty()
                for event in client.stream_chat(
                    knowledge_base_id=knowledge_base_id,
                    question=normalized_question,
                    session_id=session_id,
                    top_k=4,
                ):
                    event_type = event["type"]
                    if event_type == "delta":
                        answer += str(event["content"])
                        answer_placeholder.markdown(answer + "▌")
                    elif event_type == "sources":
                        sources = [
                            source
                            for source in event["sources"]
                            if isinstance(source, dict)
                        ]
                    elif event_type == "done":
                        completed = True
                answer_placeholder.markdown(answer)
                if completed:
                    _render_sources(sources)
        except ApiClientError as exc:
            st.session_state["last_error"] = str(exc)
            st.error(f"流式回答失败：{exc}")
        finally:
            st.session_state["streaming"] = False

        if completed:
            try:
                st.session_state["chat_messages"] = client.list_messages(
                    knowledge_base_id,
                    session_id,
                )
            except ApiClientError as exc:
                st.session_state["last_error"] = str(exc)
                messages.extend(
                    [{
                        "role": "assistant",
                        "content": answer,
                        "references": sources,
                    }]
                )
            st.rerun()
