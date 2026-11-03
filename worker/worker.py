import json
import logging
import signal
import time
from store import cache, database, initialize, QUEUE

logging.basicConfig(level=logging.INFO)
running = True
def stop(*_):
    global running
    running = False

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
                job = json.loads(item[1])
                try:
                    with database() as conn:
                        conn.execute("INSERT INTO job_results (id, result) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
                                     (job["id"], job["text"].upper()))
                except Exception:
                    client.lpush(QUEUE, item[1])
                    raise
                logging.info("Completed job %s", job["id"])
        except Exception:
            logging.exception("Worker dependency failure; retrying")
            time.sleep(2)

if __name__ == "__main__":
    main()
