from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path

try:
    from pymediainfo import MediaInfo
    PYMEDIAINFO_AVAILABLE = True
except ImportError:
    PYMEDIAINFO_AVAILABLE = False

import subprocess
import json


@dataclass
class AudioTrack:
    index: int          # 1-based track number within file
    language: str       # ISO 639-2/B code e.g. "eng", "fra", or "" if unknown
    codec: str
    title: str = ""


@dataclass
class SubtitleTrack:
    index: int
    language: str
    title: str = ""
    forced: bool = False
    sdh: bool = False


@dataclass
class VideoInfo:
    width: int = 0
    height: int = 0
    fps: float = 0.0
    duration_secs: float = 0.0
    color_range: str = ""   # "limited" or "full" — passed through
    video_codec: str = ""   # lowercase: "hevc", "av1", "h264", "avc", …
    file_size_bytes: int = 0
    hdr: bool = False       # True if PQ (smpte2084) transfer function detected
    audio_tracks: list[AudioTrack] = field(default_factory=list)
    subtitle_tracks: list[SubtitleTrack] = field(default_factory=list)


def _lang_norm(lang: str) -> str:
    """Normalise language codes to lowercase 3-letter ISO 639-2/B."""
    if not lang:
        return ""
    lang = lang.lower().strip()
    # Map 2-letter → 3-letter for common cases
    _map = {"en": "eng", "fr": "fra", "de": "deu", "es": "spa", "it": "ita",
            "ja": "jpn", "zh": "zho", "pt": "por", "nl": "nld", "ko": "kor"}
    return _map.get(lang, lang)


def _probe_pymediainfo(path: Path) -> VideoInfo:
    info = VideoInfo()
    info.file_size_bytes = path.stat().st_size
    mi = MediaInfo.parse(str(path))

    audio_idx = 0
    sub_idx = 0

    for track in mi.tracks:
        t = track.track_type

        if t == "General":
            try:
                info.duration_secs = float(track.duration or 0) / 1000.0
            except (ValueError, TypeError):
                pass

        elif t == "Video" and info.width == 0:
            info.width = int(track.width or 0)
            info.height = int(track.height or 0)
            # Frame rate
            fps_str = track.frame_rate or "0"
            try:
                info.fps = float(fps_str)
            except ValueError:
                info.fps = 0.0
            info.color_range = (track.color_range or "").lower()
            info.video_codec = (track.format or "").lower()
            transfer = (getattr(track, "transfer_characteristics", None) or "").lower()
            info.hdr = "2084" in transfer or transfer == "pq"

        elif t == "Audio":
            audio_idx += 1
            lang = _lang_norm(track.language or "")
            codec = track.codec_id or track.format or ""
            title = track.title or ""
            info.audio_tracks.append(AudioTrack(
                index=audio_idx,
                language=lang,
                codec=codec,
                title=title,
            ))

        elif t == "Text":
            sub_idx += 1
            lang = _lang_norm(track.language or "")
            title = (track.title or "").lower()
            forced = bool(getattr(track, "forced", None) in ("Yes", "yes", True))
            sdh = "sdh" in title or "hearing" in title
            info.subtitle_tracks.append(SubtitleTrack(
                index=sub_idx,
                language=lang,
                title=track.title or "",
                forced=forced,
                sdh=sdh,
            ))

    return info


def _probe_ffprobe(path: Path) -> VideoInfo:
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", str(path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    data = json.loads(result.stdout)
    streams = data.get("streams", [])

    info = VideoInfo()
    info.file_size_bytes = path.stat().st_size
    audio_idx = 0
    sub_idx = 0

    for s in streams:
        codec_type = s.get("codec_type", "")

        if codec_type == "video" and info.width == 0:
            info.width = int(s.get("width", 0))
            info.height = int(s.get("height", 0))
            r_frame_rate = s.get("r_frame_rate", "0/1")
            try:
                num, den = r_frame_rate.split("/")
                info.fps = float(num) / float(den) if float(den) else 0.0
            except Exception:
                info.fps = 0.0
            info.color_range = s.get("color_range", "").lower()
            info.video_codec = s.get("codec_name", "").lower()
            info.hdr = s.get("color_transfer", "") == "smpte2084"
            try:
                info.duration_secs = float(s.get("duration", 0))
            except (ValueError, TypeError):
                pass

        elif codec_type == "audio":
            audio_idx += 1
            tags = s.get("tags", {})
            lang = _lang_norm(tags.get("language", ""))
            codec = s.get("codec_name", "")
            title = tags.get("title", "")
            info.audio_tracks.append(AudioTrack(
                index=audio_idx,
                language=lang,
                codec=codec,
                title=title,
            ))

        elif codec_type == "subtitle":
            sub_idx += 1
            tags = s.get("tags", {})
            lang = _lang_norm(tags.get("language", ""))
            title = tags.get("title", "")
            title_lower = title.lower()
            forced = bool(s.get("disposition", {}).get("forced", 0))
            sdh = "sdh" in title_lower or "hearing" in title_lower
            info.subtitle_tracks.append(SubtitleTrack(
                index=sub_idx,
                language=lang,
                title=title,
                forced=forced,
                sdh=sdh,
            ))

    return info


def probe_file(path: Path) -> VideoInfo:
    """Probe a video file. Prefers pymediainfo, falls back to ffprobe."""
    if PYMEDIAINFO_AVAILABLE:
        try:
            return _probe_pymediainfo(path)
        except Exception:
            pass
    return _probe_ffprobe(path)
