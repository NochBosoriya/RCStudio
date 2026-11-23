import os
import json
import subprocess
import logging
import uuid
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass
from pathlib import Path
import yt_dlp

logger = logging.getLogger(__name__)


@dataclass
class VideoFormat:
    format_id: str
    ext: str
    resolution: str
    fps: Optional[float]
    vcodec: str
    acodec: str
    filesize: Optional[int]


@dataclass
class MediaInfo:
    id: str
    title: str
    duration: float
    width: int
    height: int
    fps: float
    formats: List[VideoFormat]
    thumbnail_url: Optional[str]
    subtitles: Dict[str, List[Dict]]  # yt-dlp returns dict of lang->list
    filepath: Optional[str] = None


class YTDLPDownloader:
    """Universal downloader using yt-dlp for all supported platforms."""

    def __init__(self, output_dir: str = "./storage/downloads"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def extract_info(self, url: str) -> MediaInfo:
        """Extract video info without downloading."""
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return self._parse_info(info)

    def download(self, url: str, format_id: Optional[str] = None,
                 progress_callback: Optional[Callable[[float, str], None]] = None,
                 output_dir: Optional[str] = None) -> MediaInfo:
        """Download video with optional format selection."""

        def progress_hook(d):
            if progress_callback and d['status'] == 'downloading':
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                if total > 0:
                    progress = d['downloaded_bytes'] / total
                    progress_callback(progress, f"Downloading: {d['_percent_str']}")
            elif progress_callback and d['status'] == 'finished':
                progress_callback(1.0, "Download complete, processing...")

        # Use custom output dir if provided
        outtmpl = str((Path(output_dir) if output_dir else self.output_dir) / '%(id)s.%(ext)s')

        ydl_opts = {
            'format': format_id or 'bestvideo+bestaudio/best',
            'outtmpl': outtmpl,
            'progress_hooks': [progress_hook],
            'writethumbnail': True,
            'writesubtitles': True,
            'writeautomaticsub': False,
            'subtitleslangs': ['en', 'zh', 'km'],
            'merge_output_format': 'mp4',
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            media_info = self._parse_info(info)
            # prepare_filename returns pre-merge path; we need post-merge path
            # After merge, the file will have .mp4 extension (merge_output_format)
            filepath = ydl.prepare_filename(info)
            # If merged to mp4, adjust extension
            if ydl_opts.get('merge_output_format') == 'mp4':
                filepath = str(Path(filepath).with_suffix('.mp4'))
            media_info.filepath = filepath
            return media_info

    def _parse_info(self, info: Dict) -> MediaInfo:
        formats = []
        for f in info.get('formats', []):
            if f.get('vcodec') != 'none' or f.get('acodec') != 'none':
                formats.append(VideoFormat(
                    format_id=f.get('format_id', ''),
                    ext=f.get('ext', ''),
                    resolution=f.get('resolution', ''),
                    fps=f.get('fps'),
                    vcodec=f.get('vcodec', ''),
                    acodec=f.get('acodec', ''),
                    filesize=f.get('filesize')
                ))

        # subtitles is a dict mapping language -> list of subtitle dicts
        subtitles = info.get('subtitles', {}) or {}
        auto_subs = info.get('automatic_captions', {}) or {}
        all_subs = {**subtitles, **auto_subs}

        return MediaInfo(
            id=info.get('id', ''),
            title=info.get('title', ''),
            duration=info.get('duration', 0),
            width=info.get('width', 0),
            height=info.get('height', 0),
            fps=info.get('fps', 0),
            formats=formats,
            thumbnail_url=info.get('thumbnail'),
            subtitles=all_subs
        )


class HongguoDownloaderAdapter:
    """
    Pluggable adapter for Hongguo short drama downloader.
    Wraps external CLI binary or API endpoint configured via settings.
    """

    def __init__(self, cli_path: Optional[str] = None, api_endpoint: Optional[str] = None):
        self.cli_path = cli_path or os.getenv("HONGGUO_CLI_PATH", "./bin/hongguo-downloader")
        self.api_endpoint = api_endpoint

    def is_available(self) -> bool:
        """Check if Hongguo downloader is available."""
        if self.api_endpoint:
            return True
        return Path(self.cli_path).exists()

    def parse_drama_link(self, url: str) -> Dict:
        """Parse a Hongguo drama share link to get episode list."""
        if self.api_endpoint:
            return self._api_parse(url)
        return self._cli_parse(url)

    def _cli_parse(self, url: str) -> Dict:
        """Parse using CLI binary."""
        if not self.is_available():
            logger.warning(f"Hongguo CLI not found at {self.cli_path}, skipping")
            return {"episodes": []}

        try:
            result = subprocess.run(
                [self.cli_path, 'parse', url],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                return json.loads(result.stdout)
            logger.error(f"Hongguo CLI parse failed: {result.stderr}")
        except Exception as e:
            logger.error(f"Hongguo CLI error: {e}")
        return {"episodes": []}

    def _api_parse(self, url: str) -> Dict:
        """Parse using API endpoint."""
        import requests
        try:
            resp = requests.post(f"{self.api_endpoint}/parse", json={"url": url}, timeout=30)
            return resp.json()
        except Exception as e:
            logger.error(f"Hongguo API error: {e}")
        return {"episodes": []}

    def download_episodes(self, episode_urls: List[str], output_dir: str,
                          progress_callback: Optional[Callable[[float, str], None]] = None) -> List[MediaInfo]:
        """Download multiple episodes."""
        results = []
        for i, url in enumerate(episode_urls):
            if progress_callback:
                progress_callback(i / len(episode_urls), f"Downloading episode {i+1}/{len(episode_urls)}")

            if self.api_endpoint:
                info = self._api_download(url, output_dir)
            else:
                info = self._cli_download(url, output_dir)

            if info:
                results.append(info)

        if progress_callback:
            progress_callback(1.0, "All episodes downloaded")
        return results

    def _cli_download(self, url: str, output_dir: str) -> Optional[MediaInfo]:
        if not self.is_available():
            logger.warning(f"Hongguo CLI not found at {self.cli_path}, skipping download")
            return None

        try:
            result = subprocess.run(
                [self.cli_path, 'download', url, '--output', output_dir],
                capture_output=True, text=True, timeout=300
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                return MediaInfo(
                    id=data.get('id', ''),
                    title=data.get('title', ''),
                    duration=data.get('duration', 0),
                    width=data.get('width', 0),
                    height=data.get('height', 0),
                    fps=data.get('fps', 0),
                    formats=[],
                    thumbnail_url=data.get('thumbnail'),
                    subtitles={},
                    filepath=data.get('filepath')
                )
        except Exception as e:
            logger.error(f"Hongguo CLI download error: {e}")
        return None

    def _api_download(self, url: str, output_dir: str) -> Optional[MediaInfo]:
        import requests
        try:
            resp = requests.post(f"{self.api_endpoint}/download",
                               json={"url": url, "output_dir": output_dir}, timeout=300)
            data = resp.json()
            return MediaInfo(
                id=data.get('id', ''),
                title=data.get('title', ''),
                duration=data.get('duration', 0),
                width=data.get('width', 0),
                height=data.get('height', 0),
                fps=data.get('fps', 0),
                formats=[],
                thumbnail_url=data.get('thumbnail'),
                subtitles={},
                filepath=data.get('filepath')
            )
        except Exception as e:
            logger.error(f"Hongguo API download error: {e}")
        return None


class DownloadManager:
    """Orchestrates downloads from multiple sources."""

    def __init__(self, storage_dir: str = "./storage"):
        self.storage_dir = Path(storage_dir)
        self.yt_dlp = YTDLPDownloader(str(self.storage_dir / "downloads"))
        self.hongguo = HongguoDownloaderAdapter()

    def detect_source(self, url: str) -> str:
        """Detect which downloader to use for a URL."""
        hongguo_domains = ['hongguo.com', 'hongguo.tv', 'hongguo.app']
        if any(domain in url for domain in hongguo_domains):
            return 'hongguo'
        return 'yt-dlp'

    def get_media_info(self, url: str) -> MediaInfo:
        """Get media info from appropriate source."""
        source = self.detect_source(url)
        if source == 'hongguo' and self.hongguo.is_available():
            # For Hongguo, we need to parse first to get episode info
            parsed = self.hongguo.parse_drama_link(url)
            # Return first episode info or drama overview
            if parsed.get('episodes'):
                return MediaInfo(
                    id=parsed['episodes'][0].get('id', ''),
                    title=parsed.get('title', 'Hongguo Drama'),
                    duration=sum(e.get('duration', 0) for e in parsed['episodes']),
                    width=parsed['episodes'][0].get('width', 0),
                    height=parsed['episodes'][0].get('height', 0),
                    fps=parsed['episodes'][0].get('fps', 0),
                    formats=[],
                    thumbnail_url=parsed.get('thumbnail'),
                    subtitles={}
                )
        return self.yt_dlp.extract_info(url)

    def download(self, url: str, project_id: int,
                 progress_callback: Optional[Callable[[float, str], None]] = None) -> MediaInfo:
        """Download from appropriate source."""
        source = self.detect_source(url)

        if source == 'hongguo' and self.hongguo.is_available():
            return self._download_hongguo(url, project_id, progress_callback)

        # Use project-specific output directory
        output_dir = str(self.storage_dir / "projects" / str(project_id) / "source")
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        return self.yt_dlp.download(url, progress_callback=progress_callback, output_dir=output_dir)

    def _download_hongguo(self, url: str, project_id: int,
                          progress_callback: Optional[Callable[[float, str], None]] = None) -> MediaInfo:
        """Download Hongguo drama (all episodes)."""
        parsed = self.hongguo.parse_drama_link(url)
        episode_urls = [ep['url'] for ep in parsed.get('episodes', [])]

        output_dir = str(self.storage_dir / "projects" / str(project_id) / "source")
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        results = self.hongguo.download_episodes(episode_urls, output_dir, progress_callback)

        # Return combined info
        if results:
            return MediaInfo(
                id=f"hongguo_{project_id}",
                title=parsed.get('title', 'Hongguo Drama'),
                duration=sum(r.duration for r in results),
                width=results[0].width,
                height=results[0].height,
                fps=results[0].fps,
                formats=[],
                thumbnail_url=parsed.get('thumbnail'),
                subtitles={},
                filepath=results[0].filepath
            )
        return MediaInfo(id="", title="", duration=0, width=0, height=0, fps=0,
                        formats=[], thumbnail_url=None, subtitles={})

    def batch_download(self, urls: List[str], project_id: int,
                       progress_callback: Optional[Callable[[float, str], None]] = None) -> List[MediaInfo]:
        """Download multiple URLs in batch."""
        results = []
        for i, url in enumerate(urls):
            if progress_callback:
                progress_callback(i / len(urls), f"Processing {i+1}/{len(urls)}")
            try:
                info = self.download(url, project_id,
                    lambda p, m: progress_callback((i + p) / len(urls), m) if progress_callback else None)
                results.append(info)
            except Exception as e:
                logger.error(f"Failed to download {url}: {e}")
                if progress_callback:
                    progress_callback((i + 1) / len(urls), f"Failed: {url}")
        return results


# Celery task wrapper
def download_job(url: str, project_id: int, progress_callback=None):
    """Wrapper for Celery/background task execution."""
    manager = DownloadManager()
    return manager.download(url, project_id, progress_callback)


def batch_download_job(urls: List[str], project_id: int, progress_callback=None):
    manager = DownloadManager()
    return manager.batch_download(urls, project_id, progress_callback)