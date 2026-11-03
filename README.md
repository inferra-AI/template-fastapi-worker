# FastAPI + worker

[![Deploy to Inferra](https://inferralab.com/assets/deploy-to-inferra.svg)](https://github.com/new?template_owner=inferra-AI&template_name=template-fastapi-worker)

The `api` app accepts jobs, enqueues them in a Valkey list, and returns a UUID. The separate `worker` app uppercases each job and stores the result in shared Postgres. `/health` checks both dependencies.

## Deploy

1. Click **Deploy to Inferra** or **Use this template** to create your repository with a `main` branch.
2. Install the Inferra GitHub App and grant it access to your new repository.
3. Add the database and the cache to your account repository (below), then push to `main`. Inferra builds each app folder with buildpacks and deploys both apps.

This repository uses Inferra configuration version 3. Each app has its own folder, and Inferra builds each folder on its own:

- `.inferra/repo.yaml` says which branches run (only `main`).
- `api/.inferra/app.yaml`: the `api` web app on port 8000 with a `/health` check.
- `worker/.inferra/app.yaml`: the `worker` app, one instance, no public route.

Both apps bind the services named `db` and `cache`.

### Add the services to your account repository

Services are declared once per account, in your private `<account>/.inferra` repository, not in this repository. Add these two files there (any file names work) and replace `template-fastapi-worker` under `attach:` with your repository's name.

`services/jobs-db.yaml`:

```yaml
version: 3
name: db
type: postgres
hosting: native
data: dedicated
cpu: 0.25
memory: 256Mi
storage: 1Gi
attach:
  template-fastapi-worker:   # your repository's name
    branches: [main]
    access: readwrite
```

`services/jobs-cache.yaml`:

```yaml
version: 3
name: cache
type: valkey
hosting: native
data: dedicated
cpu: 0.1
memory: 256Mi
attach:
  template-fastapi-worker:   # your repository's name
    branches: [main]
    access: readwrite
```

The apps bind `db` and `cache`, so Inferra gives them `DB_URL` and `CACHE_URL`. If your account repository has an `account.yaml`, also list this repository under `repos:` with a quota. Keep credentials out of configuration files.

## Local run

Use Python 3.12 and Docker Compose. Start local dependencies and copy the environment example:

```sh
docker compose up -d
cp .env.example .env
# These sample credentials are only for the local database.
set -a
. ./.env
set +a
python3.12 -m venv /tmp/inferra-api-local
/tmp/inferra-api-local/bin/python -m pip install -r api/requirements.txt
(cd api && /tmp/inferra-api-local/bin/uvicorn api:app --host 0.0.0.0 --port 8000)
# In a second terminal, load .env again and run:
# python3.12 -m venv /tmp/inferra-worker-local
# /tmp/inferra-worker-local/bin/python -m pip install -r worker/requirements.txt
# (cd worker && /tmp/inferra-worker-local/bin/python worker.py)
```

Wait until Postgres is ready if the first request fails. Variables must be exported in every terminal used to start an app. `docker compose down` stops local services; `docker compose down -v` also removes local data.

Submit a job and use its returned ID:

```sh
curl -s http://localhost:8000/health
curl -s -X POST http://localhost:8000/jobs -H 'Content-Type: application/json' -d '{"text":"hello inferra"}'
curl -s http://localhost:8000/jobs/REPLACE_WITH_RETURNED_UUID
```

The result becomes `HELLO INFERRA`. `/docs` provides interactive API documentation. The worker creates `job_results` automatically. The worker has no public route or HTTP health check.

This minimal queue uses `BLPOP`: a worker crash between dequeue and database commit can lose a job. Database failures requeue the job, and inserts are idempotent by UUID. Use a durable queue with acknowledgments for production workloads.

## Files

- `.inferra/repo.yaml`: branches that run.
- `api/.inferra/app.yaml`, `worker/.inferra/app.yaml`: process, port or instances, health check, service bindings for each app.
- `api/api.py`: health, job submission, and result endpoints.
- `worker/worker.py`: blocking queue consumer, dependency retries, and signal handling.
- `api/store.py`, `worker/store.py`: shared connections, queue name, and table creation. Each folder builds on its own, so each has its own copy; keep the two identical.
- `api/requirements.txt`, `worker/requirements.txt`: pinned runtime dependencies for each app (including transitive dependencies).
- `api/Procfile`, `worker/Procfile`: buildpack process command for each app.
- `api/.python-version`, `worker/.python-version`: buildpack Python version selection.
- `compose.yaml`: pinned local Postgres and Valkey containers and database volume.
- `.env.example`: local environment values; copy to ignored `.env`.
- `.gitignore`: keeps local credentials and generated files out of Git.
- `LICENSE`: MIT license.
- `README.md`: deployment and local instructions.
