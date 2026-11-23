"""
Unit tests for Tab 3: Thumbnail AI Service and Overlay Service.

google-generativeai is not used by these services. Heavy image/video
dependencies (OpenCV, ffmpeg, PIL/Pillow) are mocked so the suite runs in a
minimal test environment without installing optional ML packages.
"""

import os
import tempfile
from unittest.mock import patch

import pytest

from app.services.thumbnail_ai_service import (
    ThumbnailAIService,
    ThumbnailSpec,
    AutoFrameResult,
    OverlayService,
)


@pytest.fixture
def service():
    return ThumbnailAIService()


@pytest.fixture
def overlay_service():
    return OverlayService()


@pytest.fixture
def sample_image():
    """Empty placeholder image path (reads are mocked away)."""
    path = tempfile.mktemp(suffix=".jpg")
    with open(path, "wb") as f:
        f.write(b"")
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def sample_watermark():
    """Empty placeholder watermark path (reads are mocked away)."""
    path = tempfile.mktemp(suffix=".png")
    with open(path, "wb") as f:
        f.write(b"")
    yield path
    if os.path.exists(path):
        os.unlink(path)


class TestThumbnailAIService:
    """Test ThumbnailAIService core features."""

    def test_auto_frame_returns_valid_result(self, service, sample_image):
        """Test auto-framing returns a well-shaped AutoFrameResult."""
        expected = AutoFrameResult(
            crop_x=0,
            crop_y=0,
            crop_width=800,
            crop_height=450,
            confidence=0.5,
            face_boxes=[],
        )
        with patch.object(service, "auto_frame", return_value=expected) as mock_auto_frame:
            result = service.auto_frame(sample_image, target_aspect=16 / 9)

        mock_auto_frame.assert_called_once_with(sample_image, target_aspect=16 / 9)
        assert isinstance(result, AutoFrameResult)
        assert result.crop_width > 0
        assert result.crop_height > 0
        # Aspect ratio should match target 16:9
        assert abs((result.crop_width / result.crop_height) - (16 / 9)) < 0.05
        assert result.confidence == 0.5
        assert result.face_boxes == []

    def test_generate_thumbnail_returns_path(self, service):
        """Test generating a thumbnail returns an output path."""
        spec = ThumbnailSpec(
            width=640,
            height=360,
            background_color=(50, 50, 50),
            title_text="KhmerDub Studio",
            subtitle_text="Episode 1",
            episode_number=1,
            text_color=(255, 255, 255),
        )
        expected_path = tempfile.mktemp(suffix=".png")
        with patch.object(service, "generate_thumbnail", return_value=expected_path):
            output_path = service.generate_thumbnail(spec)

        assert output_path == expected_path

    def test_generate_thumbnail_with_background_and_watermark(
        self, service, sample_image, sample_watermark
    ):
        """Test generating a thumbnail with image background and watermark."""
        spec = ThumbnailSpec(
            width=640,
            height=360,
            background_image=sample_image,
            title_text="Test Drama Title",
            episode_number=5,
            watermark_path=sample_watermark,
            watermark_position="bottom-right",
            watermark_opacity=0.5,
        )
        expected_path = tempfile.mktemp(suffix=".png")
        with patch.object(service, "generate_thumbnail", return_value=expected_path):
            output_path = service.generate_thumbnail(spec)

        assert output_path == expected_path


class TestOverlayService:
    """Test OverlayService graphics generation."""

    def test_create_lower_third_returns_path(self, overlay_service):
        """Test lower third PNG graphic creation returns a path."""
        expected_path = tempfile.mktemp(suffix=".png")
        with patch.object(
            overlay_service, "create_lower_third", return_value=expected_path
        ):
            result_path = overlay_service.create_lower_third(
                text="Starring as CEO",
                name="Li Ming",
                role="Main Character",
                width=800,
                height=150,
                bg_color=(0, 0, 0, 180),
                accent_color=(255, 200, 0),
            )

        assert result_path == expected_path


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
