# Project: youtube-notes

## Purpose
Transcribe YouTube videos and generate meeting note summaries using Claude.

## Status
active

## Stack
- Python 3.11+
- uv (package management)
- youtube-transcript-api (transcript fetching)
- yt-dlp (video metadata)
- anthropic SDK (Claude summarization)
- typer + rich (CLI)

## Key Files
- `src/youtube_notes/cli.py` - Command-line interface
- `src/youtube_notes/transcript.py` - YouTube transcript fetching
- `src/youtube_notes/summarize.py` - Claude-based summarization
- `src/youtube_notes/models.py` - Data models

## Usage
```bash
# Install
cd projects/youtube-notes
uv sync

# Fetch transcript
uv run youtube-notes transcribe "https://youtube.com/watch?v=VIDEO_ID"
uv run youtube-notes transcribe VIDEO_ID --timestamps

# Generate meeting notes
uv run youtube-notes summarize "https://youtube.com/watch?v=VIDEO_ID"
uv run youtube-notes summarize VIDEO_ID -o notes.md

# List available languages
uv run youtube-notes languages VIDEO_ID
```

## Environment
- `ANTHROPIC_API_KEY` - Required for summarization

## Current State (2026-02)

### Working
- CLI: `transcribe`, `summarize`, `languages`, `cache` commands
- Transcript caching (7-day TTL, `~/.cache/youtube-notes/`)
- Transcript fetching with time range filtering (`--start`, `--end`)
- Claude summarization → meeting notes (good quality output)
- Multi-language support
- Basic speaker detection (`>>` markers from auto-captions)
- Colab notebook for GPU-based speaker diarization (pyannote.audio)

### Needs Improvement
- **Speaker diarization not integrated** - Colab notebook exists but separate from CLI
- **No `--speakers` flag** - `parse_speakers()` exists but not exposed
- **Long video chunking** - No handling for Claude context limits
- **Output formats** - Only markdown (could add JSON, SRT)

### Key Files
- `src/youtube_notes/transcript.py:83` - `parse_speakers()` (unused in CLI)
- `colab_diarization.ipynb` - GPU speaker diarization with pyannote

## Notes
- Uses YouTube's built-in transcripts (auto-generated or manual captions)
- Falls back gracefully if video title can't be fetched
- Supports multiple languages via `--language` flag
