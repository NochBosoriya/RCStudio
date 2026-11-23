# KhmerDub Studio AI Training Suite

Tools and pipelines for training and fine-tuning Khmer-language voice and translation models.

## Structure
- `prepare_tts_data.py`: Prepares transcriptions and audio segments for training.
- `train_f5_tts.py`: Flow Matching fine-tuning pipeline for high-fidelity Khmer TTS.
- `train_translation_qlora.py`: (Stub) QLoRA training for Chinese-to-Khmer specialized translation.

## Prerequisites
- `pip install -r requirements.txt` (includes PyTorch, transformers, accelerate, peft)
- GPU with 16GB+ VRAM recommended for fine-tuning.

## Getting Started
1. **Prepare Data**: `python prepare_tts_data.py --data-dir ./raw_audio --output-dir ./processed_data`
2. **Train TTS**: `python train_f5_tts.py --manifest ./processed_data/manifest.json --epochs 5`
