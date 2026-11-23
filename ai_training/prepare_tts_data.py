#!/usr/bin/env python3
"""
Khmer TTS Data Preparation Pipeline.
Prepares dual-track transcript segments and audio files for F5-TTS / MMS-TTS fine-tuning.
"""

import os
import json
import argparse
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def prepare_dataset(data_dir: str, output_dir: str):
    """
    Process transcript segments and audio clips into training manifests.
    """
    os.makedirs(output_dir, exist_ok=True)
    logger.info(f"Preparing dataset from {data_dir} -> {output_dir}")

    manifest = []

    # Example mock preparation logic
    sample_entry = {
        "audio_filepath": os.path.join(data_dir, "sample_01.wav"),
        "text": "ប្រធានក្រុមហ៊ុនមកដល់ហើយ",
        "speaker_id": "speaker_male_01",
        "duration": 3.45
    }
    manifest.append(sample_entry)

    manifest_path = os.path.join(output_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    logger.info(f"Dataset preparation complete. Manifest saved to {manifest_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Prepare Khmer TTS Training Data")
    parser.add_argument("--data-dir", default="./data", help="Input data directory")
    parser.add_argument("--output-dir", default="./processed_data", help="Output processed directory")
    args = parser.parse_args()

    prepare_dataset(args.data_dir, args.output_dir)
