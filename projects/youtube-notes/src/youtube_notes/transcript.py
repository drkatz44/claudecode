"""Fetch transcripts from YouTube videos."""

import json
import re
import time
from pathlib import Path

from youtube_transcript_api import YouTubeTranscriptApi

from .models import Transcript, TranscriptSegment


# Cache configuration
CACHE_DIR = Path.home() / ".cache" / "youtube-notes"
CACHE_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days (transcripts rarely change)


def _get_cache_path(video_id: str, language: str) -> Path:
    """Get cache file path for a video/language combo."""
    return CACHE_DIR / f"{video_id}_{language}.json"


def _load_from_cache(video_id: str, language: str) -> dict | None:
    """Load transcript from cache if valid."""
    cache_path = _get_cache_path(video_id, language)
    if not cache_path.exists():
        return None

    try:
        data = json.loads(cache_path.read_text())
        if time.time() - data.get("cached_at", 0) < CACHE_TTL_SECONDS:
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return None


def _save_to_cache(video_id: str, language: str, title: str, segments: list[dict]):
    """Save transcript to cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = _get_cache_path(video_id, language)
    data = {
        "video_id": video_id,
        "title": title,
        "language": language,
        "segments": segments,
        "cached_at": time.time(),
    }
    cache_path.write_text(json.dumps(data))


def clear_cache(video_id: str | None = None):
    """Clear cache for a specific video or all videos."""
    if not CACHE_DIR.exists():
        return
    if video_id:
        for path in CACHE_DIR.glob(f"{video_id}_*.json"):
            path.unlink()
    else:
        for path in CACHE_DIR.glob("*.json"):
            path.unlink()


def extract_video_id(url_or_id: str) -> str:
    """Extract video ID from a YouTube URL or return as-is if already an ID."""
    patterns = [
        r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})",
        r"^([a-zA-Z0-9_-]{11})$",
    ]
    for pattern in patterns:
        match = re.search(pattern, url_or_id)
        if match:
            return match.group(1)
    raise ValueError(f"Could not extract video ID from: {url_or_id}")


def get_video_title(video_id: str) -> str:
    """Fetch video title using yt-dlp."""
    try:
        import yt_dlp

        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            return info.get("title", f"Video {video_id}")
    except Exception:
        return f"Video {video_id}"


def fetch_transcript(
    url_or_id: str,
    languages: list[str] | None = None,
    start_time: float | None = None,
    end_time: float | None = None,
    use_cache: bool = True,
) -> Transcript:
    """
    Fetch transcript for a YouTube video.

    Args:
        url_or_id: YouTube URL or video ID
        languages: Preferred languages (default: ["en"])
        start_time: Start time in seconds (optional)
        end_time: End time in seconds (optional)
        use_cache: Whether to use cached transcripts (default: True)

    Returns:
        Transcript object with segments
    """
    video_id = extract_video_id(url_or_id)
    languages = languages or ["en"]
    language = languages[0]

    # Try cache first
    cached = _load_from_cache(video_id, language) if use_cache else None

    if cached:
        title = cached["title"]
        raw_segments = cached["segments"]
    else:
        # Fetch from API
        api = YouTubeTranscriptApi()
        transcript_data = api.fetch(video_id, languages=languages)
        title = get_video_title(video_id)
        raw_segments = [
            {"text": s.text, "start": s.start, "duration": s.duration}
            for s in transcript_data
        ]
        # Cache the full transcript
        if use_cache:
            _save_to_cache(video_id, language, title, raw_segments)

    # Build segments with optional time filtering
    segments = []
    for snippet in raw_segments:
        seg_start = snippet["start"]
        seg_end = seg_start + snippet["duration"]

        # Filter by time range if specified
        if start_time is not None and seg_end < start_time:
            continue
        if end_time is not None and seg_start > end_time:
            continue

        segments.append(
            TranscriptSegment(
                text=snippet["text"],
                start=snippet["start"],
                duration=snippet["duration"],
            )
        )

    return Transcript(video_id=video_id, title=title, segments=segments)


def parse_speakers(transcript: Transcript) -> Transcript:
    """
    Parse speaker changes from >> markers in transcript text.

    YouTube auto-generated transcripts use >> to indicate speaker changes.
    This function identifies these markers and assigns speaker labels.

    Args:
        transcript: Transcript to process

    Returns:
        New Transcript with speaker labels assigned to segments
    """
    speaker_pattern = re.compile(r'^>>+\s*')
    current_speaker = "Speaker 1"
    speaker_count = 1
    speaker_map: dict[int, str] = {}  # Maps segment index to speaker changes

    # First pass: identify where speaker changes occur
    for i, seg in enumerate(transcript.segments):
        if speaker_pattern.match(seg.text):
            speaker_count += 1
            current_speaker = f"Speaker {speaker_count}"
            speaker_map[i] = current_speaker

    # Second pass: assign speakers to all segments
    current_speaker = "Speaker 1"
    new_segments = []

    for i, seg in enumerate(transcript.segments):
        if i in speaker_map:
            current_speaker = speaker_map[i]

        # Clean the >> marker from text
        cleaned_text = speaker_pattern.sub('', seg.text)

        new_segments.append(
            TranscriptSegment(
                text=cleaned_text,
                start=seg.start,
                duration=seg.duration,
                speaker=current_speaker,
            )
        )

    return Transcript(
        video_id=transcript.video_id,
        title=transcript.title,
        segments=new_segments,
    )


def list_available_transcripts(url_or_id: str) -> list[dict]:
    """List all available transcripts for a video."""
    video_id = extract_video_id(url_or_id)
    api = YouTubeTranscriptApi()
    transcript_list = api.list(video_id)

    available = []
    for transcript in transcript_list:
        available.append(
            {
                "language": transcript.language,
                "language_code": transcript.language_code,
                "is_generated": transcript.is_generated,
                "is_translatable": transcript.is_translatable,
            }
        )
    return available
