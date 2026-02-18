from kombu import Queue

# ---------------------------------------------------------------------------
# BROKER & BACKEND
# Redis as both the message broker and result backend
# ---------------------------------------------------------------------------
broker_url = "${REDIS_URL}"
result_backend = "${REDIS_URL}"

# ---------------------------------------------------------------------------
# QUEUES
# Each endpoint has its own queue so worker pools can be sized independently
# ---------------------------------------------------------------------------
task_queues = (
    Queue("league"),
    Queue("match_list"),
    Queue("match_detail"),
    Queue("save"),
)

task_default_queue = "match_detail"

# ---------------------------------------------------------------------------
# TASK ROUTING
# Routes each task to its designated queue
# ---------------------------------------------------------------------------
task_routes = {
    "crawler.tasks.league.fetch_league":             {"queue": "league"},
    "crawler.tasks.match_list.fetch_match_list":     {"queue": "match_list"},
    "crawler.tasks.match_detail.fetch_match_detail": {"queue": "match_detail"},
    "crawler.tasks.save.save_match":                 {"queue": "save"},
}

# ---------------------------------------------------------------------------
# WORKER CONCURRENCY
# Sized according to each endpoint's method rate limit
# Override per worker using -c flag in docker-compose command if needed
# ---------------------------------------------------------------------------
worker_concurrency = 4  # default, overridden per queue below

# ---------------------------------------------------------------------------
# RELIABILITY
# acks_late=True means a task is only acknowledged (removed from queue)
# after it completes successfully — crashed tasks are automatically requeued
# ---------------------------------------------------------------------------
task_acks_late = True
task_reject_on_worker_lost = True

# ---------------------------------------------------------------------------
# SERIALIZATION
# JSON is human-readable and sufficient for our payloads
# ---------------------------------------------------------------------------
task_serializer = "json"
result_serializer = "json"
accept_content = ["json"]

# ---------------------------------------------------------------------------
# RETRIES
# Default retry policy for all tasks
# Individual tasks can override these values
# ---------------------------------------------------------------------------
task_max_retries = 5
task_default_retry_delay = 60  # seconds

# ---------------------------------------------------------------------------
# RESULT EXPIRY
# Task results are stored in Redis — expire after 1 hour to avoid memory bloat
# ---------------------------------------------------------------------------
result_expires = 3600  # seconds

# ---------------------------------------------------------------------------
# TIMEZONE
# ---------------------------------------------------------------------------
timezone = "UTC"
enable_utc = True
