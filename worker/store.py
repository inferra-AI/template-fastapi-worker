import os
import psycopg
from redis import Redis

QUEUE = "starter:jobs"
def database():
    return psycopg.connect(os.environ["DB_URL"], connect_timeout=5)
def cache():
    return Redis.from_url(os.environ["CACHE_URL"], decode_responses=True, socket_connect_timeout=5, socket_timeout=5)
def initialize():
    with database() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS job_results (
            id UUID PRIMARY KEY, result TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
