"""Tests for transcript module."""

import pytest

from youtube_notes.transcript import extract_video_id


class TestExtractVideoId:
    """Tests for video ID extraction."""

    def test_standard_url(self):
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        assert extract_video_id(url) == "dQw4w9WgXcQ"

    def test_short_url(self):
        url = "https://youtu.be/dQw4w9WgXcQ"
        assert extract_video_id(url) == "dQw4w9WgXcQ"

    def test_embed_url(self):
        url = "https://www.youtube.com/embed/dQw4w9WgXcQ"
        assert extract_video_id(url) == "dQw4w9WgXcQ"

    def test_raw_id(self):
        assert extract_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_url_with_params(self):
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=120"
        assert extract_video_id(url) == "dQw4w9WgXcQ"

    def test_invalid_url(self):
        with pytest.raises(ValueError):
            extract_video_id("not-a-valid-url")

    def test_invalid_short_string(self):
        with pytest.raises(ValueError):
            extract_video_id("abc")
