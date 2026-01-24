"""Summarize transcripts into meeting notes using Claude."""

import os

import anthropic

from .models import MeetingNotes, Transcript

SYSTEM_PROMPT = """You are an expert at converting video transcripts into clear, actionable meeting notes.
Your task is to analyze the transcript and produce structured notes that capture the essential information."""

SUMMARIZE_PROMPT = """Please analyze this video transcript and create comprehensive meeting notes.

Video Title: {title}

Transcript:
{transcript}

Please provide your response in the following exact format:

## Summary
[2-3 paragraph summary of the main content]

## Key Points
- [Key point 1]
- [Key point 2]
- [Continue as needed]

## Action Items
- [Action item 1, if any]
- [Action item 2, if any]
- [Write "None identified" if no action items]

## Topics Covered
- [Topic 1]
- [Topic 2]
- [Continue as needed]
"""


def summarize_transcript(
    transcript: Transcript,
    model: str = "claude-sonnet-4-20250514",
    max_tokens: int = 4096,
) -> MeetingNotes:
    """
    Generate meeting notes from a transcript using Claude.

    Args:
        transcript: The video transcript
        model: Claude model to use
        max_tokens: Maximum tokens in response

    Returns:
        MeetingNotes with summary, key points, action items, and topics
    """
    client = anthropic.Anthropic()

    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": SUMMARIZE_PROMPT.format(
                    title=transcript.title,
                    transcript=transcript.full_text,
                ),
            }
        ],
    )

    response_text = message.content[0].text
    return parse_summary_response(transcript.video_id, transcript.title, response_text)


def parse_summary_response(video_id: str, title: str, response: str) -> MeetingNotes:
    """Parse the structured response into a MeetingNotes object."""
    sections = {
        "summary": "",
        "key_points": [],
        "action_items": [],
        "topics": [],
    }

    current_section = None
    current_content = []

    for line in response.split("\n"):
        line_lower = line.lower().strip()

        if "## summary" in line_lower:
            current_section = "summary"
            current_content = []
        elif "## key points" in line_lower:
            if current_section == "summary":
                sections["summary"] = "\n".join(current_content).strip()
            current_section = "key_points"
            current_content = []
        elif "## action items" in line_lower:
            if current_section == "key_points":
                sections["key_points"] = extract_list_items(current_content)
            current_section = "action_items"
            current_content = []
        elif "## topics" in line_lower:
            if current_section == "action_items":
                sections["action_items"] = extract_list_items(current_content)
            current_section = "topics"
            current_content = []
        elif current_section:
            current_content.append(line)

    # Handle last section
    if current_section == "topics":
        sections["topics"] = extract_list_items(current_content)
    elif current_section == "action_items":
        sections["action_items"] = extract_list_items(current_content)

    return MeetingNotes(
        video_id=video_id,
        title=title,
        summary=sections["summary"],
        key_points=sections["key_points"],
        action_items=sections["action_items"],
        topics=sections["topics"],
    )


def extract_list_items(lines: list[str]) -> list[str]:
    """Extract bullet points from lines."""
    items = []
    for line in lines:
        line = line.strip()
        if line.startswith("- "):
            item = line[2:].strip()
            if item and item.lower() != "none identified":
                items.append(item)
    return items
