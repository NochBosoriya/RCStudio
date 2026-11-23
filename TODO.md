# TODO: KhmerDub Studio Checklist

## PHASE 1: Project Scaffold, Config & Database Schema
- [x] Create root monorepo layout (`/backend`, `/frontend`, `/ai_training`, `/storage`).
- [x] Create `.env.example` (configurable `GEMINI_API_KEY`, `GEMINI_MODEL`, Azure, YouTube, TikTok, Facebook OAuth, `HONGGUO_CLI_PATH`).
- [x] Create `docker-compose.yml` + local one-click launchers (`start.bat` for Windows, `start.sh` for macOS/Linux).
- [x] Initialize `/backend` Python dependencies (`requirements.txt`), FastAPI app skeleton, and config loader (`config.py`).
- [x] Build SQLAlchemy 2.0 models (`models.py`) and Alembic setup:
  - `Project`, `MediaAsset`, `DownloadJob`
  - `TranscriptLine` (dual-track: `source_text`, `display_text`, `tts_segments` JSON, timestamps, `character_id`, `duration_fit_status`)
  - `CharacterProfile` (gender, age_group, role, voice_engine, voice_id, pitch, speed)
  - `EpisodeGlossary` (`source_term`, `policy`: `TRANSLATE | KEEP_ORIGINAL | ROMANIZE_EN`, `display_name`, `tts_phonetic_km`)
  - `ExportJob`, `PublishJob`
- [x] Verify Phase 1 (DB tables initialize cleanly on SQLite).

## PHASE 2: Backend Core, Tab 1 (Download Hub) & Tab 2 (Translate, Entity Glossary & Khmer Dubbing)
- [ ] Build WebSocket / SSE live job progress manager + background task runner (Celery/Redis with automatic local `APScheduler` + `Thread/ProcessPool` fallback so it runs in VS Code without Docker).
- [ ] Build **Tab 1 (`downloader_service.py` + router):**
  - Universal `yt-dlp` engine with format/metadata/thumbnail extraction and batch queue.
  - Pluggable `HongguoDownloaderAdapter` (wraps external CLI/API configured in settings; clean URL router between `yt-dlp` and Hongguo + local MP4 upload).
- [ ] Build **Tab 2 Audio & ASR (`dubbing_pipeline.py`):**
  - `Demucs (htdemucs)` vocal + background SFX separation (`vocals.wav` / `no_vocals.wav`).
  - Selectable transcription engines (`faster-whisper large-v3`, `SenseVoice-Small`, optional `PaddleOCR` burned-in subtitle extractor).
  - Selectable speaker & character detector (`pyannote/speaker-diarization-3.1` + Gemini role classifier, `SpeechBrain ECAPA-TDNN`, or local LLM classifier).
- [ ] Build **Entity Preservation & Mixed-Language Workflow (`entity_glossary_service.py`):**
  - Pre-translation episode glossary extractor using free Gemini Flash.
  - Token-locked translation guardrail (`[[ENT_01]]`) with regex verification & auto-retry so untranslatable names stay in English/original language in `display_text`.
  - Bulk glossary update endpoint ("Apply to All Lines").
- [ ] Build **Engine-Aware Khmer TTS Router (`tts_router.py`):**
  - Selectable engines: `Edge-TTS` (`km-KH-PisethNeural`, `km-KH-SreymomNeural` with pitch/rate presets), `Azure Neural` (SSML `<lang>` support), `F5-TTS Khmer`, and `MMS-TTS-KHM` (auto-reads `tts_phonetic_km` for locked foreign names).
  - Auto timing sync (`ffmpeg` / `rubberband` max `1.20x` stretch) + auto-ducking audio mix (-8dB SFX under dialogue).
- [ ] Verify Phase 2 (FastAPI `/docs` loads cleanly; unit tests pass for token-locked entity preservation and URL routing).

## PHASE 3: Backend Tab 3 (AI Thumbnail & Watermark), Tab 4 (Export & Splitter) & Tab 5 (Publish)
- [ ] Build **Tab 3 (`thumbnail_ai_service.py` + `overlay_service.py` + router):**
  - Free Hybrid Mode: Free Gemini Flash Vision extracts bounding boxes, original title, Khmer title (respecting `EpisodeGlossary`), and style JSON -> local `LaMa` inpainting erases original title -> headless Playwright/SVG renderer draws style-matched Khmer + English fallback title without manual font selection.
  - Optional Native Image-Edit Mode toggle (paid Gemini image-edit API).
  - FFmpeg watermark overlay (image/text, opacity, position, optional corner-bounce) + optional bottom subtitle mask + `libass` Khmer subtitle burn-in.
- [ ] Build **Tab 4 (`export_splitter_service.py` + router):**
  - Speed control (`0.5x–2.0x`) with pitch-preserved audio (`setpts` + `atempo`).
  - Equal-length splitter (by target duration with balanced equal parts OR exact N parts), keyframe-accurate cuts, optional `Part X` badge, and aspect ratio presets (`9:16`, `16:9`, `1:1`).
- [ ] Build **Tab 5 (`publish_service.py` + scheduler + router):**
  - OAuth 2.0 provider connectors: YouTube Data API v3, TikTok Content Posting API v2, Meta Graph API (Facebook Pages/Reels).
  - Immediate post, single scheduled post (`Asia/Phnom_Penh` default), and multi-part drip scheduler (e.g., 1 part every N hours).
  - Gemini caption & hashtag generator.
- [ ] Verify Phase 3 (FFmpeg command builders and scheduler unit tests pass).

## PHASE 4: Next.js Frontend Studio Workspace (All 5 Tabs)
- [ ] Initialize Next.js (App Router, TypeScript), Tailwind CSS, shadcn/ui, TanStack Query, typed API client, and WebSocket progress hook.
- [ ] Build dark-mode App Shell with persistent Project Sidebar and 5-tab navigation.
- [ ] Build **Tab 1 UI (Download Hub):** URL batch input, detected provider badge (`yt-dlp` / `Hongguo`), live progress bars, media inspector, "Send to Translate & Dub" button.
- [ ] Build **Tab 2 UI (Translate & Dub Studio):**
  - Model selector dropdowns (Transcription, Speaker Detection, Translation, Khmer Voice Engine).
  - Waveform timeline (`Wavesurfer.js`) + editable line-by-line table (`#`, timestamp, character badge, source text, Khmer `display_text`, duration fit warning, play original/dub, regenerate line).
  - Collapsible **Glossary & Names Drawer** (toggle `Keep Original` / `Romanize EN` / `Translate`, edit pronunciation override, test audio, apply to all lines).
- [ ] Build **Tab 3 UI (Overlay & AI Thumbnail Editor):** Interactive canvas for watermark placement & subtitle mask, AI Thumbnail mode toggle, before/after comparison slider, export button.
- [ ] Build **Tab 4 UI (Export & Equal Splitter):** Speed slider, split mode selector (`Target Length` vs `Number of Parts`), calculated part-duration preview list, batch export queue.
- [ ] Build **Tab 5 UI (Publish & Scheduler):** Connected platform accounts, immediate vs schedule/drip picker, AI caption generator, thumbnail attachment, and publishing calendar/queue with retry.
- [ ] Verify Phase 4 (`npm run build` succeeds with zero TypeScript errors).

## PHASE 5: AI Model Training Suite (`/ai_training`) & Final Integration
- [ ] Build Khmer TTS data prep pipeline (`prepare_khmer_tts_dataset.py`: Silero VAD, -23 LUFS normalization, Khmer Unicode normalization, number/loanword normalizer).
- [ ] Build fine-tuning & evaluation scripts: `train_f5_tts_khmer.py`, `train_mms_khmer.py`, `eval_tts.py`, and checkpoint exporter into `/backend/models/tts/`.
- [ ] Build speaker role classifier trainer (`train_speaker_role_classifier.py` with ONNX export) and Chinese-to-Khmer drama QLoRA trainer (`train_zh_km_lora.py`).
- [ ] Write root `README.md` with exact VS Code setup, local run commands, and training CLI commands.
- [ ] Run final end-to-end health check across Backend + Frontend.