import subprocess
from pathlib import Path

from app.services import frames


def _make_video(dest: Path, with_audio: bool) -> None:
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=duration=3:size=160x120:rate=25"]
    if with_audio:
        args += ["-f", "lavfi", "-i", "sine=frequency=440:duration=3"]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if with_audio:
        args += ["-c:a", "aac", "-shortest"]
    args.append(str(dest))
    subprocess.run(args, check=True)


def _has_audio(path: Path) -> bool:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    return bool(out.stdout.strip())


def test_preview_is_always_mute(tmp_path):
    """preview.mp4 (the file the AI analyzes) must never carry audio — the clip's
    audio lives in a separate preview.mp3 so the AI input is unaffected."""
    src = tmp_path / "av.mp4"
    _make_video(src, with_audio=True)
    cache = tmp_path / "cache"
    frames.make_preview(src, cache)
    assert (cache / "preview.mp4").is_file()
    assert not _has_audio(cache / "preview.mp4")


def test_clip_audio_extracted(tmp_path):
    src = tmp_path / "av.mp4"
    _make_video(src, with_audio=True)
    cache = tmp_path / "cache"
    out = frames.make_clip_audio(src, cache)
    assert out is not None and out.is_file()
    assert out.name == "preview.mp3"
    assert _has_audio(out)


def test_clip_audio_none_for_silent_video(tmp_path):
    """A source with no audio stream yields no preview.mp3 (the montage preview
    then stays silent for that clip), and never raises."""
    src = tmp_path / "noaudio.mp4"
    _make_video(src, with_audio=False)
    cache = tmp_path / "cache"
    assert frames.make_clip_audio(src, cache) is None
    assert not (cache / "preview.mp3").exists()
