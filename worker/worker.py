import json
import logging
import signal
import time
from uuid import UUID

from psycopg import DataError
from store import cache, database, initialize, QUEUE

DEAD_LETTER_QUEUE = f"{QUEUE}:dead"

logging.basicConfig(level=logging.INFO)
running = True
def stop(*_):
    global running
    running = False

def decode_job(payload):
    job = json.loads(payload)
    if not isinstance(job, dict) or not isinstance(job.get("id"), str) or not isinstance(job.get("text"), str):
        raise ValueError("Invalid job fields")
    identifier = UUID(job["id"])
    text = job["text"]
    if "\x00" in text:
        raise ValueError("Job text contains NUL")
    text.encode("utf-8")
    return identifier, text.upper()

def process_job(payload):
    try:
        identifier, result = decode_job(payload)
    except (ValueError, RecursionError):
        return "invalid queued job"
    try:
        with database() as conn:
            conn.execute("INSERT INTO job_results (id, result) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
                         (identifier, result))
    except DataError:
        return "database rejected job data"
    logging.info("Completed job %s", identifier)
    return None

def main():
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while running:
        try:
            initialize()
            client = cache()
            while running:
                item = client.blpop(QUEUE, timeout=2)
                if not item:
                    continue
                payload = item[1]
                try:
                    reason = process_job(payload)
                    if reason is None:
                        continue
                    try:
                        client.rpush(DEAD_LETTER_QUEUE, payload)
                    except Exception:
                        logging.error("Could not write dead-letter entry; attempting to requeue")
                        raise
                    logging.warning("Dead-lettered job: %s", reason)
                except Exception:
                    client.lpush(QUEUE, payload)
                    raise
        except Exception:
            logging.error("Worker dependency failure; retrying")
            time.sleep(2)

if __name__ == "__main__":
    main()
