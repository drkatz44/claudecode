# youtube-notes

Transcribe YouTube videos and generate meeting note summaries with speaker identification.

## Features

- Fetch YouTube transcripts with time range filtering
- Identify speakers via two methods:
  - **Quick**: Parse `>>` markers from YouTube's auto-captions
  - **Accurate**: Audio-based diarization with pyannote (via Colab)
- Generate structured meeting notes with Claude

## Quick Start

### Option 1: Local CLI

```bash
cd projects/youtube-notes
pip install youtube-transcript-api yt-dlp anthropic typer rich

# Fetch transcript (minutes 3-15)
python -m youtube_notes.cli transcribe "https://youtube.com/watch?v=VIDEO_ID" -s 3 -e 15

# Generate meeting notes (requires ANTHROPIC_API_KEY)
python -m youtube_notes.cli summarize "https://youtube.com/watch?v=VIDEO_ID" -s 3 -e 15 -o notes.md
```

### Option 2: Colab (for speaker diarization)

1. Upload `colab_diarization.ipynb` to [Google Colab](https://colab.research.google.com)
2. Set runtime to **T4 GPU**
3. Get a [HuggingFace token](https://huggingface.co/settings/tokens) and accept [pyannote terms](https://huggingface.co/pyannote/speaker-diarization-3.1)
4. Run all cells

## Output Example

```markdown
**Speaker 1** [03:00]
Welcome everyone. This is the agenda...

**Speaker 2** [05:48]
Question about the timeline?

**Speaker 1** [05:55]
Yes, we have three more hours planned.
```

## Project Structure

```
src/youtube_notes/
├── cli.py          # Command-line interface
├── transcript.py   # YouTube transcript fetching + speaker parsing
├── summarize.py    # Claude-based meeting notes generation
└── models.py       # Data models

colab_diarization.ipynb  # GPU-powered speaker diarization
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `transcribe <url>` | Fetch transcript (use `-s`/`-e` for time range, `-t` for timestamps) |
| `summarize <url>` | Generate meeting notes with Claude |
| `languages <url>` | List available transcript languages |
