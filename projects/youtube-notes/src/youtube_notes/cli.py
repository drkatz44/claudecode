"""Command-line interface for YouTube Notes."""

import re
from pathlib import Path

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from .models import MeetingNotes, Transcript
from .summarize import summarize_transcript
from .transcript import fetch_transcript, list_available_transcripts

app = typer.Typer(
    name="youtube-notes",
    help="Transcribe YouTube videos and generate meeting note summaries.",
)
console = Console()


def parse_time(time_str: str | None) -> float | None:
    """Parse time string to seconds. Supports: '3' (minutes), '3:30' (mm:ss), '90' (seconds if <1)."""
    if time_str is None:
        return None
    time_str = time_str.strip()
    if ":" in time_str:
        parts = time_str.split(":")
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    # Assume minutes if a simple number
    return float(time_str) * 60


@app.command()
def transcribe(
    url: str = typer.Argument(..., help="YouTube URL or video ID"),
    output: Path | None = typer.Option(None, "--output", "-o", help="Output file path"),
    timestamps: bool = typer.Option(False, "--timestamps", "-t", help="Include timestamps"),
    language: str = typer.Option("en", "--language", "-l", help="Transcript language code"),
    start: str | None = typer.Option(None, "--start", "-s", help="Start time (minutes or mm:ss)"),
    end: str | None = typer.Option(None, "--end", "-e", help="End time (minutes or mm:ss)"),
):
    """Fetch and display the transcript of a YouTube video."""
    try:
        start_time = parse_time(start)
        end_time = parse_time(end)

        with console.status("Fetching transcript..."):
            transcript = fetch_transcript(url, languages=[language], start_time=start_time, end_time=end_time)

        text = transcript.timestamped_text if timestamps else transcript.full_text

        if output:
            output.write_text(text)
            console.print(f"[green]Transcript saved to {output}[/green]")
        else:
            console.print(Panel(text, title=transcript.title))

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def summarize(
    url: str = typer.Argument(..., help="YouTube URL or video ID"),
    output: Path | None = typer.Option(None, "--output", "-o", help="Output file path"),
    language: str = typer.Option("en", "--language", "-l", help="Transcript language code"),
    model: str = typer.Option(
        "claude-sonnet-4-20250514", "--model", "-m", help="Claude model to use"
    ),
    start: str | None = typer.Option(None, "--start", "-s", help="Start time (minutes or mm:ss)"),
    end: str | None = typer.Option(None, "--end", "-e", help="End time (minutes or mm:ss)"),
):
    """Generate meeting notes summary from a YouTube video."""
    try:
        start_time = parse_time(start)
        end_time = parse_time(end)

        with console.status("Fetching transcript..."):
            transcript = fetch_transcript(url, languages=[language], start_time=start_time, end_time=end_time)

        console.print(f"[dim]Video: {transcript.title}[/dim]")
        console.print(f"[dim]Transcript length: {len(transcript.full_text)} characters[/dim]")

        with console.status("Generating summary with Claude..."):
            notes = summarize_transcript(transcript, model=model)

        markdown = format_notes_as_markdown(notes)

        if output:
            output.write_text(markdown)
            console.print(f"[green]Notes saved to {output}[/green]")
        else:
            console.print(Markdown(markdown))

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def languages(
    url: str = typer.Argument(..., help="YouTube URL or video ID"),
):
    """List available transcript languages for a video."""
    try:
        with console.status("Fetching available transcripts..."):
            available = list_available_transcripts(url)

        if not available:
            console.print("[yellow]No transcripts available for this video.[/yellow]")
            return

        console.print("[bold]Available transcripts:[/bold]\n")
        for t in available:
            auto = " (auto-generated)" if t["is_generated"] else ""
            console.print(f"  {t['language_code']}: {t['language']}{auto}")

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


def format_notes_as_markdown(notes: MeetingNotes) -> str:
    """Format MeetingNotes as Markdown."""
    lines = [
        f"# {notes.title}",
        "",
        f"**Video ID:** {notes.video_id}",
        "",
        "## Summary",
        "",
        notes.summary,
        "",
        "## Key Points",
        "",
    ]

    for point in notes.key_points:
        lines.append(f"- {point}")

    lines.extend(["", "## Action Items", ""])

    if notes.action_items:
        for item in notes.action_items:
            lines.append(f"- [ ] {item}")
    else:
        lines.append("_No action items identified._")

    lines.extend(["", "## Topics Covered", ""])

    for topic in notes.topics:
        lines.append(f"- {topic}")

    return "\n".join(lines)


if __name__ == "__main__":
    app()
