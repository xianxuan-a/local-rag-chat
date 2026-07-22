"""UUID-based identifiers used throughout the project."""

from uuid import uuid4


def generate_id() -> str:
    """Generate a random UUID string."""
    return str(uuid4())


def generate_file_id() -> str:
    return generate_id()


def generate_knowledge_base_id() -> str:
    return generate_id()


def generate_session_id() -> str:
    return generate_id()


def generate_message_id() -> str:
    return generate_id()


def generate_chunk_id() -> str:
    return generate_id()
