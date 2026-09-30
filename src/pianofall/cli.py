"""
Command-line interface (CLI) for PianoFall.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Optional

from .config import config
from .core.runner import execute_batch, render_single_midi
from .queue.downloader import download_from_url, download_public_preview_midis
from .queue.ledger import (
    append_failed_entry,
    append_processed_entry,
    load_failed_map,
    load_processed_set,
)
from .queue.manager import discover_available_midis, select_candidates
from .utils.logging import fmt_bytes, fmt_hms, setup_logger
from .utils.midi_info import get_midi_duration
from .utils.system import find_binary, get_ffmpeg_version, get_system_summary

logger = setup_logger("pianofall")


def cmd_inspect_system(args: argparse.Namespace) -> int:
    """Print system diagnostics, CPU cores, RAM, and binary dependencies."""
    summary = get_system_summary()
    logger.info("=" * 60)
    logger.info("PIANOFALL SYSTEM DIAGNOSTICS")
    logger.info("=" * 60)
    logger.info(f"Operating System : {summary['os']}")
    logger.info(f"CPU Cores        : {summary['cpu_cores']}")
    logger.info(f"Physical Memory  : {summary['total_memory']}")
    logger.info(f"Python Version   : {summary['python_version']}")

    ffmpeg_path = find_binary(config.ffmpeg_bin)
    ffprobe_path = find_binary(config.ffprobe_bin)
    ffmpeg_ver = get_ffmpeg_version(config.ffmpeg_bin) if ffmpeg_path else "Not found"

    logger.info(f"FFmpeg Binary    : {ffmpeg_path or 'NOT FOUND'} ({ffmpeg_ver})")
    logger.info(f"FFprobe Binary   : {ffprobe_path or 'NOT FOUND'}")
    logger.info(f"Xvfb Available   : {'Yes' if find_binary('Xvfb') else 'No'}")
    logger.info("=" * 60)
    return 0


def cmd_queue_status(args: argparse.Namespace) -> int:
    """List pending, completed, and quarantined MIDI files."""
    processed = load_processed_set(config.processed_log)
    quarantined, attempts = load_failed_map(config.failed_log)
    all_midis = discover_available_midis(config.midi_dir)

    pending = [p for p in all_midis if p.name not in processed and p.stem not in processed and p.name not in quarantined]

    logger.info("=" * 60)
    logger.info("PIANOFALL QUEUE STATUS")
    logger.info("=" * 60)
    logger.info(f"Total Local MIDIs : {len(all_midis)}")
    logger.info(f"Completed Pieces  : {len(processed)}")
    logger.info(f"Quarantined Files : {len(quarantined)}")
    logger.info(f"Pending in Queue  : {len(pending)}")
    logger.info("-" * 60)

    if pending:
        logger.info("Next Pending Pieces:")
        for p in pending[:10]:
            dur = get_midi_duration(p)
            dur_str = fmt_hms(dur) if dur else "unknown"
            logger.info(f"  * {p.name} ({dur_str})")
        if len(pending) > 10:
            logger.info(f"  ... and {len(pending) - 10} more.")
    else:
        logger.info("No pending files in local queue.")
    logger.info("=" * 60)
    return 0


def cmd_fetch_midi(args: argparse.Namespace) -> int:
    """Download preview pieces or a direct URL into the midis folder."""
    if args.url:
        target = config.midi_dir / Path(args.url).name
        download_from_url(args.url, target)
    else:
        logger.info("Fetching public domain classical preview pieces...")
        download_public_preview_midis(config.midi_dir)
    return 0


async def _run_batch_async(args: argparse.Namespace) -> int:
    max_videos = args.max_videos if args.max_videos is not None else config.max_videos_per_run
    max_dur = args.max_duration if args.max_duration is not None else config.max_piece_duration_seconds
    test_sec = args.test_seconds if args.test_seconds is not None else config.test_seconds

    # Environment variable fallbacks for CI workflow dispatch
    if os.getenv("INPUT_MAX_VIDEOS"):
        try:
            max_videos = int(os.getenv("INPUT_MAX_VIDEOS", ""))
        except ValueError:
            pass

    if os.getenv("INPUT_TEST_SECONDS"):
        try:
            test_sec = float(os.getenv("INPUT_TEST_SECONDS", ""))
        except ValueError:
            pass

    target_piece = args.piece or os.getenv("INPUT_PIECE_NAME") or None

    logger.info("=" * 60)
    logger.info("PIANOFALL AUTOMATED CPU RENDERING PIPELINE")
    logger.info("=" * 60)
    logger.info(f"Max videos this run : {max_videos}")
    logger.info(f"Max piece duration  : {fmt_hms(max_dur)}")
    logger.info(f"Test duration cap   : {f'{test_sec}s' if test_sec else 'Disabled (full song)'}")
    logger.info(f"Target filter       : {target_piece or 'None (auto-queue)'}")
    logger.info("-" * 60)

    candidates = select_candidates(
        midi_dir=config.midi_dir,
        processed_log=config.processed_log,
        failed_log=config.failed_log,
        max_duration_seconds=max_dur,
        limit=max_videos,
        target_piece=target_piece,
        allow_exceed_duration=args.allow_exceed_duration,
        auto_fetch_preview=True,
    )

    if not candidates:
        logger.info("No eligible unprocessed pieces found in queue. Pipeline complete.")
        return 0

    files_to_render = [c[0] for c in candidates]
    logger.info(f"Selected {len(files_to_render)} piece(s) for rendering:")
    for path, dur in candidates:
        logger.info(f"  * {path.name} ({fmt_hms(dur)})")

    if args.dry_run:
        logger.info("Dry run flag set; skipping rendering execution.")
        return 0

    results = await execute_batch(
        midi_files=files_to_render,
        output_dir=config.output_dir,
        cfg=config,
        test_seconds=test_sec,
    )

    # Record ledger updates
    rendered_stems = set()
    for final_path, duration_s, frames in results:
        size = final_path.stat().st_size if final_path.exists() else 0
        try:
            rel_path = final_path.relative_to(config.base_dir).as_posix()
        except ValueError:
            rel_path = final_path.as_posix()

        append_processed_entry(
            log_path=config.processed_log,
            midi_filename=final_path.stem,
            duration_s=duration_s,
            frames=frames,
            file_size_bytes=size,
            rel_output_path=rel_path,
        )
        rendered_stems.add(final_path.stem)

    # Any candidate that was attempted but not in rendered_stems is marked failed
    for path, _ in candidates:
        if path.stem not in rendered_stems:
            append_failed_entry(
                log_path=config.failed_log,
                midi_filename=path.name,
                error_msg="Render execution aborted or failed validation",
            )

    logger.info(f"Batch completed: {len(results)}/{len(files_to_render)} succeeded.")
    return 0 if len(results) > 0 or len(files_to_render) == 0 else 1


def cmd_render_batch(args: argparse.Namespace) -> int:
    """Run the batch rendering pipeline."""
    return asyncio.run(_run_batch_async(args))


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="pianofall",
        description="Automated offline MIDI piano visualization pipeline.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # render-batch
    batch_parser = subparsers.add_parser("render-batch", help="Process queued MIDI files.")
    batch_parser.add_argument("--max-videos", type=int, default=None, help="Max videos to render.")
    batch_parser.add_argument("--max-duration", type=float, default=None, help="Max piece duration in seconds.")
    batch_parser.add_argument("--test-seconds", type=float, default=None, help="Render only first N seconds.")
    batch_parser.add_argument("--piece", type=str, default=None, help="Target specific filename or substring.")
    batch_parser.add_argument("--allow-exceed-duration", action="store_true", help="Allow targeted piece to exceed duration.")
    batch_parser.add_argument("--dry-run", action="store_true", help="Inspect candidate selection without rendering.")

    # queue
    subparsers.add_parser("queue", help="Display current queue and ledger statistics.")

    # inspect-system
    subparsers.add_parser("inspect-system", help="Inspect system CPU, memory, and FFmpeg version.")

    # fetch-midi
    fetch_parser = subparsers.add_parser("fetch-midi", help="Fetch public domain MIDIs.")
    fetch_parser.add_argument("--url", type=str, default=None, help="Direct URL to MIDI file.")

    args = parser.parse_args()

    # Default to render-batch if no subcommand passed
    if args.command is None:
        return cmd_render_batch(argparse.Namespace(
            max_videos=None,
            max_duration=None,
            test_seconds=None,
            piece=None,
            allow_exceed_duration=False,
            dry_run=False,
        ))

    if args.command == "render-batch":
        return cmd_render_batch(args)
    elif args.command == "queue":
        return cmd_queue_status(args)
    elif args.command == "inspect-system":
        return cmd_inspect_system(args)
    elif args.command == "fetch-midi":
        return cmd_fetch_midi(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())
