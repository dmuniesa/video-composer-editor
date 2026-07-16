"""Curated EXIF/metadata extraction from ffprobe container tags."""
from __future__ import annotations

from app.services import scanner


def test_extract_meta_apple_quicktime():
    tags = {
        "com.apple.quicktime.make": "Apple",
        "com.apple.quicktime.model": "iPhone 14 Pro",
        "com.apple.quicktime.software": "16.5",
        "com.apple.quicktime.location.ISO6709": "+41.38-002.17+012.000/",
        "creation_time": "2023-08-15T12:23:11.000000Z",
        "handler_name": "Core Media Video",  # noise, dropped
        "encoder": "H.264",                    # noise (technical), dropped
    }
    meta = scanner.extract_meta(tags)
    assert meta["make"] == "Apple"
    assert meta["model"] == "iPhone 14 Pro"
    assert meta["software"] == "16.5"
    assert meta["location"].startswith("+41.38")
    # Promoted + noise keys never leak into "tags".
    assert "tags" not in meta


def test_extract_meta_generic_camera_and_lens():
    tags = {
        "make": "SONY",
        "model": "ILCE-7M4",
        "LensModel": "FE 24-70mm F2.8 GM",
        "com.custom.scene": "Beach",
    }
    meta = scanner.extract_meta(tags)
    assert meta["make"] == "SONY"
    assert meta["model"] == "ILCE-7M4"
    assert meta["lens"] == "FE 24-70mm F2.8 GM"
    # Unknown, non-noise tags are preserved for the review panel.
    assert meta["tags"] == {"com.custom.scene": "Beach"}


def test_extract_meta_camera_in_comment():
    # Fujifilm X-T2 (and many others) leave make/model blank and stash the
    # camera identity in the comment, duplicated as a -eng sibling.
    tags = {
        "creation_time": "2026-04-24T12:37:57.000000Z",
        "comment": "FUJIFILM DIGITAL CAMERA X-T2",
        "comment-eng": "FUJIFILM DIGITAL CAMERA X-T2",
        "original_format": "Digital Camera",
        "original_format-eng": "Digital Camera",
        "encoder": "AVC Coding",
    }
    meta = scanner.extract_meta(tags)
    assert meta["make"] == "FUJIFILM"
    assert meta["model"] == "X-T2"
    assert "software" not in meta  # codec "encoder" is not camera software
    # comment consumed; its -eng dup and the codec encoder dropped; the -eng
    # dup of original_format collapsed into the base key.
    assert meta.get("tags", {}) == {"original_format": "Digital Camera"}


def test_extract_meta_empty():
    assert scanner.extract_meta({}) == {}
    # Blank values are ignored, not surfaced as empty fields.
    assert scanner.extract_meta({"make": "  ", "model": ""}) == {}
