bind = "0.0.0.0:10000"
# Keep workers = 1: app/routes.py's single-flight locks (_fetch_locks) that
# coalesce concurrent cache-misses into one live LeetCode API call are an
# in-process dict, not shared across workers. >1 worker means each worker
# has its own lock registry, so N workers can each independently make the
# "first" live call for the same cache-miss - multiplying outbound API
# traffic by worker count instead of coalescing it.
workers = 1
worker_class = "uvicorn.workers.UvicornWorker"
worker_connections = 20  # Further reduced
timeout = 900  # 15 minutes for large student lists
keepalive = 5
max_requests = 25  # Restart worker more frequently
max_requests_jitter = 5
graceful_timeout = 120
worker_tmp_dir = '/dev/shm'  # Use shared memory for worker files (faster on Render)
