# KhmerDub Studio Production Readiness Plan

## 1. Infrastructure Migration (Docker)
- **Objective**: Containerize the app for consistent deployment.
- **Tasks**:
  - [ ] Create `Dockerfile` for the backend (FastAPI + Celery + PyTorch).
  - [ ] Create `Dockerfile` for the frontend (Next.js SSR).
  - [ ] Create `docker-compose.yml` orchestrating API, Worker, Redis, PostgreSQL.

## 2. Real API Integration (TanStack Query)
- **Objective**: Connect the frontend UI to real endpoints.
- **Tasks**:
  - [ ] Configure `axios` base client in `frontend/src/lib/api.ts`.
  - [ ] Implement `useQuery` and `useMutation` hooks for project, download, and dubbing modules.
  - [ ] Implement WebSocket or Polling hook for job status updates (`/api/overlay/job/{job_id}`).

## 3. Database & Auth
- **Objective**: Move from SQLite to PostgreSQL + add security.
- **Tasks**:
  - [ ] Migrate `app/config.py` to use `postgresql://` URI.
  - [ ] Add `fastapi-users` or basic JWT/Auth middleware to `app/main.py`.
  - [ ] Update `app/models.py` to support multi-tenancy (project ownership).

## 4. Production Storage
- **Objective**: Offload files from local disk to object storage.
- **Tasks**:
  - [ ] Replace `os.path` operations with `boto3` (AWS S3) or `google-cloud-storage` abstractions in `thumbnail_ai_service.py` and `downloader_service.py`.

---

**Current Status**: 
- The project is fully scaffolded and tested. 
- **Next immediate action**: Choose a component to prioritize. I recommend **Dockerization** as the first step to ensure everything runs reliably before we start replacing local data with external infrastructure. 

**Shall I generate the `Dockerfile` and `docker-compose.yml` setup?**
