"""知识库文件上传组件。"""

from __future__ import annotations

from typing import Any

import streamlit as st

from ui.api_client import ApiClient, ApiClientError


_STATUS_LABELS = {
    "PENDING": "等待处理",
    "PROCESSING": "正在处理",
    "SUCCESS": "处理成功",
    "FAILED": "处理失败",
}


def _format_file_size(value: Any) -> str:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return "未知"
    size = float(value)
    units = ("B", "KiB", "MiB", "GiB")
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{value} B"


def _format_time(value: Any) -> str:
    text = str(value or "")
    return text[:19].replace("T", " ") if text else "—"


def render_file_uploader(
    client: ApiClient,
    knowledge_base_id: str | None,
    backend_available: bool,
) -> None:
    """上传、处理、刷新和删除当前知识库的真实文件记录。"""

    header, refresh_column = st.columns([5, 1])
    with header:
        st.subheader("上传文件")
    with refresh_column:
        if st.button(
            "刷新文件",
            key="refresh_files",
            use_container_width=True,
            disabled=not backend_available or knowledge_base_id is None,
        ):
            st.rerun()
    st.caption("支持 TXT、PDF、CSV、JSON；单文件最大 20 MiB。")
    uploaded_file = st.file_uploader(
        "选择文件",
        type=["txt", "pdf", "csv", "json"],
        accept_multiple_files=False,
        max_upload_size=20,
        disabled=not backend_available or knowledge_base_id is None,
        key=f"file_uploader_{knowledge_base_id or 'none'}",
    )
    upload_submitted = st.button(
        "上传到当前知识库",
        type="primary",
        disabled=(
            not backend_available
            or knowledge_base_id is None
            or uploaded_file is None
        ),
        key=f"upload_file_{knowledge_base_id or 'none'}",
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
            st.rerun()

    last_upload: Any = st.session_state.get("last_uploaded_file")
    if isinstance(last_upload, dict):
        display_name = last_upload.get("original_name") or last_upload.get("file_name")
        status = last_upload.get("status", "PENDING")
        if display_name:
            st.caption(f"最近上传：{display_name} · {status}")

    st.divider()
    st.subheader("文件管理")
    if not backend_available:
        st.info("后端不可用，文件管理操作暂时停用。")
        return
    if knowledge_base_id is None:
        st.info("选择知识库后可查看和删除文件。")
        return

    try:
        file_records = client.list_files(knowledge_base_id)
    except ApiClientError as exc:
        st.error(str(exc))
        return

    if not file_records:
        st.session_state["files"] = []
        st.info("当前知识库还没有文件，请先上传文档。")
        return

    st.session_state["files"] = file_records
    processing_file_ids = set(
        st.session_state.get("processing_file_ids", [])
    )
    st.caption("处理接口返回持久化 Job；页面轮询真实阶段和最终状态。")
    for record in file_records:
        file_id = str(record.get("id") or "")
        display_name = str(record.get("original_name") or file_id or "未命名文件")
        current_status = str(record.get("status") or "UNKNOWN")
        status_label = _STATUS_LABELS.get(current_status, current_status)
        chunk_count = record.get("chunk_count")
        label = f"{display_name} · {status_label}"
        with st.expander(label, expanded=current_status in {"FAILED", "PROCESSING"}):
            metadata = st.columns(3)
            metadata[0].metric("状态", status_label)
            metadata[1].metric("大小", _format_file_size(record.get("file_size")))
            metadata[2].metric(
                "分块数量",
                str(chunk_count) if isinstance(chunk_count, int) else "—",
            )
            st.caption(
                f"类型：{record.get('file_type') or '—'} · "
                f"上传时间：{_format_time(record.get('created_at'))} · "
                "最近成功入库："
                f"{_format_time(record.get('last_successful_indexed_at'))}"
            )
            error_message = record.get("error_message")
            if current_status == "FAILED" and error_message:
                st.error(str(error_message))
            elif error_message:
                st.warning(str(error_message))

            process_waiting = file_id in processing_file_ids
            actions = st.columns(2)
            with actions[0]:
                process_label = (
                    "重新处理"
                    if current_status in {"FAILED", "SUCCESS"}
                    else "开始处理"
                )
                process_submitted = st.button(
                    process_label,
                    key=f"process_file_{file_id}",
                    disabled=(
                        not file_id
                        or current_status == "PROCESSING"
                        or process_waiting
                    ),
                    use_container_width=True,
                )
            with actions[1]:
                confirm_delete = st.checkbox(
                    "确认删除",
                    key=f"confirm_delete_file_{file_id}",
                    disabled=current_status == "PROCESSING" or process_waiting,
                )
                delete_submitted = st.button(
                    "删除文件",
                    key=f"delete_file_{file_id}",
                    disabled=(
                        not file_id
                        or current_status == "PROCESSING"
                        or process_waiting
                        or not confirm_delete
                    ),
                    use_container_width=True,
                )
            if confirm_delete:
                st.warning(
                    f"将删除“{display_name}”的文件记录并清理已入库向量；"
                    "此操作无法由前端撤销。"
                )

            if process_submitted:
                processing_file_ids.add(file_id)
                st.session_state["processing_file_ids"] = list(
                    processing_file_ids
                )
                process_succeeded = False
                try:
                    with st.status(
                        f"正在处理 {display_name}…",
                        expanded=True,
                    ) as status_box:
                        status_box.write(
                            "等待后端完成解析、切分、Embedding 和向量写入。"
                        )
                        submitted = client.process_file(file_id)
                        job_id = str(submitted.get("id") or "")
                        status_box.write(f"Job 已提交：{job_id}")
                        job = client.wait_for_job(job_id)
                        process_succeeded = job.get("status") == "SUCCEEDED"
                        result = job.get("result") or {}
                        final_status = str(job.get("status") or "")
                        if final_status == "SUCCEEDED":
                            status_box.update(
                                label=(
                                    f"处理成功，共生成 "
                                    f"{result.get('chunk_count', 0)} 个分块"
                                ),
                                state="complete",
                            )
                        else:
                            status_box.update(
                                label=f"处理结束：{final_status or '未知状态'}",
                                state="error",
                            )
                except ApiClientError as exc:
                    st.error(str(exc))
                finally:
                    processing_file_ids.discard(file_id)
                    st.session_state["processing_file_ids"] = list(
                        processing_file_ids
                    )
                if process_succeeded:
                    st.rerun()

            if delete_submitted:
                try:
                    client.delete_file(file_id)
                except ApiClientError as exc:
                    st.error(str(exc))
                else:
                    processing_file_ids.discard(file_id)
                    st.session_state["processing_file_ids"] = list(
                        processing_file_ids
                    )
                    last_uploaded = st.session_state.get("last_uploaded_file")
                    if isinstance(last_uploaded, dict) and str(
                        last_uploaded.get("id")
                    ) == file_id:
                        st.session_state.pop("last_uploaded_file", None)
                    st.success(f"已删除文件：{display_name}")
                    st.rerun()
