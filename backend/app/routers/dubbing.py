from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from pydantic import BaseModel, HttpUrl
from typing import List, Optional
from sqlalchemy.orm import Session
import logging

from ..models import get_db, Project, TranscriptLine, CharacterProfile
from ..services.dubbing_pipeline import (
    DemucsSeparator, FasterWhisperEngine, SenseVoiceEngine,
    PyannoteDiarizer, SpeechBrainDiarizer, CharacterDetector,
    separate_vocals, transcribe_audio, diarize_speakers, detect_characters,
    SpeakerSegment, TranscriptionSegment
)
from ..config import settings

router = APIRouter(prefix="/api/dubbing", tags=["dubbing"])
logger = logging.getLogger(__name__)


class SeparateRequest(BaseModel):
    project_id: int
    audio_path: str


class TranscribeRequest(BaseModel):
    project_id: int
    audio_path: str
    engine: str = "faster-whisper"


class DiarizeRequest(BaseModel):
    project_id: int
    audio_path: str
    engine: str = "pyannote"


class CharacterDetectRequest(BaseModel):
    project_id: int
    speaker_segments: List[dict]
    transcript: List[dict]


def get_storage_path(project_id: int, subdir: str = "") -> str:
    """Get absolute storage path for a project."""
    base = Path(settings.storage_dir) / "projects" / str(project_id)
    if subdir:
        base = base / subdir
    base.mkdir(parents=True, exist_ok=True)
    return str(base)


from pathlib import Path


def run_background_task(func, *args, **kwargs):
    """Run a function in background with its own DB session."""
    from ..models import SessionLocal
    db = SessionLocal()
    try:
        func(db, *args, **kwargs)
    except Exception as e:
        logger.error(f"Background task failed: {e}", exc_info=True)
    finally:
        db.close()


def _run_separation(db: Session, project_id: int, audio_path: str):
    try:
        output_dir = get_storage_path(project_id, "audio")
        result = separate_vocals(audio_path, output_dir)
        # Store result in project metadata or a dedicated table
        project = db.query(Project).filter(Project.id == project_id).first()
        if project:
            if not project.asset_metadata:
                project.asset_metadata = {}
            project.asset_metadata["separated_audio"] = {
                "vocals": f"{output_dir}/vocals.wav",
                "accompaniment": f"{output_dir}/no_vocals.wav"
            }
            db.commit()
        logger.info(f"Separation completed for project {project_id}")
    except Exception as e:
        logger.error(f"Separation failed for project {project_id}: {e}", exc_info=True)


@router.post("/separate")
async def separate_audio(request: SeparateRequest, background_tasks: BackgroundTasks):
    """Separate vocals from background music/SFX."""
    db = next(get_db())
    try:
        project = db.query(Project).filter(Project.id == request.project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        background_tasks.add_task(run_background_task, _run_separation, request.project_id, request.audio_path)
        return {"status": "started", "message": "Vocal separation started"}
    finally:
        db.close()


def _run_transcription(db: Session, project_id: int, audio_path: str, engine: str):
    try:
        segments = transcribe_audio(audio_path, engine)
        for i, seg in enumerate(segments):
            line = TranscriptLine(
                project_id=project_id,
                source_text=seg['text'],
                display_text=seg['text'],
                start_time=seg['start'],
                end_time=seg['end'],
                duration_fit_status="pending"
            )
            db.add(line)
        db.commit()
        logger.info(f"Transcription completed for project {project_id}: {len(segments)} segments")
    except Exception as e:
        logger.error(f"Transcription failed for project {project_id}: {e}", exc_info=True)
        db.rollback()


@router.post("/transcribe")
async def transcribe(request: TranscribeRequest, background_tasks: BackgroundTasks):
    """Transcribe audio to text."""
    db = next(get_db())
    try:
        project = db.query(Project).filter(Project.id == request.project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        background_tasks.add_task(run_background_task, _run_transcription, request.project_id, request.audio_path, request.engine)
        return {"status": "started", "message": f"Transcription started with {request.engine}"}
    finally:
        db.close()


def _run_diarization(db: Session, project_id: int, audio_path: str, engine: str):
    try:
        segments = diarize_speakers(audio_path, engine)
        # Update transcript lines with speaker_id by matching timestamps
        lines = db.query(TranscriptLine).filter(TranscriptLine.project_id == project_id).all()
        for line in lines:
            for seg in segments:
                if seg['start'] <= line.start_time < seg['end']:
                    line.speaker_id = seg.get('speaker', 'unknown')
                    break
        db.commit()
        logger.info(f"Diarization completed for project {project_id}")
    except Exception as e:
        logger.error(f"Diarization failed for project {project_id}: {e}", exc_info=True)
        db.rollback()


@router.post("/diarize")
async def diarize(request: DiarizeRequest, background_tasks: BackgroundTasks):
    """Speaker diarization."""
    db = next(get_db())
    try:
        project = db.query(Project).filter(Project.id == request.project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        background_tasks.add_task(run_background_task, _run_diarization, request.project_id, request.audio_path, request.engine)
        return {"status": "started", "message": f"Diarization started with {request.engine}"}
    finally:
        db.close()


def _run_character_detection(db: Session, project_id: int, speaker_segments: List[dict], transcript: List[dict]):
    try:
        chars = detect_characters(
            [SpeakerSegment(**s) for s in speaker_segments],
            [TranscriptionSegment(**s) for s in transcript]
        )

        # Save character profiles - avoid duplicates by speaker_id
        for speaker_id, info in chars.items():
            existing = db.query(CharacterProfile).filter(
                CharacterProfile.project_id == project_id,
                CharacterProfile.name == speaker_id
            ).first()
            if existing:
                existing.gender = info.get('gender', 'unknown')
                existing.age_group = info.get('age_group', 'unknown')
                existing.role = info.get('role', 'unknown')
            else:
                profile = CharacterProfile(
                    project_id=project_id,
                    name=speaker_id,
                    gender=info.get('gender', 'unknown'),
                    age_group=info.get('age_group', 'unknown'),
                    role=info.get('role', 'unknown'),
                    voice_engine="edge-tts",
                    voice_id="km-KH-PisethNeural" if info.get('gender') == 'male' else "km-KH-SreymomNeural"
                )
                db.add(profile)
        db.commit()
        logger.info(f"Character detection completed for project {project_id}")
    except Exception as e:
        logger.error(f"Character detection failed for project {project_id}: {e}", exc_info=True)
        db.rollback()


@router.post("/detect-characters")
async def detect_chars(request: CharacterDetectRequest, background_tasks: BackgroundTasks):
    """Detect character roles from speakers."""
    db = next(get_db())
    try:
        project = db.query(Project).filter(Project.id == request.project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        background_tasks.add_task(run_background_task, _run_character_detection, request.project_id, request.speaker_segments, request.transcript)
        return {"status": "started", "message": "Character detection started"}
    finally:
        db.close()


@router.get("/project/{project_id}/lines")
async def get_transcript_lines(project_id: int, db: Session = Depends(get_db)):
    """Get all transcript lines for a project."""
    lines = db.query(TranscriptLine).filter(TranscriptLine.project_id == project_id).order_by(TranscriptLine.start_time).all()
    return [
        {
            "id": l.id,
            "source_text": l.source_text,
            "display_text": l.display_text,
            "tts_segments": l.tts_segments,
            "start_time": l.start_time,
            "end_time": l.end_time,
            "character_id": l.character_id,
            "duration_fit_status": l.duration_fit_status
        }
        for l in lines
    ]


@router.get("/project/{project_id}/characters")
async def get_characters(project_id: int, db: Session = Depends(get_db)):
    """Get all character profiles for a project."""
    chars = db.query(CharacterProfile).filter(CharacterProfile.project_id == project_id).all()
    return [
        {
            "id": c.id,
            "name": c.name,
            "gender": c.gender,
            "age_group": c.age_group,
            "role": c.role,
            "voice_engine": c.voice_engine,
            "voice_id": c.voice_id,
            "pitch": c.pitch,
            "speed": c.speed
        }
        for c in chars
    ]


# Fields that can be updated via the update endpoint
UPDATABLE_FIELDS = {
    "source_text", "display_text", "tts_segments",
    "character_id", "duration_fit_status"
}

@router.put("/line/{line_id}")
async def update_transcript_line(line_id: int, data: dict, db: Session = Depends(get_db)):
    """Update a transcript line (translation edit)."""
    line = db.query(TranscriptLine).filter(TranscriptLine.id == line_id).first()
    if not line:
        raise HTTPException(status_code=404, detail="Line not found")

    for key, value in data.items():
        if key in UPDATABLE_FIELDS and hasattr(line, key):
            setattr(line, key, value)
    db.commit()
    return {"status": "updated"}