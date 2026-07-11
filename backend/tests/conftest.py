from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent


@pytest.fixture(autouse=True)
def _isolated_registry(tmp_path, monkeypatch):
    """Keep the project registry and settings out of $HOME during tests."""
    monkeypatch.setenv("MONTAGE_REGISTRY", str(tmp_path / "registry.json"))
    import app.db as dbm

    monkeypatch.setattr(dbm, "REGISTRY_PATH", tmp_path / "registry.json")

    monkeypatch.setenv("MONTAGE_SETTINGS", str(tmp_path / "settings.json"))
    from app import settings

    settings.reload()
    yield
    settings.reload()


@pytest.fixture
def fake_agy(monkeypatch):
    script = TESTS_DIR / "fake_agy.py"
    # Python instead of bash so the fake runs on Windows too, and forward
    # slashes because agy_command() parses AGY_CMD with shlex.split (POSIX
    # mode), which eats backslashes.
    monkeypatch.setenv(
        "AGY_CMD", f"{Path(sys.executable).as_posix()} {script.as_posix()} -p"
    )
    yield script


@pytest.fixture(scope="session")
def sample_video(tmp_path_factory) -> Path:
    """8s test-pattern H.264 clip generated with ffmpeg."""
    dest = tmp_path_factory.mktemp("media") / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=duration=8:size=640x360:rate=25",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(dest),
        ],
        check=True,
    )
    return dest


@pytest.fixture(scope="session")
def sample_song(tmp_path_factory) -> Path:
    """30s synthetic track: 120 BPM click over two alternating drones, so
    beat tracking and segmentation have something real to find."""
    dest = tmp_path_factory.mktemp("media") / "song.wav"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi",
            "-i",
            "sine=frequency=220:duration=30,volume=0.3",
            "-f", "lavfi",
            "-i",
            "sine=frequency=880:duration=30,volume='0.5*lt(mod(t,0.5),0.05)':eval=frame",
            "-filter_complex", "amix=inputs=2",
            str(dest),
        ],
        check=True,
    )
    return dest
