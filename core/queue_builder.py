"""
Build HandBrake queue job entries.

HandBrake ≥ 1.7 uses a JSON queue file. We target the 1.7+ schema.
Each entry is a JSON object matching HandBrake's QueueJobList item.
"""
from __future__ import annotations
import json
from pathlib import Path
from .mediainfo import VideoInfo, AudioTrack, SubtitleTrack

# ---------------------------------------------------------------------------
# Audio selection
# ---------------------------------------------------------------------------

def select_audio_track(tracks: list[AudioTrack], prefer_english: bool) -> AudioTrack | None:
    if not tracks:
        return None

    if prefer_english:
        for t in tracks:
            if t.language == "eng":
                return t
        return tracks[0]
    else:
        # Foreign: prefer first non-English
        for t in tracks:
            if t.language != "eng":
                return t
        return tracks[0]


# ---------------------------------------------------------------------------
# Subtitle selection
# ---------------------------------------------------------------------------

def select_subtitle_tracks(tracks: list[SubtitleTrack]) -> list[SubtitleTrack]:
    """
    Return English subtitle tracks ordered: Forced → Regular → SDH.
    All three types included if present; no burn-in.
    """
    eng = [t for t in tracks if t.language in ("eng", "")]

    forced = [t for t in eng if t.forced]
    sdh = [t for t in eng if not t.forced and t.sdh]
    regular = [t for t in eng if not t.forced and not t.sdh]

    return forced + regular + sdh


# ---------------------------------------------------------------------------
# Framerate helpers
# ---------------------------------------------------------------------------

def _resolve_fps(source_fps: float) -> tuple[float | None, bool]:
    """
    Returns (target_fps, pfr).
    If source is ~50 fps → 25 fps, pfr=True.
    Otherwise pass-through (None = same as source), pfr=True.
    """
    if abs(source_fps - 50.0) < 1.0:
        return 25.0, True
    return None, True   # None = "same as source"


# ---------------------------------------------------------------------------
# Build a single job dict (HandBrake 1.7+ JSON queue schema)
# ---------------------------------------------------------------------------

def build_job(
    source_path: Path,
    output_path: Path,
    info: VideoInfo,
    prefer_english: bool,
    rf: float = 20.0,
) -> dict:
    audio_track = select_audio_track(info.audio_tracks, prefer_english)
    subtitle_tracks = select_subtitle_tracks(info.subtitle_tracks)

    target_fps, pfr = _resolve_fps(info.fps)

    # ---- Video ----
    video = {
        "Encoder": "x265_12bit",
        "Level": "auto",
        "Options": "",
        "Preset": "medium",
        "Profile": "auto",
        "Quality": rf,
        "QualityType": 2,   # 2 = Constant Quality (RF)
        "Tune": "",
        "TwoPass": False,
        "Turbo": False,
    }

    # Framerate
    if target_fps is not None:
        video["Framerate"] = int(target_fps)
        video["FramerateMode"] = 2  # PFR
    else:
        video["Framerate"] = 0      # 0 = same as source
        video["FramerateMode"] = 2  # PFR

    # ---- Audio ----
    audio_list = []
    if audio_track:
        audio_list.append({
            "Track": audio_track.index - 1,  # HandBrake uses 0-based index
            "Encoder": "copy",
            "Mixdown": "none",
            "Samplerate": 0,
            "Bitrate": 0,
            "CompressionLevel": -1,
            "DRC": 0,
            "Gain": 0,
            "Name": audio_track.title,
        })

    # ---- Subtitles ----
    sub_list = []
    for st in subtitle_tracks:
        sub_list.append({
            "Track": st.index - 1,  # 0-based
            "Forced": st.forced,
            "Burned": False,
            "Default": st.forced,
            "Name": st.title,
        })

    # ---- Filters ----
    filters = {
        "FilterList": [
            # Deinterlace/denoise etc. all off — pass through
        ]
    }

    # ---- Source / Destination ----
    source = {
        "Angle": 0,
        "Chapter": {"End": -1, "Start": 1},
        "Path": str(source_path),
        "Title": 0,
        "Type": 0,
    }

    destination = {
        "AlignAVStart": True,
        "ChapterList": [],
        "ChapterMarkers": False,
        "File": str(output_path),
        "Format": "av_mkv",
        "Mux": "av_mkv",
        "Options": {
            "IpodAtom": False,
            "Mp4HttpOptimize": False,
        },
    }

    # ---- Picture (no crop/scale) ----
    picture = {
        "Crop": [0, 0, 0, 0],          # Top/Bottom/Left/Right = 0
        "CropMode": 0,                  # 0 = None
        "DARWidth": 0,
        "DARHeight": 0,
        "DisplayWidth": info.width,
        "Height": info.height,
        "ItuPAR": False,
        "KeepDisplayAspect": True,
        "Modulus": 2,
        "PAR": {"Den": 1, "Num": 1},
        "PictureScanMode": 0,
        "Rotate": 0,
        "Width": info.width,
        "Sharpness": {"Deblock": {"CustomDeblock": "", "Deblock": "off"},
                      "Sharpen": {"CustomSharpen": "", "SharpenPreset": "off",
                                  "SharpenTune": "none"}},
    }

    job = {
        "Job": {
            "Audio": {"AudioList": audio_list, "CopyMask": ["copy:aac", "copy:ac3",
                      "copy:eac3", "copy:truehd", "copy:dts", "copy:dtshd",
                      "copy:mp3", "copy:flac", "copy:opus"]},
            "Destination": destination,
            "Filters": filters,
            "PAR": {"Den": 1, "Num": 1},
            "Picture": picture,
            "Sequence ID": 0,
            "Source": source,
            "Subtitle": {"SubtitleList": sub_list},
            "Video": video,
        },
        "State": 1,   # 1 = Waiting
    }

    return job


# ---------------------------------------------------------------------------
# Build full queue JSON
# ---------------------------------------------------------------------------

def build_queue(jobs: list[dict]) -> str:
    """Serialise a list of job dicts to HandBrake queue JSON."""
    return json.dumps(jobs, indent=2)
