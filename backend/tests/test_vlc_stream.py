import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import VLC_PLAYER_HINT_URL, VLC_UDP_URL, _build_vlc_ffmpeg_command


class VlcRelayCommandTests(unittest.TestCase):
    def test_build_vlc_ffmpeg_command_uses_webm_pipe_and_vlc_url(self) -> None:
        subtitle_path = Path("/tmp/subtitle.txt")
        command = _build_vlc_ffmpeg_command("ffmpeg", subtitle_path, VLC_UDP_URL)

        self.assertIn("ffmpeg", command)
        self.assertIn("-f", command)
        self.assertIn("webm", command)
        self.assertIn("pipe:0", command)
        self.assertIn(VLC_UDP_URL, command)

    def test_player_hint_url_is_loopback_ready(self) -> None:
        self.assertEqual(VLC_PLAYER_HINT_URL, "udp://@127.0.0.1:1234")


if __name__ == "__main__":
    unittest.main()
