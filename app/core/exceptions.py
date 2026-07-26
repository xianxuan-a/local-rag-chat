"""Application exception hierarchy used by global API handlers."""

from __future__ import annotations

from typing import Any, ClassVar


class AppException(Exception):
    """Base class for errors that may be safely presented to an API client."""

    default_message: ClassVar[str] = "请求处理失败"
    default_status_code: ClassVar[int] = 400

    def __init__(
        self,
        message: str | None = None,
        *,
        code: int | None = None,
        status_code: int | None = None,
        data: Any = None,
    ) -> None:
        self.message = message or self.default_message
        self.status_code = status_code or self.default_status_code
        self.code = code if code is not None else self.status_code
        self.data = data
        super().__init__(self.message)


class ValidationException(AppException):
    default_message = "请求参数无效"
    default_status_code = 400


class ResourceNotFoundException(AppException):
    default_message = "请求的资源不存在"
    default_status_code = 404


class ConflictException(AppException):
    default_message = "资源状态冲突"
    default_status_code = 409


class PayloadTooLargeException(AppException):
    default_message = "上传内容超过大小限制"
    default_status_code = 413


class UnsupportedFileTypeException(AppException):
    default_message = "不支持的文件类型"
    default_status_code = 415


class FeatureNotImplementedException(AppException):
    default_message = "该功能尚未实现"
    default_status_code = 501


class FileProcessException(AppException):
    default_message = "文件处理失败"
    default_status_code = 400


class VectorStoreException(AppException):
    default_message = "向量存储服务异常"
    default_status_code = 500


class ModelServiceException(AppException):
    default_message = "模型服务异常"
    default_status_code = 500


class ConfigurationException(AppException):
    default_message = "服务配置不完整"
    default_status_code = 500
