from __future__ import annotations

# (encoder, encoder_preset, default_rf)
PRESETS: dict[str, tuple[str, str, float]] = {
    "Fast H.264 (Hardware)": ("h264_videotoolbox", "", 65.0),
    "Fast H.265 (Hardware)": ("hevc_videotoolbox", "", 82.0),
    "Fast H.264": ("x264", "fast", 22.0),
    "Balanced H.265": ("x265", "medium", 18.0),
    "Quality H.265 12-bit": ("x265_12bit", "medium", 20.0),  # RF 20 = excellent quality
    "Quality AV1": ("av1", "4", 30.0),
}
DEFAULT_PRESET = "Quality H.265 12-bit"
DEFAULT_PRESET_4K = "Fast H.265 (Hardware)"
DEFAULT_RF_4K = 63.0
DEFAULT_RF_4K_SMALL = 70.0
DEFAULT_4K_SMALL_THRESHOLD_GB = 10.0
