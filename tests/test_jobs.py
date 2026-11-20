import importlib.util
import json
import os
import unittest
from contextlib import contextmanager
from collections import defaultdict, deque
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import psycopg
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError

ROOT = Path(__file__).resolve().parents[1]
QUEUE = "starter:jobs"
DEAD_LETTER_QUEUE = "starter:jobs:dead"


def load_app(name):
    def load_file(module_name, path):
        spec = importlib.util.spec_from_file_location(module_name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    store = load_file(f"{name}_store", ROOT / name / "store.py")
    with patch.dict("sys.modules", {"store": store}):
        return load_file(name, ROOT / name / f"{name}.py")


api = load_app("api")
worker = load_app("worker")


class Queue:
    def __init__(self, *entries):
        self.lists = defaultdict(deque, {QUEUE: deque(entries)})

    def rpush(self, key, value):
        self.lists[key].append(value)

    def lpush(self, key, value):
        self.lists[key].appendleft(value)

    def blpop(self, key, timeout):
        if self.lists[key]:
            return key, self.lists[key].popleft()
        worker.running = False


class JobTests(unittest.TestCase):
    def test_nul_rejected_without_enqueueing_or_echoing_input(self):
        queue = Queue()
        with patch.object(api, "cache", return_value=queue), TestClient(api.app) as client:
            response = client.post("/jobs", json={"text": "private\x00text"})
            self.assertEqual(response.status_code, 422)
            self.assertIn("NUL", response.json()["detail"])
            self.assertNotIn("private", response.text)
            self.assertEqual(list(queue.lists[QUEUE]), [])
            response = client.post("/jobs", json={"text": "hello"})
            self.assertEqual(response.status_code, 202)
            self.assertEqual(json.loads(queue.lists[QUEUE][0])["id"], response.json()["id"])

    def run_worker(self, queue, database):
        with (
            patch.object(worker, "running", True),
            patch.object(worker.signal, "signal"),
            patch.object(worker, "initialize"),
            patch.object(worker, "cache", return_value=queue),
            patch.object(worker, "database", side_effect=database),
            patch.object(worker.time, "sleep", side_effect=lambda _: worker.stop()),
        ):
            worker.main()

    def test_permanent_input_failures_do_not_block_following_job(self):
        valid_id = str(uuid4())
        valid = json.dumps({"id": valid_id, "text": "hello"})
        bad_entries = [
            json.dumps({"id": str(uuid4()), "text": "\x00"}),
            "{",
            "[" * 2000 + "]" * 2000,
            "null",
            json.dumps({"id": "invalid", "text": "hello"}),
            json.dumps({"id": str(uuid4()), "text": None}),
            json.dumps({"id": str(uuid4()), "text": "\ud800"}),
        ]
        with psycopg.connect(os.environ["INFERRA_TEST_DATABASE_URL"], autocommit=True) as conn:
            conn.execute("CREATE TEMP TABLE job_results (id UUID PRIMARY KEY, result TEXT NOT NULL)")
            for bad in bad_entries:
                with self.subTest(entry=bad):
                    conn.execute("DELETE FROM job_results")
                    queue = Queue(bad, valid)

                    self.run_worker(queue, lambda: database_transaction(conn))
                    self.assertEqual(list(queue.lists[DEAD_LETTER_QUEUE]), [bad])
                    self.assertEqual(list(queue.lists[QUEUE]), [])
                    self.assertEqual(conn.execute("SELECT result FROM job_results").fetchall(), [("HELLO",)])

    def test_database_data_error_dead_letters_job(self):
        bad = json.dumps({"id": str(uuid4()), "text": "too long"})
        good = json.dumps({"id": str(uuid4()), "text": "ok"})
        queue = Queue(bad, good)
        with psycopg.connect(os.environ["INFERRA_TEST_DATABASE_URL"], autocommit=True) as conn:
            conn.execute("CREATE TEMP TABLE job_results (id UUID PRIMARY KEY, result VARCHAR(2) NOT NULL)")
            self.run_worker(queue, lambda: database_transaction(conn))
            self.assertEqual(list(queue.lists[DEAD_LETTER_QUEUE]), [bad])
            self.assertEqual(conn.execute("SELECT result FROM job_results").fetchall(), [("OK",)])

    def test_database_outage_requeues_valid_job(self):
        valid = json.dumps({"id": str(uuid4()), "text": "hello"})
        queue = Queue(valid)

        def database():
            raise psycopg.OperationalError("database offline")

        self.run_worker(queue, database)
        self.assertEqual(list(queue.lists[QUEUE]), [valid])
        self.assertEqual(list(queue.lists[DEAD_LETTER_QUEUE]), [])

    def test_dead_letter_write_failure_requeues_original_job(self):
        bad = "{"
        queue = Queue(bad)
        with patch.object(queue, "rpush", side_effect=ConnectionError):
            self.run_worker(queue, None)
        self.assertEqual(list(queue.lists[QUEUE]), [bad])


@contextmanager
def database_transaction(connection):
    with connection.transaction():
        yield connection
