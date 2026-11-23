import os
import logging
import tempfile
import subprocess
import json
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

@dataclass
class TTSSegment:
    text: str
    lang: str  # km, en, other
    phonetic_km: str
    speaker_id: Optional[str] = None

@dataclass
class TTSResult:
    audio_path: str
    duration: float
    segments: List[TTSSegment]

class TTSEngine:
    """Base class for TTS engines."""

    def synthesize(self, segments: List[TTSSegment], speaker_config: Dict,
                   progress_callback: Optional[Callable[[float, str], None]] = None) -> TTSResult:
        raise NotImplementedError

class EdgeTTSEngine(TTSEngine):
    """Edge-TTS Neural Khmer (free, default)."""

    def __init__(self):
        self._communicate = None

    def _get_communicate(self):
        if self._communicate is None:
            import edge_tts
            self._communicate = edge_tts.Communicate
        return self._communicate

    def synthesize(self, segments: List[TTSSegment], speaker_config: Dict,
                   progress_callback: Optional[Callable[[float, str], None]] = None) -> TTSResult:
        """
        Synthesize using Edge-TTS.
        For mixed-language: stitch Khmer/English clips with crossfade.
        """
        Communicate = self._get_communicate()

        voice_id = speaker_config.get('voice_id', 'km-KH-PisethNeural')
        pitch = speaker_config.get('pitch', 0)  # Hz
        rate = speaker_config.get('rate', 0)    # %

        # Build SSML for mixed language
        ssml_parts = []
        for seg in segments:
            if seg.lang == 'km':
                ssml_parts.append(f'<voice name="{voice_id}"><prosody pitch="{pitch}Hz" rate="{rate}%">{seg.text}</prosody></voice>')
            elif seg.lang == 'en':
                # Use English voice for English segments
                en_voice = speaker_config.get('en_voice_id', 'en-US-GuyNeural')
                ssml_parts.append(f'<voice name="{en_voice}"><prosody pitch="{pitch}Hz" rate="{rate}%">{seg.text}</prosody></voice>')
            else:
                ssml_parts.append(f'<voice name="{voice_id}"><prosody pitch="{pitch}Hz" rate="{rate}%">{seg.phonetic_km or seg.text}</prosody></voice>')

        ssml = f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="km-KH">{"".join(ssml_parts)}</speak>'

        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp:
            output_path = tmp.name

        if progress_callback:
            progress_callback(0.3, "Synthesizing with Edge-TTS...")

        import asyncio
        async def _synthesize():
            communicate = Communicate(ssml, voice_id)
            await communicate.save(output_path)

        asyncio.run(_synthesize())

        if progress_callback:
            progress_callback(1.0, "Edge-TTS synthesis complete")

        # Get duration
        import ffmpeg
        probe = ffmpeg.probe(output_path)
        duration = float(probe['format']['duration'])

        return TTSResult(audio_path=output_path, duration=duration, segments=segments)

class AzureTTSEngine(TTSEngine):
    """Azure Cognitive Services Neural Khmer with SSML <lang> support."""

    def __init__(self, api_key: Optional[str] = None, region: Optional[str] = None):
        self.api_key = api_key or os.getenv("AZURE_SPEECH_KEY")
        self.region = region or os.getenv("AZURE_SPEECH_REGION")
        self._synthesizer = None

    def _get_synthesizer(self):
        if self._synthesizer is None and self.api_key:
            import azure.cognitiveservices.speech as speechsdk
            speech_config = speechsdk.SpeechConfig(subscription=self.api_key, region=self.region)
            speech_config.speech_synthesis_voice_name = "km-KH-PisethNeural"
            self._synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)
        return self._synthesizer

    def synthesize(self, segments: List[TTSSegment], speaker_config: Dict,
                   progress_callback: Optional[Callable[[float, str], None]] = None) -> TTSResult:
        synthesizer = self._get_synthesizer()
        if not synthesizer:
            raise RuntimeError("Azure TTS not configured")

        voice_id = speaker_config.get('voice_id', 'km-KH-PisethNeural')

        # Build SSML with <lang> tags for mixed language
        ssml_parts = ['<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="km-KH">']

        for seg in segments:
            if seg.lang == 'km':
                ssml_parts.append(f'<voice name="{voice_id}">{seg.text}</voice>')
            elif seg.lang == 'en':
                ssml_parts.append(f'<voice name="{voice_id}"><lang xml:lang="en-US">{seg.text}</lang></voice>')
            else:
                ssml_parts.append(f'<voice name="{voice_id}">{seg.phonetic_km or seg.text}</voice>')

        ssml_parts.append('</speak>')
        ssml = "".join(ssml_parts)

        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
            output_path = tmp.name

        if progress_callback:
            progress_callback(0.3, "Synthesizing with Azure TTS...")

        import azure.cognitiveservices.speech as speechsdk
        audio_config = speechsdk.audio.AudioOutputConfig(filename=output_path)
        synth = speechsdk.SpeechSynthesizer(
            speech_config=synthesizer.speech_config,
            audio_config=audio_config
        )
        result = synth.speak_ssml_async(ssml).get()

        if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
            raise RuntimeError(f"Azure TTS failed: {result.cancellation_details.error_details}")

        if progress_callback:
            progress_callback(1.0, "Azure TTS synthesis complete")

        import ffmpeg
        probe = ffmpeg.probe(output_path)
        duration = float(probe['format']['duration'])

        return TTSResult(audio_path=output_path, duration=duration, segments=segments)

class F5TTSEngine(TTSEngine):
    """Local F5-TTS Khmer zero-shot voice cloning."""

    def __init__(self, model_path: Optional[str] = None):
        self.model_path = model_path or "./models/tts/f5-tts-khmer"
        self._model = None

    def _get_model(self):
        if self._model is None:
            # Placeholder for F5-TTS loading
            # from f5_tts.infer import Infer
            # self._model = Infer(model_path=self.model_path)
            pass
        return self._model

    def synthesize(self, segments: List[TTSSegment], speaker_config: Dict,
                   progress_callback: Optional[Callable[[float, str], None]] = None) -> TTSResult:
        """
        Synthesize using F5-TTS.
        For non-Khmer segments: use phonetic_km fallback or cross-lingual splicing.
        """
        model = self._get_model()
        if not model:
            # Fallback to Edge-TTS if model not available
            logger.warning("F5-TTS model not loaded, falling back to Edge-TTS")
            return EdgeTTSEngine().synthesize(segments, speaker_config, progress_callback)

        ref_audio = speaker_config.get('reference_audio')  # 5-10s reference clip

        if progress_callback:
            progress_callback(0.3, "Synthesizing with F5-TTS...")

        # Process each segment
        output_files = []
        for i, seg in enumerate(segments):
            text = seg.text if seg.lang == 'km' else (seg.phonetic_km or seg.text)

            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
                out_path = tmp.name

            # model.infer(ref_audio, text, out_path)
            output_files.append(out_path)

            if progress_callback:
                progress_callback(0.3 + 0.6 * (i / len(segments)), f"Segment {i+1}/{len(segments)}")

        # Concatenate
        final_path = self._concatenate_audio(output_files)

        if progress_callback:
            progress_callback(1.0, "F5-TTS synthesis complete")

        import ffmpeg
        probe = ffmpeg.probe(final_path)
        duration = float(probe['format']['duration'])

        return TTSResult(audio_path=final_path, duration=duration, segments=segments)

    def _concatenate_audio(self, files: List[str]) -> str:
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
            output = tmp.name

        # Use ffmpeg concat
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            for file in files:
                f.write(f"file '{file}'\n")
            list_file = f.name

        subprocess.run([
            'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', list_file,
            '-c', 'copy', output
        ], capture_output=True)

        return output

class MMSTTSEngine(TTSEngine):
    """Local Meta MMS (facebook/mms-tts-khm) lightweight VITS model."""

    def __init__(self, model_id: str = "facebook/mms-tts-khm"):
        self.model_id = model_id
        self._model = None
        self._tokenizer = None

    def _get_model(self):
        if self._model is None:
            from transformers import VitsModel, AutoTokenizer
            self._model = VitsModel.from_pretrained(self.model_id)
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_id)
        return self._model, self._tokenizer

    def synthesize(self, segments: List[TTSSegment], speaker_config: Dict,
                   progress_callback: Optional[Callable[[float, str], None]] = None) -> TTSResult:
        """
        Synthesize using MMS-TTS-KHM.
        Only supports Khmer - non-Khmer segments use phonetic_km.
        """
        model, tokenizer = self._get_model()
        if not model:
            raise RuntimeError("MMS-TTS model not loaded")

        if progress_callback:
            progress_callback(0.3, "Synthesizing with MMS-TTS...")

        output_files = []
        for i, seg in enumerate(segments):
            text = seg.text if seg.lang == 'km' else (seg.phonetic_km or seg.text)

            inputs = tokenizer(text, return_tensors="pt")
            with torch.no_grad():
                output = model(**inputs).waveform

            import torchaudio
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
                out_path = tmp.name
            torchaudio.save(out_path, output, model.config.sampling_rate)
            output_files.append(out_path)

            if progress_callback:
                progress_callback(0.3 + 0.6 * (i / len(segments)), f"Segment {i+1}/{len(segments)}")

        # Concatenate
        final_path = self._concatenate_audio(output_files)

        if progress_callback:
            progress_callback(1.0, "MMS-TTS synthesis complete")

        import ffmpeg
        probe = ffmpeg.probe(final_path)
        duration = float(probe['format']['duration'])

        return TTSResult(audio_path=final_path, duration=duration, segments=segments)

    def _concatenate_audio(self, files: List[str]) -> str:
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
            output = tmp.name

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            for file in files:
                f.write(f"file '{file}'\n")
            list_file = f.name

        subprocess.run([
            'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', list_file,
            '-c', 'copy', output
        ], capture_output=True)

        return output

class TTSRouter:
    """
    Engine-aware Khmer TTS router.
    Selects appropriate engine and handles mixed-language segments.
    """

    ENGINES = {
        'edge-tts': EdgeTTSEngine,
        'azure': AzureTTSEngine,
        'f5-tts': F5TTSEngine,
        'mms-tts': MMSTTSEngine,
    }

    def __init__(self, default_engine: str = 'edge-tts'):
        self.default_engine = default_engine
        self._engines = {}

    def get_engine(self, engine_name: str) -> TTSEngine:
        if engine_name not in self._engines:
            engine_class = self.ENGINES.get(engine_name)
            if not engine_class:
                raise ValueError(f"Unknown TTS engine: {engine_name}")
            self._engines[engine_name] = engine_class()
        return self._engines[engine_name]

    def synthesize(self, segments: List[Dict], speaker_config: Dict,
                   engine: Optional[str] = None,
                   progress_callback: Optional[Callable[[float, str], None]] = None) -> TTSResult:
        """
        Main synthesis entry point.
        segments: [{"text": "...", "lang": "km|en|other", "phonetic_km": "..."}]
        speaker_config: {voice_id, pitch, rate, reference_audio, en_voice_id}
        """
        engine_name = engine or self.default_engine
        engine = self.get_engine(engine_name)

        tts_segments = [TTSSegment(**s) for s in segments]

        return engine.synthesize(tts_segments, speaker_config, progress_callback)

    def auto_timing_sync(self, tts_audio: str, target_duration: float,
                         max_stretch: float = 1.2,
                         progress_callback: Optional[Callable[[float, str], None]] = None) -> str:
        """
        Time-stretch or trim TTS audio to fit target duration.
        Uses ffmpeg rubberband for pitch-preserved stretching (max 1.20x).
        """
        import ffmpeg

        probe = ffmpeg.probe(tts_audio)
        current_duration = float(probe['format']['duration'])

        ratio = target_duration / current_duration

        if ratio > max_stretch:
            # Too long - need to trim/speed up more aggressively
            ratio = max_stretch
            logger.warning(f"Target duration requires {target_duration/current_duration:.2f}x stretch, capped at {max_stretch}x")

        if abs(ratio - 1.0) < 0.02:
            # Close enough, no processing needed
            return tts_audio

        if progress_callback:
            progress_callback(0.2, f"Time-stretching audio ({ratio:.2f}x)...")

        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
            output_path = tmp.name

        if ratio > 1.0:
            # Stretch (slow down) - use rubberband
            cmd = [
                'ffmpeg', '-y', '-i', tts_audio,
                '-af', f'rubberband=tempo={1/ratio:.4f}',
                output_path
            ]
        else:
            # Speed up - use atempo (chained for >2x)
            atempo_chain = []
            remaining = 1/ratio
            while remaining > 2.0:
                atempo_chain.append('atempo=2.0')
                remaining /= 2.0
            atempo_chain.append(f'atempo={remaining:.4f}')
            cmd = [
                'ffmpeg', '-y', '-i', tts_audio,
                '-af', ','.join(atempo_chain),
                output_path
            ]

        subprocess.run(cmd, capture_output=True)

        if progress_callback:
            progress_callback(1.0, "Time-sync complete")

        return output_path

    def mix_with_background(self, dubbed_audio: str, background_audio: str,
                            duck_db: float = -8.0,
                            progress_callback: Optional[Callable[[float, str], None]] = None) -> str:
        """
        Mix dubbed audio with background (no_vocals.wav).
        Duck background by duck_db during speech.
        """
        import ffmpeg

        if progress_callback:
            progress_callback(0.2, "Mixing dubbed audio with background...")

        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
            output_path = tmp.name

        # Use ffmpeg sidechain compression for ducking
        cmd = [
            'ffmpeg', '-y',
            '-i', background_audio,  # [0] background
            '-i', dubbed_audio,       # [1] dubbed
            '-filter_complex',
            f'[0:a][1:a]sidechaincompress=threshold=0.003:ratio=20:attack=5:release=50:makeup={abs(duck_db)}[out]',
            '-map', '[out]',
            output_path
        ]

        subprocess.run(cmd, capture_output=True)

        if progress_callback:
            progress_callback(1.0, "Audio mixing complete")

        return output_path

def synthesize_tts_job(segments: List[Dict], speaker_config: Dict, engine: str = 'edge-tts',
                       progress_callback=None):
    """Celery task wrapper for TTS synthesis."""
    router = TTSRouter()
    result = router.synthesize(segments, speaker_config, engine, progress_callback)
    return {"audio_path": result.audio_path, "duration": result.duration}

def auto_sync_job(tts_audio: str, target_duration: float, progress_callback=None):
    """Celery task wrapper for auto timing sync."""
    router = TTSRouter()
    synced = router.auto_timing_sync(tts_audio, target_duration, progress_callback=progress_callback)
    return {"audio_path": synced}

def mix_audio_job(dubbed_audio: str, background_audio: str, progress_callback=None):
    """Celery task wrapper for audio mixing."""
    router = TTSRouter()
    mixed = router.mix_with_background(dubbed_audio, background_audio, progress_callback=progress_callback)
    return {"audio_path": mixed}

import torch