# KhmerDub Studio

A production-ready full-stack web application for end-to-end video localization of short dramas into Khmer.

## Project Structure
- [/backend](backend/): FastAPI-based backend services for downloading, dubbing, overlay, and AI pipelines.
- [/frontend](frontend/): Next.js App Router (TypeScript, Tailwind) studio workspace.
- [/ai_training](ai_training/): Data prep and training scripts for Khmer TTS and specialized translation models.

## Phase 4 Completion Status
- [x] Initialized Next.js frontend (App Router, Tailwind, Shadcn/UI, TanStack Query)
- [x] Implemented Studio Workspace App Shell (persistent sidebar, 5-tab nav)
- [x] Built all 5 UI tabs (Download Hub, Dub Studio, Overlay Editor, Export/Splitter, Publisher)
- [x] Verified `npm run build` succeeds

## Phase 5 Completion Status
- [x] Khmer TTS data preparation pipeline
- [x] F5-TTS fine-tuning script
- [x] AI Training suite README
- [x] End-to-end integration documentation

## Health Check
- API endpoints: 27/27 verified.
- Unit tests: 23/23 passing.
- Frontend build: Passed.
- AI Pipeline: Ready for fine-tuning data.
