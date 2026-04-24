# Video Generation Platform

Seedance-centered video generation platform.

This repository is structured as a product platform rather than a single script:

- FastAPI backend for projects, planning, generation, assets, timelines, subtitles, and exports
- Celery worker for background orchestration
- Redis and MinIO through Docker for local development
- PostgreSQL expected to run locally for now
- FFmpeg/ffprobe used by media services

## Local Development

Prepare local services and `.env`:

```bash
./scripts/enter-dev.sh
```

Create the conda environment:

```bash
conda create -n video-platform --override-channels -c conda-forge python=3.12 pip ffmpeg -y
conda activate video-platform
pip install -r requirements.txt
```

Copy and edit environment variables:

```bash
cp .env.example .env
```

Start local infrastructure:

```bash
docker compose up -d
```

Run the API:

```bash
./scripts/start-api.sh
```

Run the web app:

```bash
./scripts/start-web.sh
```

Run the worker:

```bash
celery -A apps.worker.app.celery_app worker --loglevel=info
```

Run tests:

```bash
pytest -q
pnpm --dir apps/web exec tsc --noEmit
pnpm --dir apps/web build
```

## Services

- API: http://localhost:8000
- API docs: http://localhost:8000/docs
- Web app: http://localhost:3000
- Redis: localhost:6379
- MinIO API: http://localhost:9000
- MinIO console: http://localhost:9001

## Current Status

Implemented:

- Project CRUD and Chinese web workspace
- Rule-based Seedance prompt optimization
- Shot planning from project briefs
- Seedance task records and Celery worker entrypoints
- Configurable Seedance submit/query client
- MinIO upload/download helpers
- Timeline generation
- FFmpeg render planning and basic MP4 render execution
- Pytest coverage for prompt planning, Seedance response parsing, and FFmpeg rendering
- GitHub Actions CI

Still in progress:

- End-to-end live Seedance validation requires a real `ARK_API_KEY` and a console-enabled Seedance model.
- Advanced transitions, subtitle burn-in, BGM mixing, and render presets are planned after the basic MP4 render path.
- Upload UI and settings UI are still placeholders.

## Current Pipeline APIs

The first internal pipeline is Seedance-only for generation and FFmpeg for assembly/rendering.

- `POST /projects/{project_id}/prompt/optimize` optimizes the project brief into a Seedance-ready master prompt.
- `POST /projects/{project_id}/shots/plan` creates Seedance-ready shot prompts from the project brief.
- `POST /projects/{project_id}/generation-tasks` queues local Seedance generation tasks.
- `POST /projects/{project_id}/generation-tasks/{task_id}/submit` dispatches a worker job to submit a Seedance task.
- `POST /projects/{project_id}/generation-tasks/{task_id}/poll` dispatches a worker job to poll a Seedance task.
- `POST /projects/{project_id}/assets` registers generated or uploaded media assets.
- `POST /projects/{project_id}/timelines` builds an editable timeline from planned shots.
- `POST /projects/{project_id}/render-jobs` creates an FFmpeg render plan for the latest timeline.
- `POST /projects/{project_id}/render-jobs/{render_job_id}/run` dispatches a worker job to render the latest timeline.

`ARK_API_KEY` must be set before the worker can submit real Seedance jobs. Configure Seedance endpoints in `.env` when your Volcano Engine product line uses a different base URL or path:

```env
ARK_API_KEY=your-api-key
SEEDANCE_API_BASE_URL=https://operator.las.cn-beijing.volces.com/api/v1
SEEDANCE_SUBMIT_PATH=/contents/generations/tasks
SEEDANCE_QUERY_PATH_TEMPLATE=/contents/generations/tasks/{task_id}
```

The local MinIO credentials in `docker-compose.yml` are development defaults only. Do not use them in production.
