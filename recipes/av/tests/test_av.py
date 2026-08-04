"""Smoke tests for PyAV cross-compiled mobile wheel."""

import av


def test_import_and_version():
    """Prove the av module loads and exposes basic metadata."""
    assert hasattr(av, "__version__")


def test_basic_codec_registry():
    """Prove the C-extension path works: codec access needs linked FFmpeg libs."""
    # Accessing codecs exercises all seven linked FFmpeg libraries.
    codecs = av.codec.codecs_available
    assert isinstance(codecs, set)
    assert len(codecs) > 0


def test_codec_lookup():
    """Prove codec name-based lookups work through the linked FFmpeg tree."""
    # h264 is universally available; its codec object confirms libavcodec linked.
    codec = av.codec.Codec("h264", "r")
    assert codec is not None
    assert codec.name == "h264"


def test_video_frame_create():
    """Prove Frame creation and pixel format access round-trips correctly."""
    frame = av.VideoFrame(width=16, height=16, format="yuv420p")
    assert frame.width == 16
    assert frame.height == 16
    assert frame.format.name == "yuv420p"
