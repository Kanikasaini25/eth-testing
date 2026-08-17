#!/usr/bin/env python3
"""
Extract transcripts from a list of YouTube video URLs and save to a file.

Usage:
  python extract_transcripts.py                  # reads from .env
  python extract_transcripts.py "https://youtu.be/abc" "https://youtube.com/watch?v=xyz"

Configure defaults in .env (copy from .env.example).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv
from youtube_transcript_api import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
    YouTubeTranscriptApi,
)

PROJECT_DIR = Path(__file__).resolve().parent
ENV_FILE = PROJECT_DIR / ".env"
load_dotenv(ENV_FILE)

VIDEO_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{11}$")


def extract_video_id(url: str) -> str | None:
    """Extract YouTube video ID from common URL formats."""
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


def load_urls(input_path: Path | None, cli_urls: list[str]) -> list[str]:
    """Load URLs from a file and/or command-line arguments."""
    urls: list[str] = list(cli_urls)

    if input_path:
        if not input_path.exists():
            raise FileNotFoundError(f"Input file not found: {input_path}")

        file_urls = [
            line.strip()
            for line in input_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        urls.extend(file_urls)

    # Preserve order while removing duplicates
    seen: set[str] = set()
    unique_urls: list[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            unique_urls.append(url)

    return unique_urls


def fetch_transcript(
    api: YouTubeTranscriptApi,
    video_id: str,
    languages: list[str],
) -> tuple[str, str]:
    """Fetch transcript text for a video. Returns (language_code, transcript_text)."""
    try:
        transcript = api.fetch(video_id, languages=languages)
    except NoTranscriptFound:
        transcript_list = api.list(video_id)
        try:
            transcript = transcript_list.find_generated_transcript(languages).fetch()
        except NoTranscriptFound:
            transcript = next(iter(transcript_list)).fetch()

    text = " ".join(snippet.text for snippet in transcript.snippets)
    return transcript.language_code, text


def format_transcript_block(
    index: int,
    url: str,
    video_id: str,
    language: str,
    text: str,
) -> str:
    separator = "=" * 80
    return (
        f"{separator}\n"
        f"Video {index}\n"
        f"URL: {url}\n"
        f"Video ID: {video_id}\n"
        f"Language: {language}\n"
        f"{separator}\n\n"
        f"{text.strip()}\n\n"
    )


def load_urls_from_env() -> list[str]:
    """Load URLs from the YOUTUBE_URLS environment variable."""
    env_urls = os.getenv("YOUTUBE_URLS", "").strip()
    if not env_urls:
        return []
    return [url.strip() for url in env_urls.split(",") if url.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract transcripts from YouTube videos and save to a file."
    )
    parser.add_argument(
        "-f",
        "--file",
        help="Optional text file with one YouTube URL per line",
    )
    parser.add_argument(
        "urls",
        nargs="*",
        help="YouTube URLs passed directly on the command line",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=os.getenv("OUTPUT_FILE", "transcripts.txt"),
        help="Output file path (default: OUTPUT_FILE from .env or transcripts.txt)",
    )
    parser.add_argument(
        "-l",
        "--languages",
        default=os.getenv("LANGUAGES", "en"),
        help="Preferred transcript languages, comma-separated (default: LANGUAGES from .env or en)",
    )
    args = parser.parse_args()

    env_urls = load_urls_from_env()
    input_path = Path(args.file) if args.file else None
    cli_urls = args.urls or env_urls

    if not input_path and not cli_urls:
        if not ENV_FILE.exists():
            parser.error(
                f"No .env file found at {ENV_FILE}. "
                "Copy .env.example to .env and set YOUTUBE_URLS."
            )
        parser.error(
            "No URLs found. Set YOUTUBE_URLS in .env or pass URLs as arguments."
        )

    languages = [lang.strip() for lang in args.languages.split(",") if lang.strip()]
    output_path = Path(args.output)

    try:
        urls = load_urls(input_path, cli_urls)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if not urls:
        print("Error: No URLs found.", file=sys.stderr)
        return 1

    blocks: list[str] = []
    errors: list[str] = []
    api = YouTubeTranscriptApi()

    for index, url in enumerate(urls, start=1):
        video_id = extract_video_id(url)
        if not video_id:
            errors.append(f"[{index}] Invalid URL: {url}")
            continue

        print(f"[{index}/{len(urls)}] Fetching transcript for {video_id}...")

        try:
            language, text = fetch_transcript(api, video_id, languages)
            blocks.append(format_transcript_block(index, url, video_id, language, text))
        except TranscriptsDisabled:
            errors.append(f"[{index}] Transcripts disabled: {url}")
        except VideoUnavailable:
            errors.append(f"[{index}] Video unavailable: {url}")
        except NoTranscriptFound:
            errors.append(f"[{index}] No transcript found: {url}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"[{index}] Failed ({url}): {exc}")

    if errors:
        error_block = "\n".join(f"- {message}" for message in errors)
        blocks.append(
            "\n" + "=" * 80 + "\n"
            "ERRORS\n"
            + "=" * 80 + "\n\n"
            + error_block
            + "\n"
        )

    output_path.write_text("".join(blocks), encoding="utf-8")

    success_count = len(urls) - len(errors)
    print(f"\nDone. Saved {success_count}/{len(urls)} transcript(s) to {output_path}")

    if errors:
        print(f"{len(errors)} video(s) failed. See ERRORS section in output file.")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
