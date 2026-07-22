"""知识库文件上传组件。"""

from __future__ import annotations

from typing import Any

import streamlit as st

from ui.api_client import ApiClient, ApiClientError


def render_file_uploader(
    client: ApiClient,
    knowledge_base_id: str | None,
    backend_available: bool,
) -> None:
    """渲染单文件上传入口并展示最近一次成功结果。"""

    st.subheader("上传文件")
    st.caption("支持 TXT、PDF、CSV、JSON；单文件最大 20 MiB。")
    uploaded_file = st.file_uploader(
        "选择文件",
        type=["txt", "pdf", "csv", "json"],
        accept_multiple_files=False,
        max_upload_size=20,
        disabled=not backend_available or knowledge_base_id is None,
    )
    upload_submitted = st.button(
        "上传到当前知识库",
        type="primary",
        disabled=(
            not backend_available
            or knowledge_base_id is None
            or uploaded_file is None
        ),
    )

    if knowledge_base_id is None:
        st.info("请先在左侧创建或选择知识库。")

    if upload_submitted and uploaded_file is not None and knowledge_base_id:
        content = uploaded_file.getvalue()
        if not content:
            st.warning("不能上传空文件。")
            return
        try:
            result = client.upload_file(
                knowledge_base_id=knowledge_base_id,
                filename=uploaded_file.name,
                content=content,
                content_type=uploaded_file.type,
            )
        except ApiClientError as exc:
            st.error(str(exc))
        else:
            st.session_state["last_uploaded_file"] = result
            st.success("文件已保存，处理状态为 PENDING。")

    last_upload: Any = st.session_state.get("last_uploaded_file")
    if isinstance(last_upload, dict):
        display_name = last_upload.get("original_name") or last_upload.get("file_name")
        status = last_upload.get("status", "PENDING")
        if display_name:
            st.caption(f"最近上传：{display_name} · {status}")

    st.divider()
    st.subheader("文件管理")
    st.info("文件列表、状态刷新和删除功能尚未实现。")
