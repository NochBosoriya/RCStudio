import logging
from typing import List

from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from pydantic import BaseModel, HttpUrl
from sqlalchemy.orm import Session

from ..models import get_db, Project, MediaAsset, DownloadJob, SessionLocal
from ..services.downloader_service import DownloadManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/download", tags=["download"])


class URLRequest(BaseModel):
    urls: List[HttpUrl]
    project_id: int


class FormatSelectRequest(BaseModel):
    url: HttpUrl
    format_id: str
    project_id: int


class HongguoParseRequest(BaseModel):
    url: HttpUrl
    project_id: int


@router.post("/info")
async def get_media_info(url: HttpUrl):
    """Get media info without downloading."""
    manager = DownloadManager()
    try:
        info = manager.get_media_info(str(url))
        return {
            "id": info.id,
            "title": info.title,
            "duration": info.duration,
            "width": info.width,
            "height": info.height,
            "fps": info.fps,
            "formats": [
                {
                    "format_id": f.format_id,
                    "ext": f.ext,
                    "resolution": f.resolution,
                    "fps": f.fps,
                    "vcodec": f.vcodec,
                    "acodec": f.acodec,
                    "filesize": f.filesize,
                }
                for f in info.formats
            ],
            "thumbnail_url": info.thumbnail_url,
            "source": manager.detect_source(str(url)),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/start")
async def start_download(
    request: URLRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Start batch download job."""
    # Verify project exists
    project = db.query(Project).filter(Project.id == request.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if not request.urls:
        raise HTTPException(status_code=400, detail="No URLs provided")

    # Snapshot request values so the background task never touches the
    # request-scoped session or ORM instances owned by it.
    project_id = request.project_id
    url_list = [str(u) for u in request.urls]

    # Create download job record (request-scoped session is fine here)
    job = DownloadJob(
        project_id=project_id,
        url=url_list[0],
        status="pending",
        progress=0.0,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    job_id = job.id

    # Build the response BEFORE registering the background task so job_id is
    # always available to the caller regardless of what the task does.
    response = {"job_id": job_id, "status": "started"}

    def run_download():
        """Runs after the response is sent. Owns its own DB session."""
        session = SessionLocal()
        try:
            job_row = session.query(DownloadJob).filter(DownloadJob.id == job_id).first()
            if job_row is None:
                logger.error("Download job %s not found in database", job_id)
                return

            job_row.status = "downloading"
            job_row.progress = 0.0
            session.commit()

            manager = DownloadManager()
            total = len(url_list)

            def make_progress_cb(index: int):
                def progress_cb(progress: float, message: str):
                    try:
                        job_row.progress = max(0.0, min(1.0, (index + progress) / total))
                        session.commit()
                    except Exception:
                        # Progress updates must never kill the job.
                        session.rollback()
                        logger.warning(
                            "Failed to persist progress for job %s at %s/%s",
                            job_id, index, total,
                        )
                return progress_cb

            # Download one URL at a time so each MediaInfo stays paired with
            # the exact source URL it came from (needed for dedupe and to keep
            # going when one URL fails).
            downloaded = []  # list[tuple[str, MediaInfo]]
            for i, url in enumerate(url_list):
                try:
                    info = manager.download(url, project_id, make_progress_cb(i))
                    downloaded.append((url, info))
                except Exception as e:
                    logger.error("Failed to download %s: %s", url, e)

            if not downloaded:
                raise RuntimeError("All downloads failed")

            # Persist assets with dedupe (by file_path OR url + project_id).
            for url, info in downloaded:
                existing = None

                # 1) Dedupe by file_path.
                if info.filepath:
                    existing = (
                        session.query(MediaAsset)
                        .filter(MediaAsset.file_path == info.filepath)
                        .first()
                    )

                # 2) Dedupe by (source_url + project_id). Compare in Python so
                # this works on SQLite and Postgres alike without JSON operators.
                if existing is None:
                    candidates = (
                        session.query(MediaAsset)
                        .filter(MediaAsset.project_id == project_id)
                        .all()
                    )
                    for candidate in candidates:
                        meta = candidate.asset_metadata or {}
                        if meta.get("source_url") == url:
                            existing = candidate
                            break

                if existing is not None:
                    logger.info(
                        "Skipping duplicate asset for %s (existing id=%s)",
                        url, existing.id,
                    )
                    continue

                asset = MediaAsset(
                    project_id=project_id,
                    file_path=info.filepath,
                    asset_metadata={
                        "title": info.title,
                        "duration": info.duration,
                        "width": info.width,
                        "height": info.height,
                        "fps": info.fps,
                        "source_url": url,
                    },
                )
                session.add(asset)

            job_row.status = "completed"
            job_row.progress = 1.0
            session.commit()
            logger.info("Download job %s completed (%s assets)", job_id, len(downloaded))

        except Exception as e:
            logger.error("Download job %s failed: %s", job_id, e, exc_info=True)
            # Mark the job failed on ANY exception, including asset creation.
            try:
                session.rollback()
                job_row = (
                    session.query(DownloadJob)
                    .filter(DownloadJob.id == job_id)
                    .first()
                )
                if job_row is not None:
                    job_row.status = "failed"
                    session.commit()
            except Exception as inner:
                logger.error(
                    "Failed to mark job %s as failed: %s", job_id, inner, exc_info=True,
                )
                session.rollback()
        finally:
            session.close()

    background_tasks.add_task(run_download)

    return response


@router.get("/job/{job_id}")
async def get_download_job(job_id: int, db: Session = Depends(get_db)):
    """Get download job status."""
    job = db.query(DownloadJob).filter(DownloadJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "id": job.id,
        "status": job.status,
        "progress": job.progress,
    }


@router.post("/hongguo/parse")
async def parse_hongguo_drama(request: HongguoParseRequest):
    """Parse Hongguo drama link for episode list."""
    from ..services.downloader_service import HongguoDownloaderAdapter

    adapter = HongguoDownloaderAdapter()
    if not adapter.is_available():
        raise HTTPException(status_code=400, detail="Hongguo downloader not configured")

    parsed = adapter.parse_drama_link(str(request.url))
    return parsed


@router.get("/project/{project_id}/assets")
async def get_project_assets(project_id: int, db: Session = Depends(get_db)):
    """Get all media assets for a project."""
    assets = db.query(MediaAsset).filter(MediaAsset.project_id == project_id).all()
    return [
        {
            "id": a.id,
            "file_path": a.file_path,
            "metadata": a.asset_metadata,
        }
        for a in assets
    ]
