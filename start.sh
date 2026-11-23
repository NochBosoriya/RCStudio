#!/bin/bash
echo "Starting KhmerDub Studio..."
python3 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.app.main:app --reload --port 8000 &
cd frontend && npm run dev
