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

## Services

- API: http://localhost:8000
- API docs: http://localhost:8000/docs
- Web app: http://localhost:3000
- Redis: localhost:6379
- MinIO API: http://localhost:9000
- MinIO console: http://localhost:9001

## Current Pipeline APIs

The first internal pipeline is Seedance-only for generation and FFmpeg for assembly/render planning.

- `POST /projects/{project_id}/shots/plan` creates Seedance-ready shot prompts from the project brief.
- `POST /projects/{project_id}/prompt/optimize` optimizes the project brief into a Seedance-ready master prompt.
- `POST /projects/{project_id}/generation-tasks` queues local Seedance generation tasks.
- `POST /projects/{project_id}/assets` registers generated or uploaded media assets.
- `POST /projects/{project_id}/timelines` builds an editable timeline from planned shots.
- `POST /projects/{project_id}/render-jobs` creates an FFmpeg render plan for the latest timeline.

`ARK_API_KEY` must be set before the worker can submit real Seedance jobs. Without it, generation tasks are kept as local queued records.
