from __future__ import annotations

import os
import re
from urllib.parse import parse_qs, urlparse

import requests
from youtube_transcript_api import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
    YouTubeTranscriptApi,
)

VIDEO_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{11}$")


def _youtube_http_client() -> requests.Session:
    """Create a YouTube client that avoids blocked inherited proxies by default."""
    session = requests.Session()
    session.trust_env = os.getenv("YOUTUBE_USE_ENV_PROXY", "false").lower() == "true"
    return session


def extract_video_id(url: str) -> str | None:
    url = url.strip()
    if not url:
        return None

    if VIDEO_ID_PATTERN.match(url):
        return url

    parsed = urlparse(url)

    if parsed.hostname in {"youtu.be", "www.youtu.be"}:
        video_id = parsed.path.lstrip("/").split("/")[0]
        return video_id if VIDEO_ID_PATTERN.match(video_id) else None

    if parsed.hostname in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if parsed.path == "/watch":
            video_ids = parse_qs(parsed.query).get("v", [])
            return video_ids[0] if video_ids else None

        path_parts = parsed.path.strip("/").split("/")
        if len(path_parts) >= 2 and path_parts[0] in {"embed", "shorts", "live"}:
            video_id = path_parts[1]
            return video_id if VIDEO_ID_PATTERN.match(video_id) else None

    return None


def fetch_transcript_text(url: str, languages: list[str] | None = None) -> dict[str, str]:
    """Fetch transcript for a YouTube URL."""
    languages = languages or ["en"]
    video_id = extract_video_id(url)
    if not video_id:
        raise ValueError(f"Invalid YouTube URL: {url}")

    api = YouTubeTranscriptApi(http_client=_youtube_http_client())

    try:
        transcript = api.fetch(video_id, languages=languages)
    except NoTranscriptFound:
        transcript_list = api.list(video_id)
        try:
            transcript = transcript_list.find_generated_transcript(languages).fetch()
        except NoTranscriptFound:
            transcript = next(iter(transcript_list)).fetch()

    text = " ".join(snippet.text for snippet in transcript.snippets)
    return {
        "video_id": video_id,
        "url": url,
        "language": transcript.language_code,
        "text": text.strip(),
    }
