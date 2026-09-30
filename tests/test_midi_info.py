"""
Unit tests for MIDI duration parsing.
"""

import tempfile
import unittest
from pathlib import Path
from pianofall.utils.midi_info import get_midi_duration


class TestMidiInfo(unittest.TestCase):
    def test_handel_midi_duration(self):
        root = Path(__file__).resolve().parent.parent
        sample = root / "midis" / "Handel_HWV425.mid"
        self.assertTrue(sample.exists(), "Sample MIDI file must exist")

        dur = get_midi_duration(sample)
        self.assertIsNotNone(dur)
        # Handel Air in E major HWV 425 is approximately 206 seconds
        self.assertTrue(200.0 < dur < 215.0)

    def test_invalid_midi_duration(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            bad_file = Path(tmp_dir) / "corrupt.mid"
            bad_file.write_bytes(b"NOT_A_MIDI_FILE_DATA_CORRUPT")

            dur = get_midi_duration(bad_file)
            self.assertIsNone(dur)


if __name__ == "__main__":
    unittest.main()
