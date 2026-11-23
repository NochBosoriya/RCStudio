import os
import json
import subprocess
import logging
import tempfile
import shutil
import sys
import re
from typing import List, Dict, Optional, Callable, Any
from dataclasses import dataclass, asdict
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class TranscriptionSegment:
    start: float
    end: float
    text: str
    speaker_id: Optional[str] = None
    confidence: float = 1.0


@dataclass
class SpeakerSegment:
    start: float
    end: float
    speaker_id: str
    gender: Optional[str] = None
    age_group: Optional[str] = None
    role: Optional[str] = None


class DemucsSeparator:
    """Vocal and background separation using Demucs htdemucs model."""

    def __init__(self, model: str = "htdemucs", device: str = "cpu"):
        self.model = model
        self.device = device

    def separate(self, input_path: str, output_dir: str,
                 progress_callback: Optional[Callable[[float, str], None]] = None) -> Dict[str, str]:
        """
        Separate audio into vocals and no_vocals (background music + SFX).
        Returns paths to vocals.wav and no_vocals.wav
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        if progress_callback:
            progress_callback(0.1, "Loading Demucs model...")

        # Use sys.executable to ensure venv python is used
        cmd = [
            sys.executable, "-m", "demucs.separate",
            "-n", self.model,
            "--device", self.device,
            "-o", str(output_path),
            "--two-stems", "vocals",
            input_path
        ]

        if progress_callback:
            progress_callback(0.3, "Running separation...")

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if result.returncode != 0:
                logger.error(f"Demucs failed: {result.stderr}")
                raise RuntimeError(f"Demucs separation failed: {result.stderr}")
        except subprocess.TimeoutExpired:
            raise RuntimeError("Demucs separation timed out")

        # Demucs outputs to output_path/model_name/input_stem.wav
        model_dir = output_path / self.model / Path(input_path).stem
        vocals_path = model_dir / "vocals.wav"
        no_vocals_path = model_dir / "no_vocals.wav"

        if progress_callback:
            progress_callback(1.0, "Separation complete")

        return {
            "vocals": str(vocals_path),
            "no_vocals": str(no_vocals_path)
        }


class TranscriptionEngine:
    """Base class for transcription engines."""

    def transcribe(self, audio_path: str,
                   progress_callback: Optional[Callable[[float, str], None]] = None) -> List[TranscriptionSegment]:
        raise NotImplementedError


class FasterWhisperEngine(TranscriptionEngine):
    """Transcription using faster-whisper large-v3."""

    def __init__(self, model_size: str = "large-v3", device: str = "cpu", compute_type: str = "int8"):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self._model = None

    def _get_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(self.model_size, device=self.device, compute_type=self.compute_type)
        return self._model

    def transcribe(self, audio_path: str,
                   progress_callback: Optional[Callable[[float, str], None]] = None) -> List[TranscriptionSegment]:
        model = self._get_model()

        if progress_callback:
            progress_callback(0.1, "Transcribing with faster-whisper...")

        segments, info = model.transcribe(audio_path, beam_size=5, vad_filter=True)

        # Collect all segments first to get total count for progress calculation
        segment_list = list(segments)
        total_segments = len(segment_list)

        results = []
        for i, seg in enumerate(segment_list):
            if progress_callback:
                # Fix: use total_segments instead of info.duration for progress
                progress_callback(0.1 + 0.8 * (i / max(1, total_segments)), f"Transcribing segment {i+1}/{total_segments}")
            results.append(TranscriptionSegment(
                start=seg.start,
                end=seg.end,
                text=seg.text.strip(),
                confidence=seg.avg_logprob if hasattr(seg, 'avg_logprob') else 1.0
            ))

        if progress_callback:
            progress_callback(1.0, "Transcription complete")
        return results


class SenseVoiceEngine(TranscriptionEngine):
    """Transcription using SenseVoice-Small (fast Chinese/multilingual)."""

    def __init__(self, model_path: str = "iic/SenseVoiceSmall", device: str = "cpu"):
        self.model_path = model_path
        self.device = device
        self._model = None
        self._available = True

    def _get_model(self):
        if self._model is None:
            try:
                from funasr import AutoModel
                self._model = AutoModel(model=self.model_path, device=self.device)
            except ImportError as e:
                logger.warning(f"SenseVoice unavailable: funasr not installed ({e}). Returning empty results.")
                self._available = False
                return None
        return self._model

    def transcribe(self, audio_path: str,
                   progress_callback: Optional[Callable[[float, str], None]] = None) -> List[TranscriptionSegment]:
        model = self._get_model()

        if not self._available or model is None:
            if progress_callback:
                progress_callback(1.0, "SenseVoice unavailable, returning empty results")
            return []

        if progress_callback:
            progress_callback(0.2, "Transcribing with SenseVoice...")

        res = model.generate(input=audio_path, batch_size_s=300)

        results = []
        for item in res:
            # SenseVoice returns rich format with timestamps
            for seg in item.get('segments', []):
                results.append(TranscriptionSegment(
                    start=seg['start'] / 1000.0,
                    end=seg['end'] / 1000.0,
                    text=seg['text'],
                    confidence=seg.get('confidence', 1.0)
                ))

        if progress_callback:
            progress_callback(1.0, "Transcription complete")
        return results


class PaddleOCREngine:
    """Burned-in subtitle extraction using PaddleOCR."""

    def __init__(self, lang: str = "ch"):
        self.lang = lang
        self._ocr = None
        self._available = True

    def _get_ocr(self):
        if self._ocr is None:
            try:
                from paddleocr import PaddleOCR
                self._ocr = PaddleOCR(use_angle_cls=True, lang=self.lang)
            except ImportError as e:
                logger.warning(f"PaddleOCR unavailable: paddleocr not installed ({e}). Returning empty results.")
                self._available = False
                return None
        return self._ocr

    def extract_subtitles(self, video_path: str,
                          interval: float = 1.0,
                          progress_callback: Optional[Callable[[float, str], None]] = None) -> List[TranscriptionSegment]:
        """Extract hardcoded subtitles from video frames."""
        ocr = self._get_ocr()

        if not self._available or ocr is None:
            if progress_callback:
                progress_callback(1.0, "PaddleOCR unavailable, returning empty results")
            return []

        try:
            import cv2
        except ImportError as e:
            logger.warning(f"OpenCV unavailable: cv2 not installed ({e}). Returning empty results.")
            if progress_callback:
                progress_callback(1.0, "OpenCV unavailable, returning empty results")
            return []

        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps

        results = []
        frame_interval = int(fps * interval)
        last_text = ""

        frame_count = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_count % frame_interval == 0:
                if progress_callback:
                    progress_callback(frame_count / total_frames, f"OCR frame {frame_count}/{total_frames}")

                # Crop bottom portion for subtitles
                h, w = frame.shape[:2]
                subtitle_region = frame[int(h * 0.75):, :]

                result = ocr.ocr(subtitle_region, cls=True)
                if result and result[0]:
                    texts = [line[1][0] for line in result[0] if line[1][1] > 0.5]
                    combined = " ".join(texts)
                    if combined != last_text and combined.strip():
                        timestamp = frame_count / fps
                        results.append(TranscriptionSegment(
                            start=timestamp - interval,
                            end=timestamp,
                            text=combined.strip()
                        ))
                        last_text = combined

            frame_count += 1

        cap.release()

        if progress_callback:
            progress_callback(1.0, "OCR extraction complete")
        return results


class SpeakerDiarizer:
    """Base class for speaker diarization."""

    def diarize(self, audio_path: str,
                progress_callback: Optional[Callable[[float, str], None]] = None) -> List[SpeakerSegment]:
        raise NotImplementedError


class PyannoteDiarizer(SpeakerDiarizer):
    """Speaker diarization using pyannote/speaker-diarization-3.1."""

    def __init__(self, auth_token: Optional[str] = None):
        self.auth_token = auth_token or os.getenv("HF_TOKEN")
        self._pipeline = None

    def _get_pipeline(self):
        if self._pipeline is None:
            if not self.auth_token:
                raise RuntimeError(
                    "Pyannote diarization requires HF_TOKEN. "
                    "Set HF_TOKEN environment variable or use 'speechbrain' engine instead."
                )
            from pyannote.audio import Pipeline
            self._pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                use_auth_token=self.auth_token
            )
        return self._pipeline

    def diarize(self, audio_path: str,
                progress_callback: Optional[Callable[[float, str], None]] = None) -> List[SpeakerSegment]:
        pipeline = self._get_pipeline()

        if progress_callback:
            progress_callback(0.2, "Running speaker diarization...")

        diarization = pipeline(audio_path)

        results = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            results.append(SpeakerSegment(
                start=turn.start,
                end=turn.end,
                speaker_id=speaker
            ))

        if progress_callback:
            progress_callback(1.0, "Diarization complete")
        return results


class SpeechBrainDiarizer(SpeakerDiarizer):
    """Speaker diarization using SpeechBrain ECAPA-TDNN."""

    def __init__(self):
        self._model = None
        self._torchaudio_available = True

    def _get_model(self):
        if self._model is None:
            try:
                from speechbrain.inference.speaker import EncoderClassifier
                self._model = EncoderClassifier.from_hparams(
                    source="speechbrain/spkrec-ecapa-voxceleb",
                    savedir="pretrained_models/spkrec-ecapa-voxceleb"
                )
            except ImportError as e:
                logger.warning(f"SpeechBrain unavailable: speechbrain not installed ({e}).")
                raise RuntimeError("SpeechBrain not installed. Install with: pip install speechbrain")
        return self._model

    def diarize(self, audio_path: str,
                progress_callback: Optional[Callable[[float, str], None]] = None) -> List[SpeakerSegment]:
        # This is a simplified version - full implementation would use
        # spectral clustering on embeddings
        model = self._get_model()

        if progress_callback:
            progress_callback(0.2, "Extracting speaker embeddings...")

        # Make torchaudio import optional with fallback
        try:
            import torchaudio
            waveform, sr = torchaudio.load(audio_path)
            duration = waveform.shape[1] / sr
        except ImportError:
            logger.warning("torchaudio not available, using fallback duration estimation")
            # Fallback: estimate duration from file size or use a default
            import os
            file_size = os.path.getsize(audio_path)
            # Rough estimate: 16-bit mono WAV at 16kHz = 32KB/sec
            duration = file_size / 32000
            self._torchaudio_available = False

        if progress_callback:
            progress_callback(1.0, "Diarization complete (single speaker fallback)")

        return [SpeakerSegment(start=0, end=duration, speaker_id="SPEAKER_00")]


class CharacterDetector:
    """Detect character roles (gender, age, role) from speaker segments + transcript."""

    def __init__(self, use_gemini: bool = True):
        self.use_gemini = use_gemini

    def detect(self, segments: List[SpeakerSegment], transcript: List[TranscriptionSegment],
               progress_callback: Optional[Callable[[float, str], None]] = None) -> Dict[str, Dict]:
        """
        Assign gender, age_group, role to each speaker_id.
        Returns: {speaker_id: {gender, age_group, role, confidence}}
        """
        if self.use_gemini:
            return self._detect_with_gemini(segments, transcript, progress_callback)
        return self._detect_local(segments, transcript)

    def _detect_with_gemini(self, segments: List[SpeakerSegment], transcript: List[TranscriptionSegment],
                            progress_callback: Optional[Callable[[float, str], None]] = None) -> Dict[str, Dict]:
        """Use Gemini to classify speaker roles from context."""
        try:
            import google.generativeai as genai
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                return self._detect_local(segments, transcript)

            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(os.getenv("GEMINI_MODEL", "gemini-1.5-flash"))

            # Build context from transcript
            speaker_texts = {}
            for seg in transcript:
                # Find matching speaker segment
                for spk in segments:
                    if spk.start <= seg.start < spk.end:
                        if spk.speaker_id not in speaker_texts:
                            speaker_texts[spk.speaker_id] = []
                        speaker_texts[spk.speaker_id].append(seg.text)
                        break

            context = "\n".join([
                f"{spk_id}: {' '.join(texts[:20])}"  # First 20 lines per speaker
                for spk_id, texts in speaker_texts.items()
            ])

            prompt = f"""Analyze these speakers from a Chinese drama and classify each:
{context}

For each speaker, determine:
1. Gender: male/female/unknown
2. Age group: young/middle/elderly/unknown
3. Role: lead/supporting/narrator/system/unknown

Return JSON: {{"SPEAKER_00": {{"gender": "...", "age_group": "...", "role": "...", "confidence": 0.9}}, ...}}"""

            if progress_callback:
                progress_callback(0.5, "Analyzing characters with Gemini...")

            response = model.generate_content(prompt)

            # Fix: Strip code fences before parsing JSON
            response_text = response.text.strip()
            # Remove triple backticks with optional language specifier
            if response_text.startswith("```"):
                # Remove first line if it's a code fence
                lines = response_text.split('\n')
                if lines[0].startswith("```"):
                    lines = lines[1:]
                # Remove last line if it's a code fence
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                response_text = '\n'.join(lines)

            return json.loads(response_text)
        except Exception as e:
            logger.error(f"Gemini character detection failed: {e}")
            return self._detect_local(segments, transcript)

    def _detect_local(self, segments: List[SpeakerSegment], transcript: List[TranscriptionSegment]) -> Dict[str, Dict]:
        """Local fallback: simple heuristic based on pitch/frequency."""
        results = {}
        for seg in segments:
            # Placeholder - in production would analyze pitch
            results[seg.speaker_id] = {
                "gender": "unknown",
                "age_group": "unknown",
                "role": "unknown",
                "confidence": 0.5
            }
        return results


def separate_vocals(input_path: str, output_dir: str, progress_callback=None):
    """Task wrapper for vocal separation."""
    separator = DemucsSeparator()
    return separator.separate(input_path, output_dir, progress_callback)


def transcribe_audio(audio_path: str, engine: str = "faster-whisper",
                     progress_callback=None) -> List[Dict]:
    """Task wrapper for transcription."""
    engines = {
        "faster-whisper": FasterWhisperEngine(),
        "sensevoice": SenseVoiceEngine(),
    }
    transcriber = engines.get(engine, FasterWhisperEngine())
    segments = transcriber.transcribe(audio_path, progress_callback)
    return [asdict(s) for s in segments]


def diarize_speakers(audio_path: str, engine: str = "speechbrain",
                     progress_callback=None) -> List[Dict]:
    """Task wrapper for speaker diarization."""
    engines = {
        "pyannote": PyannoteDiarizer(),
        "speechbrain": SpeechBrainDiarizer(),
    }
    diarizer = engines.get(engine, SpeechBrainDiarizer())
    segments = diarizer.diarize(audio_path, progress_callback)
    return [asdict(s) for s in segments]


def detect_characters(speaker_segments: List[Dict], transcript: List[Dict],
                      progress_callback=None) -> Dict:
    """Task wrapper for character detection."""
    detector = CharacterDetector()
    return detector.detect(
        [SpeakerSegment(**s) for s in speaker_segments],
        [TranscriptionSegment(**s) for s in transcript],
        progress_callback
    )