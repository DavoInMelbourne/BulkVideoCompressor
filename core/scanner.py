from pathlib import Path

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".ts", ".m2ts"}


def scan_directory(source_dir: str) -> list[Path]:
    """Recursively scan source_dir for video files."""
    root = Path(source_dir)
    files = []
    for ext in VIDEO_EXTENSIONS:
        files.extend(root.rglob(f"*{ext}"))
    return sorted(files)


def get_output_path(source_file: Path, source_root: Path, output_root: Path) -> Path:
    """Mirror source folder structure in output_root, forcing .mkv extension."""
    relative = source_file.relative_to(source_root)
    return (output_root / relative).with_suffix(".mkv")


def scan_non_video_files(source_dir: str) -> list[Path]:
    """Recursively scan source_dir for non-video files (e.g. .srt, .nfo, images)."""
    root = Path(source_dir)
    return sorted(
        f for f in root.rglob("*")
        if f.is_file() and f.suffix.lower() not in VIDEO_EXTENSIONS
    )
