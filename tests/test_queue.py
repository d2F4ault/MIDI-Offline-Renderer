"""
Unit tests for queue discovery and ledger management.
"""

import tempfile
import unittest
from pathlib import Path
from pianofall.queue.ledger import (
    append_failed_entry,
    append_processed_entry,
    load_failed_map,
    load_processed_set,
)
from pianofall.queue.manager import select_candidates


class TestQueue(unittest.TestCase):
    def test_ledger_append_and_load(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proc_log = Path(tmp_dir) / "processed.txt"
            fail_log = Path(tmp_dir) / "failed.txt"

            append_processed_entry(
                log_path=proc_log,
                midi_filename="test_song.mid",
                duration_s=120.5,
                frames=7230,
                file_size_bytes=5000000,
                rel_output_path="outputs/2026-09-30/test_song.mp4",
            )

            proc_set = load_processed_set(proc_log)
            self.assertIn("test_song.mid", proc_set)
            self.assertIn("test_song", proc_set)

            append_failed_entry(
                log_path=fail_log,
                midi_filename="broken_song.mid",
                error_msg="Test timeout error",
            )

            quarantined, attempts = load_failed_map(fail_log)
            self.assertIn("broken_song.mid", quarantined)
            self.assertEqual(attempts.get("broken_song.mid"), 1)

    def test_select_candidates_filters_processed(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proc_log = Path(tmp_dir) / "processed.txt"
            fail_log = Path(tmp_dir) / "failed.txt"
            midi_dir = Path(tmp_dir) / "midis"
            midi_dir.mkdir()

            root = Path(__file__).resolve().parent.parent
            sample = root / "midis" / "Handel_HWV425.mid"
            target = midi_dir / "Handel_HWV425.mid"
            target.write_bytes(sample.read_bytes())

            cand = select_candidates(
                midi_dir=midi_dir,
                processed_log=proc_log,
                failed_log=fail_log,
                max_duration_seconds=300.0,
                limit=1,
                auto_fetch_preview=False,
            )
            self.assertEqual(len(cand), 1)
            self.assertEqual(cand[0][0].name, "Handel_HWV425.mid")

            # Mark as processed
            append_processed_entry(
                log_path=proc_log,
                midi_filename="Handel_HWV425.mid",
                duration_s=206.5,
                frames=12390,
                file_size_bytes=5000000,
                rel_output_path="outputs/2026-09-30/Handel_HWV425.mp4",
            )

            # Now candidate should be filtered out
            cand_after = select_candidates(
                midi_dir=midi_dir,
                processed_log=proc_log,
                failed_log=fail_log,
                max_duration_seconds=300.0,
                limit=1,
                auto_fetch_preview=False,
            )
            self.assertEqual(len(cand_after), 0)


if __name__ == "__main__":
    unittest.main()
