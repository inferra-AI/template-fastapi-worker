import json
from uuid import uuid4, UUID
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from store import cache, database, initialize, QUEUE

app = FastAPI(title="Inferra jobs")
class Job(BaseModel):
    text: str = Field(min_length=1, max_length=10000)

@app.get("/health")
def health():
    try:
        with database() as conn:
            conn.execute("SELECT 1")
        cache().ping()
        return {"status": "ok"}
    except Exception:
        raise HTTPException(503, "Dependencies unavailable")

@app.post("/jobs", status_code=202)
def enqueue(job: Job):
    identifier = str(uuid4())
    cache().rpush(QUEUE, json.dumps({"id": identifier, "text": job.text}))
    return {"id": identifier}

@app.get("/jobs/{identifier}")
def result(identifier: UUID):
    initialize()
    with database() as conn:
        row = conn.execute("SELECT result FROM job_results WHERE id = %s", (identifier,)).fetchone()
    return {"id": str(identifier), "status": "completed" if row else "pending", "result": row[0] if row else None}
