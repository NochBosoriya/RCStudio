import os
import json
import logging
import tempfile
import subprocess
from typing import List, Dict, Optional, Callable, Tuple
from dataclasses import dataclass
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ThumbnailSpec:
    """Specification for thumbnail generation."""
    width: int = 1280
    height: int = 720
    background_color: Tuple[int, int, int] = (0, 0, 0)
    title_text: str = ""
    subtitle_text: str = ""
    episode_number: Optional[int] = None
    watermark_path: Optional[str] = None
    watermark_opacity: float = 0.3
    watermark_position: str = "bottom-right"  # bottom-right, bottom-left, top-right, top-left, center
    font_path: Optional[str] = None
    title_font_size: int = 72
    subtitle_font_size: int = 36
    episode_font_size: int = 48
    text_color: Tuple[int, int, int] = (255, 255, 255)
    text_stroke_color: Tuple[int, int, int] = (0, 0, 0)
    text_stroke_width: int = 3
    background_image: Optional[str] = None
    background_blur: float = 0.0
    background_overlay_color: Tuple[int, int, int, int] = (0, 0, 0, 128)  # RGBA
    progress_callback: Optional[Callable[[float, str], None]] = None


@dataclass
class AutoFrameResult:
    """Result of auto-framing detection."""
    crop_x: int
    crop_y: int
    crop_width: int
    crop_height: int
    confidence: float
    face_boxes: List[Dict]  # [{"x": 0.5, "y": 0.5, "w": 0.3, "h": 0.3, "confidence": 0.9}]


class BaseImageService:
    """Base class with shared font handling."""

    def __init__(self):
        self._default_font_cache = {}  # size -> font

    def _get_default_font(self, size: int) -> ImageFont.FreeTypeFont:
        """Get default font, trying common Khmer-supporting fonts."""
        if size in self._default_font_cache:
            return self._default_font_cache[size]

        font_paths = [
            # Khmer fonts
            "/usr/share/fonts/truetype/khmer/KhmerOS.ttf",
            "/usr/share/fonts/truetype/khmer/KhmerOSsys.ttf",
            "C:/Windows/Fonts/KhmerOS.ttf",
            "C:/Windows/Fonts/KhmerUI.ttf",
            # Fallback fonts
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/segoeui.ttf",
        ]
        for path in font_paths:
            if os.path.exists(path):
                try:
                    font = ImageFont.truetype(path, size)
                    self._default_font_cache[size] = font
                    return font
                except Exception:
                    continue
        # Ultimate fallback - load_default() has no size, so create a dummy
        try:
            font = ImageFont.load_default()
            self._default_font_cache[size] = font
            return font
        except Exception:
            # Last resort: use a basic truetype if available
            raise RuntimeError(f"No usable font found for size {size}")


class ThumbnailAIService(BaseImageService):
    """
    AI-powered thumbnail generation with auto-framing, watermarking, and text overlay.
    Uses OpenCV for face detection and PIL for compositing.
    """

    def __init__(self):
        super().__init__()
        self._face_cascade = None

    def _get_face_cascade(self):
        """Lazy load OpenCV face detector (DNN-based YN model)."""
        if self._face_cascade is None:
            import cv2
            # OpenCV 5.x uses FaceDetectorYN (YuNet) instead of Haar cascades
            # Need to download the model file - use a simple path
            try:
                # Try to use built-in model path
                model_path = os.path.join(cv2.data.haarcascades, 'face_detection_yunet_2023mar.onnx')
                if os.path.exists(model_path):
                    self._face_cascade = cv2.FaceDetectorYN_create(
                        model_path, "", (320, 320), 0.9, 0.3, 5000
                    )
                else:
                    # Use score threshold, nms threshold, top_k
                    self._face_cascade = None  # Will use center crop fallback
            except Exception:
                self._face_cascade = None
        return self._face_cascade

    def auto_frame(self, image_path: str, target_aspect: float = 16/9,
                   progress_callback: Optional[Callable[[float, str], None]] = None) -> AutoFrameResult:
        """
        Detect faces and compute optimal crop for target aspect ratio.
        Returns crop coordinates in source image space.
        Uses OpenCV 5.x FaceDetectorYN (YuNet) for face detection.
        """
        import cv2

        if progress_callback:
            progress_callback(0.1, "Loading image for auto-framing...")

        img = cv2.imread(image_path)
        if img is None:
            raise ValueError(f"Could not load image: {image_path}")

        h, w = img.shape[:2]
        current_aspect = w / h

        if progress_callback:
            progress_callback(0.3, "Detecting faces...")

        # Use FaceDetectorYN for face detection (OpenCV 5.x)
        face_boxes = []
        detector = self._get_face_cascade()

        if detector is not None:
            # Set input size to image dimensions
            detector.setInputSize((w, h))
            _, faces = detector.detect(img)

            if faces is not None:
                for face in faces:
                    x, y, fw, fh = face[:4].astype(int)
                    conf = face[14] if len(face) > 14 else 0.9
                    face_boxes.append({
                        "x": (x + fw/2) / w,
                        "y": (y + fh/2) / h,
                        "w": fw / w,
                        "h": fh / h,
                        "confidence": float(conf)
                    })

        if progress_callback:
            progress_callback(0.6, "Computing optimal crop...")

        # Compute target crop dimensions
        if current_aspect > target_aspect:
            # Image is wider - crop width
            crop_h = h
            crop_w = int(h * target_aspect)
        else:
            # Image is taller - crop height
            crop_w = w
            crop_h = int(w / target_aspect)

        # If faces detected, center crop on face cluster
        if face_boxes:
            # Find center of all faces
            avg_x = sum(f["x"] for f in face_boxes) / len(face_boxes)
            avg_y = sum(f["y"] for f in face_boxes) / len(face_boxes)

            # Convert to pixel coordinates
            center_x = int(avg_x * w)
            center_y = int(avg_y * h)

            # Calculate crop top-left keeping center in frame
            crop_x = max(0, min(center_x - crop_w // 2, w - crop_w))
            crop_y = max(0, min(center_y - crop_h // 2, h - crop_h))

            confidence = min(1.0, len(face_boxes) * 0.3)  # More faces = higher confidence
        else:
            # Center crop
            crop_x = (w - crop_w) // 2
            crop_y = (h - crop_h) // 2
            confidence = 0.5

        if progress_callback:
            progress_callback(1.0, "Auto-framing complete")

        return AutoFrameResult(
            crop_x=crop_x,
            crop_y=crop_y,
            crop_width=crop_w,
            crop_height=crop_h,
            confidence=confidence,
            face_boxes=face_boxes
        )

    def generate_thumbnail(self, spec: ThumbnailSpec,
                           progress_callback: Optional[Callable[[float, str], None]] = None) -> str:
        """
        Generate a thumbnail image from spec.
        Returns path to generated thumbnail.
        """
        if progress_callback:
            progress_callback(0.1, "Starting thumbnail generation...")

        # Create base image
        if spec.background_image and os.path.exists(spec.background_image):
            # Load and crop/resize background
            bg = Image.open(spec.background_image).convert("RGBA")

            # Apply auto-framing if background is an image
            frame_result = self.auto_frame(spec.background_image,
                                           target_aspect=spec.width/spec.height)

            # Crop to detected region
            bg = bg.crop((
                frame_result.crop_x,
                frame_result.crop_y,
                frame_result.crop_x + frame_result.crop_width,
                frame_result.crop_y + frame_result.crop_height
            ))

            # Resize to target
            bg = bg.resize((spec.width, spec.height), Image.Resampling.LANCZOS)

            # Apply blur if requested
            if spec.background_blur > 0:
                bg = bg.filter(ImageFilter.GaussianBlur(radius=spec.background_blur))

            # Apply overlay
            if spec.background_overlay_color[3] > 0:
                overlay = Image.new("RGBA", (spec.width, spec.height),
                                   spec.background_overlay_color)
                bg = Image.alpha_composite(bg, overlay)
        else:
            # Solid color background
            bg = Image.new("RGBA", (spec.width, spec.height),
                          spec.background_color + (255,))

        if progress_callback:
            progress_callback(0.3, "Drawing text overlays...")

        draw = ImageDraw.Draw(bg)

        # Draw title
        if spec.title_text:
            font = self._get_default_font(spec.title_font_size)
            # Calculate text position (center horizontally, upper third vertically)
            bbox = draw.textbbox((0, 0), spec.title_text, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
            x = (spec.width - text_w) // 2
            y = spec.height // 4 - text_h // 2

            # Draw stroke
            for dx in range(-spec.text_stroke_width, spec.text_stroke_width + 1):
                for dy in range(-spec.text_stroke_width, spec.text_stroke_width + 1):
                    if dx != 0 or dy != 0:
                        draw.text((x + dx, y + dy), spec.title_text,
                                 font=font, fill=spec.text_stroke_color)
            # Draw main text
            draw.text((x, y), spec.title_text, font=font, fill=spec.text_color)

        # Draw episode number
        if spec.episode_number is not None:
            ep_text = f"ភាគទី {spec.episode_number}"
            font = self._get_default_font(spec.episode_font_size)
            bbox = draw.textbbox((0, 0), ep_text, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
            x = (spec.width - text_w) // 2
            y = spec.height // 2 - text_h // 2

            for dx in range(-spec.text_stroke_width, spec.text_stroke_width + 1):
                for dy in range(-spec.text_stroke_width, spec.text_stroke_width + 1):
                    if dx != 0 or dy != 0:
                        draw.text((x + dx, y + dy), ep_text,
                                 font=font, fill=spec.text_stroke_color)
            draw.text((x, y), ep_text, font=font, fill=spec.text_color)

        # Draw subtitle
        if spec.subtitle_text:
            font = self._get_default_font(spec.subtitle_font_size)
            bbox = draw.textbbox((0, 0), spec.subtitle_text, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
            x = (spec.width - text_w) // 2
            y = 3 * spec.height // 4 - text_h // 2

            for dx in range(-spec.text_stroke_width, spec.text_stroke_width + 1):
                for dy in range(-spec.text_stroke_width, spec.text_stroke_width + 1):
                    if dx != 0 or dy != 0:
                        draw.text((x + dx, y + dy), spec.subtitle_text,
                                 font=font, fill=spec.text_stroke_color)
            draw.text((x, y), spec.subtitle_text, font=font, fill=spec.text_color)

        if progress_callback:
            progress_callback(0.7, "Applying watermark...")

        # Apply watermark
        if spec.watermark_path and os.path.exists(spec.watermark_path):
            watermark = Image.open(spec.watermark_path).convert("RGBA")

            # Resize watermark to reasonable size (max 20% of width)
            max_w = int(spec.width * 0.2)
            max_h = int(spec.height * 0.2)
            watermark.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)

            # Adjust opacity
            if spec.watermark_opacity < 1.0:
                alpha = watermark.split()[-1]
                alpha = alpha.point(lambda p: int(p * spec.watermark_opacity))
                watermark.putalpha(alpha)

            # Calculate position
            wm_w, wm_h = watermark.size
            margin = 30
            if spec.watermark_position == "bottom-right":
                pos = (spec.width - wm_w - margin, spec.height - wm_h - margin)
            elif spec.watermark_position == "bottom-left":
                pos = (margin, spec.height - wm_h - margin)
            elif spec.watermark_position == "top-right":
                pos = (spec.width - wm_w - margin, margin)
            elif spec.watermark_position == "top-left":
                pos = (margin, margin)
            else:  # center
                pos = ((spec.width - wm_w) // 2, (spec.height - wm_h) // 2)

            # Composite watermark
            bg.paste(watermark, pos, watermark)

        if progress_callback:
            progress_callback(0.9, "Saving thumbnail...")

        # Save
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            output_path = tmp.name
        bg.convert("RGB").save(output_path, "PNG")  # PNG doesn't use quality param

        if progress_callback:
            progress_callback(1.0, "Thumbnail generation complete")

        return output_path

    def extract_video_frame(self, video_path: str, timestamp: float,
                            progress_callback: Optional[Callable[[float, str], None]] = None) -> str:
        """Extract a frame from video at given timestamp."""
        if progress_callback:
            progress_callback(0.1, "Extracting frame from video...")

        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
            output_path = tmp.name

        cmd = [
            'ffmpeg', '-y', '-ss', str(timestamp), '-i', video_path,
            '-vframes', '1', '-q:v', '2', output_path
        ]

        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg frame extraction failed: {result.stderr.decode()}")

        if progress_callback:
            progress_callback(1.0, "Frame extracted")

        return output_path

    def generate_episode_thumbnails(self, video_path: str, episode_num: int,
                                    title: str, subtitle: str = "",
                                    watermark_path: Optional[str] = None,
                                    timestamps: List[float] = None,
                                    progress_callback: Optional[Callable[[float, str], None]] = None) -> List[str]:
        """
        Generate multiple thumbnail candidates from video.
        Extracts frames at specified timestamps (or auto-distributed) and creates thumbnails.
        """
        if timestamps is None:
            # Auto-distribute: 25%, 50%, 75% of video duration
            import ffmpeg
            probe = ffmpeg.probe(video_path)
            duration = float(probe['format']['duration'])
            timestamps = [duration * 0.25, duration * 0.5, duration * 0.75]

        thumbnails = []
        for i, ts in enumerate(timestamps):
            if progress_callback:
                progress_callback(i / len(timestamps), f"Processing thumbnail {i+1}/{len(timestamps)}...")

            # Extract frame
            frame_path = self.extract_video_frame(video_path, ts)

            # Generate thumbnail
            spec = ThumbnailSpec(
                title_text=title,
                subtitle_text=subtitle,
                episode_number=episode_num,
                watermark_path=watermark_path,
                background_image=frame_path,
                background_overlay_color=(0, 0, 0, 160)
            )

            thumb_path = self.generate_thumbnail(spec)
            thumbnails.append(thumb_path)

            # Clean up frame
            os.unlink(frame_path)

        if progress_callback:
            progress_callback(1.0, f"Generated {len(thumbnails)} thumbnail candidates")

        return thumbnails


class OverlayService(BaseImageService):
    """
    Video overlay service for watermarks, burned-in subtitles, and graphic overlays.
    Uses FFmpeg filter_complex for efficient GPU-accelerated compositing.
    """

    def __init__(self):
        super().__init__()

    @staticmethod
    def _rgb_to_ass_color(rgb: Tuple[int, int, int]) -> str:
        """Convert RGB tuple to ASS color format (&HBBGGRR)."""
        r, g, b = rgb
        return f"&H{b:02X}{g:02X}{r:02X}"

    @staticmethod
    def _color_str_to_ass(color: str) -> str:
        """Convert color string (white, black, #RRGGBB, rgb(r,g,b)) to ASS format."""
        color = color.strip().lower()
        if color.startswith('#'):
            # Hex color
            hex_val = color[1:]
            if len(hex_val) == 6:
                r = int(hex_val[0:2], 16)
                g = int(hex_val[2:4], 16)
                b = int(hex_val[4:6], 16)
                return f"&H{b:02X}{g:02X}{r:02X}"
        elif color.startswith('rgb('):
            # rgb(r, g, b)
            import re
            match = re.match(r'rgb\((\d+),\s*(\d+),\s*(\d+)\)', color)
            if match:
                r, g, b = map(int, match.groups())
                return f"&H{b:02X}{g:02X}{r:02X}"
        # Named colors - map common ones
        named_colors = {
            'white': '&HFFFFFF',
            'black': '&H000000',
            'red': '&H0000FF',
            'green': '&H00FF00',
            'blue': '&HFF0000',
            'yellow': '&H00FFFF',
            'cyan': '&HFFFF00',
            'magenta': '&HFF00FF',
        }
        return named_colors.get(color, '&HFFFFFF')  # Default to white

    def add_watermark(self, input_video: str, watermark_path: str,
                      position: str = "bottom-right",
                      opacity: float = 0.5,
                      margin: int = 30,
                      output_path: Optional[str] = None,
                      progress_callback: Optional[Callable[[float, str], None]] = None) -> str:
        """
        Add watermark overlay to video.
        Position: bottom-right, bottom-left, top-right, top-left, center
        """
        if output_path is None:
            with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
                output_path = tmp.name

        if progress_callback:
            progress_callback(0.1, "Preparing watermark overlay...")

        # Build position expression
        pos_map = {
            "bottom-right": f"main_w-overlay_w-{margin}:main_h-overlay_h-{margin}",
            "bottom-left": f"{margin}:main_h-overlay_h-{margin}",
            "top-right": f"main_w-overlay_w-{margin}:{margin}",
            "top-left": f"{margin}:{margin}",
            "center": "(main_w-overlay_w)/2:(main_h-overlay_h)/2",
        }
        pos_expr = pos_map.get(position, pos_map["bottom-right"])

        # Build filter complex
        filter_complex = (
            f"[1:v]format=rgba,colorchannelmixer=aa={opacity}[wm];"
            f"[0:v][wm]overlay={pos_expr}[out]"
        )

        cmd = [
            'ffmpeg', '-y',
            '-i', input_video,
            '-i', watermark_path,
            '-filter_complex', filter_complex,
            '-map', '[out]', '-map', '0:a?',
            '-c:v', 'libx264', '-preset', 'medium', '-crf', '20',
            '-c:a', 'copy',
            output_path
        ]

        if progress_callback:
            progress_callback(0.3, "Applying watermark...")

        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            raise RuntimeError(f"Watermark overlay failed: {result.stderr.decode()}")

        if progress_callback:
            progress_callback(1.0, "Watermark applied")

        return output_path

    def burn_subtitles(self, input_video: str, srt_path: str,
                       font_path: Optional[str] = None,
                       font_size: int = 24,
                       font_color: str = "white",
                       outline_color: str = "black",
                       outline_width: int = 2,
                       margin_v: int = 50,
                       output_path: Optional[str] = None,
                       progress_callback: Optional[Callable[[float, str], None]] = None) -> str:
        """
        Burn SRT subtitles into video using FFmpeg subtitles filter.
        Supports Khmer fonts.
        """
        if output_path is None:
            with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
                output_path = tmp.name

        if progress_callback:
            progress_callback(0.1, "Preparing subtitle burn-in...")

        # Escape path for FFmpeg subtitles filter (Windows paths need special handling)
        srt_path_escaped = srt_path.replace('\\', '/').replace(':', '\\:')

        # Build subtitles filter
        sub_filter = f"subtitles='{srt_path_escaped}'"
        if font_path:
            font_dir = os.path.dirname(font_path).replace('\\', '/')
            font_file = os.path.basename(font_path)
            sub_filter += f":fontsdir='{font_dir}':fontfile='{font_file}'"

        # Convert colors to ASS format
        primary_colour = self._color_str_to_ass(font_color)
        outline_colour = self._color_str_to_ass(outline_color)

        sub_filter += f":force_style='FontSize={font_size},PrimaryColour={primary_colour},OutlineColour={outline_colour},Outline={outline_width},MarginV={margin_v}'"

        cmd = [
            'ffmpeg', '-y',
            '-i', input_video,
            '-vf', sub_filter,
            '-c:v', 'libx264', '-preset', 'medium', '-crf', '20',
            '-c:a', 'copy',
            output_path
        ]

        if progress_callback:
            progress_callback(0.3, "Burning subtitles...")

        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            raise RuntimeError(f"Subtitle burn-in failed: {result.stderr.decode()}")

        if progress_callback:
            progress_callback(1.0, "Subtitles burned in")

        return output_path

    def add_graphic_overlay(self, input_video: str, overlay_path: str,
                            start_time: float = 0,
                            duration: Optional[float] = None,
                            position: str = "bottom-right",
                            opacity: float = 1.0,
                            margin: int = 30,
                            fade_in: float = 0.5,
                            fade_out: float = 0.5,
                            output_path: Optional[str] = None,
                            progress_callback: Optional[Callable[[float, str], None]] = None) -> str:
        """
        Add a graphic overlay (logo, lower third, etc.) with optional timing and fade.
        """
        if output_path is None:
            with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
                output_path = tmp.name

        if progress_callback:
            progress_callback(0.1, "Preparing graphic overlay...")

        pos_map = {
            "bottom-right": f"main_w-overlay_w-{margin}:main_h-overlay_h-{margin}",
            "bottom-left": f"{margin}:main_h-overlay_h-{margin}",
            "top-right": f"main_w-overlay_w-{margin}:{margin}",
            "top-left": f"{margin}:{margin}",
            "center": "(main_w-overlay_w)/2:(main_h-overlay_h)/2",
        }
        pos_expr = pos_map.get(position, pos_map["bottom-right"])

        # Build filter with timing and fade
        overlay_filter = f"[1:v]format=rgba,colorchannelmixer=aa={opacity}"
        if fade_in > 0:
            overlay_filter += f",fade=t=in:st=0:d={fade_in}:alpha=1"
        if fade_out > 0 and duration:
            overlay_filter += f",fade=t=out:st={duration-fade_out}:d={fade_out}:alpha=1"
        overlay_filter += f"[ov];[0:v][ov]overlay={pos_expr}"
        if start_time > 0:
            overlay_filter += f":enable='between(t,{start_time}"
            if duration:
                overlay_filter += f",{start_time+duration}"
            overlay_filter += ")'"
        # Note: if start_time == 0, no enable filter is added (overlay shows entire video)

        cmd = [
            'ffmpeg', '-y',
            '-i', input_video,
            '-i', overlay_path,
            '-filter_complex', overlay_filter,
            '-c:v', 'libx264', '-preset', 'medium', '-crf', '20',
            '-c:a', 'copy',
            output_path
        ]

        if progress_callback:
            progress_callback(0.3, "Applying graphic overlay...")

        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            raise RuntimeError(f"Graphic overlay failed: {result.stderr.decode()}")

        if progress_callback:
            progress_callback(1.0, "Graphic overlay applied")

        return output_path

    def create_lower_third(self, text: str, name: str = "", role: str = "",
                           width: int = 1280, height: int = 200,
                           bg_color: Tuple[int, int, int, int] = (0, 0, 0, 200),
                           text_color: Tuple[int, int, int] = (255, 255, 255),
                           accent_color: Tuple[int, int, int] = (255, 200, 0),
                           font_path: Optional[str] = None,
                           output_path: Optional[str] = None) -> str:
        """
        Create a lower third graphic as PNG for overlay.
        """
        if output_path is None:
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                output_path = tmp.name

        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Background bar
        draw.rectangle([0, 0, width, height], fill=bg_color)

        # Accent line on left
        draw.rectangle([0, 0, 8, height], fill=accent_color + (255,))

        # Load fonts
        try:
            if font_path:
                name_font = ImageFont.truetype(font_path, 48)
                role_font = ImageFont.truetype(font_path, 28)
            else:
                name_font = self._get_default_font(48)
                role_font = self._get_default_font(28)
        except Exception:
            name_font = ImageFont.load_default()
            role_font = ImageFont.load_default()

        # Draw name
        if name:
            bbox = draw.textbbox((0, 0), name, font=name_font)
            text_w = bbox[2] - bbox[0]
            draw.text((20, 20), name, font=name_font, fill=text_color)

        # Draw role
        if role:
            y_offset = 80 if name else 20
            draw.text((20, y_offset), role, font=role_font, fill=accent_color)

        # Draw main text (title/description)
        if text:
            y_offset = 140 if (name or role) else 60
            draw.text((20, y_offset), text, font=role_font, fill=text_color)

        img.save(output_path, "PNG")
        return output_path


def generate_thumbnail_job(spec_dict: dict, progress_callback=None) -> str:
    """Celery task wrapper for thumbnail generation."""
    service = ThumbnailAIService()
    spec = ThumbnailSpec(**spec_dict)
    return service.generate_thumbnail(spec, progress_callback)


def burn_subtitles_job(input_video: str, srt_path: str, output_path: str,
                       font_path: str = None, font_size: int = 24,
                       progress_callback=None) -> str:
    """Celery task wrapper for subtitle burn-in."""
    service = OverlayService()
    return service.burn_subtitles(input_video, srt_path, font_path, font_size,
                                  output_path=output_path, progress_callback=progress_callback)


def add_watermark_job(input_video: str, watermark_path: str, output_path: str,
                      position: str = "bottom-right", opacity: float = 0.5,
                      progress_callback=None) -> str:
    """Celery task wrapper for watermark overlay."""
    service = OverlayService()
    return service.add_watermark(input_video, watermark_path, position, opacity,
                                 output_path=output_path, progress_callback=progress_callback)