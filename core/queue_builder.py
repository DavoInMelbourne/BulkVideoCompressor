"""
Build HandBrake queue job entries.

HandBrake ≥ 1.7 uses a JSON queue file. We target the 1.7+ schema.
Each entry is a JSON object matching HandBrake's QueueJobList item.
"""
from __future__ import annotations
import json
from pathlib import Path
from .mediainfo import VideoInfo, AudioTrack, SubtitleTrack
from .languages import Language

# ---------------------------------------------------------------------------
# Audio selection
# ---------------------------------------------------------------------------

def select_audio_track(
    tracks: list[AudioTrack],
    audio_language: Language,
    prioritise_dts: bool = True,
    fallback_language: Language | None = None,
) -> AudioTrack | None:
    """Select the best audio track.

    Priority order (with prioritise_dts=True):
      1. DTS/TrueHD in preferred language
      2. Any codec in preferred language
      3. DTS/TrueHD in fallback language
      4. Any codec in fallback language
      5. DTS/TrueHD in any language
      6. First track

    With audio_language=ENGLISH the old "prefer English" behaviour is preserved.
    With any other language, non-English tracks in that language are preferred
    (i.e. the "Foreign" behaviour is automatically applied for non-English picks).
    """
    if not tracks:
        return None

    def is_preferred_codec(t: AudioTrack) -> bool:
        if not t.codec:
            return False
        codec = t.codec.lower()
        return "dts" in codec or "truehd" in codec

    # Resolve ORIGINAL to the language of the first track
    resolved_language = audio_language
    if audio_language is Language.ORIGINAL:
        first_lang = tracks[0].language if tracks else None
        # Find a Language enum that matches, else treat as NON_ENGLISH fallback
        resolved_language = next(
            (l for l in Language if l.codes and first_lang in l.codes),
            Language.NON_ENGLISH,
        )

    def try_lang(lang: Language | None, codec_filter: bool) -> AudioTrack | None:
        if lang is None:
            return None
        if lang is Language.NON_ENGLISH:
            for t in tracks:
                if not Language.ENGLISH.matches(t.language):
                    if not codec_filter or is_preferred_codec(t):
                        return t
            return None
        for t in tracks:
            if lang.matches(t.language):
                if not codec_filter or is_preferred_codec(t):
                    return t
        return None

    # DTS wins from any language — this is the primary purpose of
    # prioritise_dts.  Language preference only applies when no DTS track exists.
    if prioritise_dts:
        for t in tracks:
            if t.codec and "dts" in t.codec.lower():
                return t

    # No DTS available — apply language preference
    result = try_lang(resolved_language, False)
    if result:
        return result

    if fallback_language and fallback_language != audio_language:
        result = try_lang(fallback_language, False)
        if result:
            return result

    return tracks[0]


# ---------------------------------------------------------------------------
# Subtitle selection
# ---------------------------------------------------------------------------

def select_subtitle_tracks(
    tracks: list[SubtitleTrack],
    subtitle_language: Language | None = None,
    fallback_language: Language | None = None,
) -> list[SubtitleTrack]:
    """Return subtitle tracks ordered: Forced → Regular → SDH.

    Tries subtitle_language first, falls back to fallback_language, then
    falls back to English.  At most one of each type is returned — mapping
    multiple PGS tracks causes the MKV muxer to stall with time=N/A.
    """
    if subtitle_language is None:
        subtitle_language = Language.ENGLISH
    if fallback_language is None:
        fallback_language = Language.ENGLISH

    def pick(lang: Language) -> list[SubtitleTrack]:
        matches = [t for t in tracks if lang.matches(t.language)]
        forced  = [t for t in matches if t.forced]
        sdh     = [t for t in matches if not t.forced and t.sdh]
        regular = [t for t in matches if not t.forced and not t.sdh]
        return forced[:1] + regular[:1] + sdh[:1]

    result = pick(subtitle_language)
    if not result and fallback_language != subtitle_language:
        result = pick(fallback_language)
    if not result and Language.ENGLISH not in (subtitle_language, fallback_language):
        result = pick(Language.ENGLISH)
    return result


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
