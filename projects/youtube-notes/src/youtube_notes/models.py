"""Data models for YouTube Notes."""

from dataclasses import dataclass


@dataclass
class TranscriptSegment:
    """A segment of transcript with timing info."""

    text: str
    start: float
    duration: float
    speaker: str | None = None

    @property
    def end(self) -> float:
        return self.start + self.duration


@dataclass
class Transcript:
    """Full transcript of a video."""

    video_id: str
    title: str
    segments: list[TranscriptSegment]

    @property
    def full_text(self) -> str:
        """Return the complete transcript as plain text."""
        return " ".join(seg.text for seg in self.segments)

    @property
    def timestamped_text(self) -> str:
        """Return transcript with timestamps."""
        lines = []
        for seg in self.segments:
            minutes = int(seg.start // 60)
            seconds = int(seg.start % 60)
            lines.append(f"[{minutes:02d}:{seconds:02d}] {seg.text}")
        return "\n".join(lines)

    @property
    def speaker_text(self) -> str:
        """Return transcript with speaker labels and timestamps."""
        lines = []
        current_speaker = None
        for seg in self.segments:
            minutes = int(seg.start // 60)
            seconds = int(seg.start % 60)
            timestamp = f"[{minutes:02d}:{seconds:02d}]"

            if seg.speaker and seg.speaker != current_speaker:
                current_speaker = seg.speaker
                lines.append(f"\n**{current_speaker}** {timestamp}")
                lines.append(seg.text)
            else:
                lines.append(f"{timestamp} {seg.text}")
        return "\n".join(lines)

    def get_speakers(self) -> list[str]:
        """Return list of unique speakers in order of appearance."""
        seen = set()
        speakers = []
        for seg in self.segments:
            if seg.speaker and seg.speaker not in seen:
                seen.add(seg.speaker)
                speakers.append(seg.speaker)
        return speakers


@dataclass
class MeetingNotes:
    """Summarized meeting notes from a transcript."""

    video_id: str
    title: str
    summary: str
    key_points: list[str]
    action_items: list[str]
    topics: list[str]
