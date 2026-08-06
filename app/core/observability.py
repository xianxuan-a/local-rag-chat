"""Low-cardinality Prometheus metrics shared across API and worker code."""

from prometheus_client import Counter, Histogram


HTTP_REQUESTS = Counter(
    "local_rag_http_requests_total",
    "HTTP requests by method, route template, and status",
    ("method", "route", "status"),
)
HTTP_ERRORS = Counter(
    "local_rag_http_errors_total",
    "HTTP responses with status >= 400",
    ("method", "route", "status"),
)
HTTP_DURATION = Histogram(
    "local_rag_http_request_duration_seconds",
    "HTTP request duration by method and route template",
    ("method", "route"),
)
JOB_TERMINALS = Counter(
    "local_rag_jobs_terminal_total",
    "Jobs reaching a terminal status",
    ("job_type", "status"),
)
JOB_DURATION = Histogram(
    "local_rag_job_duration_seconds",
    "Job execution duration",
    ("job_type",),
)
FILE_PROCESS_TERMINALS = Counter(
    "local_rag_file_process_terminal_total",
    "File process jobs by terminal outcome",
    ("status",),
)
EMBEDDING_ERRORS = Counter(
    "local_rag_embedding_errors_total",
    "Embedding call errors",
)
GENERATION_ERRORS = Counter(
    "local_rag_generation_errors_total",
    "Generation call errors",
)
RETRIEVAL_DURATION = Histogram(
    "local_rag_retrieval_duration_seconds",
    "Vector retrieval duration",
)
RAG_DURATION = Histogram(
    "local_rag_rag_duration_seconds",
    "End-to-end RAG service duration",
    ("mode",),
)
RETRIEVAL_MODE_DECISIONS = Counter(
    "local_rag_retrieval_mode_decisions_total",
    "Retrieval requests by requested and effective mode",
    ("requested_mode", "effective_mode"),
)
WEB_SEARCH_OUTCOMES = Counter(
    "local_rag_web_search_outcomes_total",
    "Web retrieval outcomes by bounded status and provider state",
    ("status", "provider_status"),
)
RETRIEVAL_STAGE_DURATION = Histogram(
    "local_rag_retrieval_stage_duration_seconds",
    "Retrieval-stage duration by bounded stage name",
    ("stage",),
)
RETRIEVAL_SOURCE_COUNT = Histogram(
    "local_rag_retrieval_source_count",
    "Usable retrieval sources by provenance type",
    ("source_type",),
    buckets=(0, 1, 2, 3, 5, 8, 13, 21),
)
