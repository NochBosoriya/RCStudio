from fastapi import APIRouter, HTTPException, Body, Query
from pydantic import BaseModel, Field
from typing import Optional, List
import os
import tempfile
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from app.services.thumbnail_ai_service import (
    ThumbnailAIService,
    ThumbnailSpec,
    OverlayService,
    generate_thumbnail_job,
    burn_subtitles_job,
    add_watermark_job,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/overlay", tags=["overlay"])

# Thread pool for blocking operations
overlay_executor = ThreadPoolExecutor(max_workers=2)

# In-memory job tracking (replace with Redis/DB in production)
overlay_jobs = {}


class ThumbnailGenerateRequest(BaseModel):
    """Request model for thumbnail generation."""
    width: int = 1280
    height: int = 720
    background_color: List[int] = [0, 0, 0]
    title_text: str = ""
    subtitle_text: str = ""
    episode_number: Optional[int] = None
    watermark_path: Optional[str] = None
    watermark_opacity: float = 0.3
    watermark_position: str = "bottom-right"
    font_path: Optional[str] = None
    title_font_size: int = 72
    subtitle_font_size: int = 36
    episode_font_size: int = 48
    text_color: List[int] = [255, 255, 255]
    text_stroke_color: List[int] = [0, 0, 0]
    text_stroke_width: int = 3
    background_image: Optional[str] = None
    background_blur: float = 0.0
    background_overlay_color: List[int] = [0, 0, 0, 128]


class AutoFrameRequest(BaseModel):
    """Request model for auto-framing."""
    image_path: str
    target_aspect: float = 16/9


class VideoFrameExtractRequest(BaseModel):
    """Request model for video frame extraction."""
    video_path: str
    timestamp: float


class EpisodeThumbnailsRequest(BaseModel):
    """Request model for episode thumbnail generation."""
    video_path: str
    episode_num: int
    title: str
    subtitle: str = ""
    watermark_path: Optional[str] = None
    timestamps: Optional[List[float]] = None


class WatermarkRequest(BaseModel):
    """Request model for adding watermark to video."""
    input_video: str
    watermark_path: str
    position: str = "bottom-right"
    opacity: float = 0.5
    margin: int = 30


class SubtitleBurnRequest(BaseModel):
    """Request model for burning subtitles into video."""
    input_video: str
    srt_path: str
    font_path: Optional[str] = None
    font_size: int = 24
    font_color: str = "white"
    outline_color: str = "black"
    outline_width: int = 2
    margin_v: int = 50


class GraphicOverlayRequest(BaseModel):
    """Request model for adding graphic overlay to video."""
    input_video: str
    overlay_path: str
    start_time: float = 0
    duration: Optional[float] = None
    position: str = "bottom-right"
    opacity: float = 1.0
    margin: int = 30
    fade_in: float = 0.5
    fade_out: float = 0.5


class LowerThirdRequest(BaseModel):
    """Request model for creating lower third graphic."""
    text: str
    name: str = ""
    role: str = ""
    width: int = 1280
    height: int = 200
    bg_color: List[int] = [0, 0, 0, 200]
    text_color: List[int] = [255, 255, 255]
    accent_color: List[int] = [255, 200, 0]
    font_path: Optional[str] = None


class JobStatusResponse(BaseModel):
    """Job status response."""
    job_id: str
    status: str
    progress: float
    message: str
    result: Optional[dict] = None


def _run_in_executor(func, *args, **kwargs):
    """Run blocking function in thread pool."""
    loop = __import__('asyncio').get_event_loop()
    return loop.run_in_executor(overlay_executor, partial(func, *args, **kwargs))


async def _handle_blocking_job(job_id: str, func, *args, **kwargs):
    """
    Handle a blocking job: run in executor, update job status, return result.
    This allows the API to return immediately with job_id for polling.
    """
    # Initialize job status
    overlay_jobs[job_id] = {
        "job_id": job_id,
        "status": "running",
        "progress": 0.0,
        "message": "Starting...",
        "result": None
    }

    def progress_cb(progress: float, msg: str):
        if job_id in overlay_jobs:
            overlay_jobs[job_id].update({
                "progress": progress,
                "message": msg
            })

    try:
        # Run blocking work in thread pool
        result = await _run_in_executor(func, *args, progress_callback=progress_cb, **kwargs)

        overlay_jobs[job_id] = {
            "job_id": job_id,
            "status": "completed",
            "progress": 1.0,
            "message": "Completed successfully",
            "result": result
        }
        return result
    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}", exc_info=True)
        overlay_jobs[job_id] = {
            "job_id": job_id,
            "status": "failed",
            "progress": 0.0,
            "message": str(e),
            "result": None
        }
        raise


@router.post("/thumbnail/generate", response_model=JobStatusResponse)
async def generate_thumbnail(request: ThumbnailGenerateRequest = Body(...)):
    """
    Generate a thumbnail image from specification.
    Returns job ID for async tracking.
    """
    job_id = str(uuid.uuid4())

    spec = ThumbnailSpec(
        width=request.width,
        height=request.height,
        background_color=tuple(request.background_color),
        title_text=request.title_text,
        subtitle_text=request.subtitle_text,
        episode_number=request.episode_number,
        watermark_path=request.watermark_path,
        watermark_opacity=request.watermark_opacity,
        watermark_position=request.watermark_position,
        font_path=request.font_path,
        title_font_size=request.title_font_size,
        subtitle_font_size=request.subtitle_font_size,
        episode_font_size=request.episode_font_size,
        text_color=tuple(request.text_color),
        text_stroke_color=tuple(request.text_stroke_color),
        text_stroke_width=request.text_stroke_width,
        background_image=request.background_image,
        background_blur=request.background_blur,
        background_overlay_color=tuple(request.background_overlay_color),
    )

    # Validate background image if provided
    if spec.background_image and not os.path.exists(spec.background_image):
        raise HTTPException(status_code=400, detail=f"Background image not found: {spec.background_image}")

    # Validate watermark if provided
    if spec.watermark_path and not os.path.exists(spec.watermark_path):
        raise HTTPException(status_code=400, detail=f"Watermark image not found: {spec.watermark_path}")

    service = ThumbnailAIService()

    # Start async job
    await _handle_blocking_job(job_id, service.generate_thumbnail, spec)

    return overlay_jobs[job_id]


@router.post("/thumbnail/auto-frame")
async def auto_frame(request: AutoFrameRequest = Body(...)):
    """
    Detect faces and compute optimal crop for target aspect ratio.
    Returns crop coordinates.
    """
    if not os.path.exists(request.image_path):
        raise HTTPException(status_code=400, detail=f"Image not found: {request.image_path}")

    service = ThumbnailAIService()

    try:
        result = service.auto_frame(request.image_path, request.target_aspect)
        return {
            "crop_x": result.crop_x,
            "crop_y": result.crop_y,
            "crop_width": result.crop_width,
            "crop_height": result.crop_height,
            "confidence": result.confidence,
            "face_boxes": result.face_boxes
        }
    except Exception as e:
        logger.error(f"Auto-frame failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/thumbnail/extract-frame")
async def extract_video_frame(request: VideoFrameExtractRequest = Body(...)):
    """
    Extract a frame from video at given timestamp.
    """
    if not os.path.exists(request.video_path):
        raise HTTPException(status_code=400, detail=f"Video not found: {request.video_path}")

    service = ThumbnailAIService()

    try:
        frame_path = service.extract_video_frame(request.video_path, request.timestamp)
        return {"frame_path": frame_path, "timestamp": request.timestamp}
    except Exception as e:
        logger.error(f"Frame extraction failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/thumbnail/episode-candidates")
async def generate_episode_thumbnails(request: EpisodeThumbnailsRequest = Body(...)):
    """
    Generate multiple thumbnail candidates from video.
    Extracts frames at specified timestamps and creates thumbnails.
    """
    if not os.path.exists(request.video_path):
        raise HTTPException(status_code=400, detail=f"Video not found: {request.video_path}")

    if request.watermark_path and not os.path.exists(request.watermark_path):
        raise HTTPException(status_code=400, detail=f"Watermark not found: {request.watermark_path}")

    service = ThumbnailAIService()

    try:
        thumbnails = service.generate_episode_thumbnails(
            video_path=request.video_path,
            episode_num=request.episode_num,
            title=request.title,
            subtitle=request.subtitle,
            watermark_path=request.watermark_path,
            timestamps=request.timestamps
        )
        return {"thumbnails": thumbnails, "count": len(thumbnails)}
    except Exception as e:
        logger.error(f"Episode thumbnail generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/video/watermark", response_model=JobStatusResponse)
async def add_watermark_to_video(request: WatermarkRequest = Body(...)):
    """
    Add watermark overlay to video.
    """
    job_id = str(uuid.uuid4())

    if not os.path.exists(request.input_video):
        raise HTTPException(status_code=400, detail=f"Input video not found: {request.input_video}")
    if not os.path.exists(request.watermark_path):
        raise HTTPException(status_code=400, detail=f"Watermark not found: {request.watermark_path}")

    service = OverlayService()

    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
        output_path = tmp.name

    # Start async job
    await _handle_blocking_job(
        job_id,
        service.add_watermark,
        request.input_video,
        request.watermark_path,
        request.position,
        request.opacity,
        request.margin,
        output_path
    )

    return overlay_jobs[job_id]


@router.post("/video/burn-subtitles", response_model=JobStatusResponse)
async def burn_subtitles(request: SubtitleBurnRequest = Body(...)):
    """
    Burn SRT subtitles into video.
    """
    job_id = str(uuid.uuid4())

    if not os.path.exists(request.input_video):
        raise HTTPException(status_code=400, detail=f"Input video not found: {request.input_video}")
    if not os.path.exists(request.srt_path):
        raise HTTPException(status_code=400, detail=f"SRT file not found: {request.srt_path}")
    if request.font_path and not os.path.exists(request.font_path):
        raise HTTPException(status_code=400, detail=f"Font file not found: {request.font_path}")

    service = OverlayService()

    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
        output_path = tmp.name

    # Start async job
    await _handle_blocking_job(
        job_id,
        service.burn_subtitles,
        request.input_video,
        request.srt_path,
        request.font_path,
        request.font_size,
        request.font_color,
        request.outline_color,
        request.outline_width,
        request.margin_v,
        output_path
    )

    return overlay_jobs[job_id]


@router.post("/video/graphic-overlay", response_model=JobStatusResponse)
async def add_graphic_overlay(request: GraphicOverlayRequest = Body(...)):
    """
    Add graphic overlay (logo, lower third, etc.) to video with timing and fade.
    """
    job_id = str(uuid.uuid4())

    if not os.path.exists(request.input_video):
        raise HTTPException(status_code=400, detail=f"Input video not found: {request.input_video}")
    if not os.path.exists(request.overlay_path):
        raise HTTPException(status_code=400, detail=f"Overlay image not found: {request.overlay_path}")

    service = OverlayService()

    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
        output_path = tmp.name

    # Start async job
    await _handle_blocking_job(
        job_id,
        service.add_graphic_overlay,
        request.input_video,
        request.overlay_path,
        request.start_time,
        request.duration,
        request.position,
        request.opacity,
        request.margin,
        request.fade_in,
        request.fade_out,
        output_path
    )

    return overlay_jobs[job_id]


@router.post("/graphics/lower-third")
async def create_lower_third(request: LowerThirdRequest = Body(...)):
    """
    Create a lower third graphic as PNG for overlay.
    """
    service = OverlayService()

    try:
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            output_path = tmp.name

        result_path = service.create_lower_third(
            text=request.text,
            name=request.name,
            role=request.role,
            width=request.width,
            height=request.height,
            bg_color=tuple(request.bg_color),
            text_color=tuple(request.text_color),
            accent_color=tuple(request.accent_color),
            font_path=request.font_path,
            output_path=output_path
        )

        return {"lower_third_path": result_path}
    except Exception as e:
        logger.error(f"Lower third creation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/job/{job_id}")
async def get_job_status(job_id: str):
    """Get status of an overlay job."""
    if job_id not in overlay_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return overlay_jobs[job_id]