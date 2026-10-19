#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for autovod.py - config parser, templating, argument building.

Run with:  python -m unittest discover -s tests -t . -v
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import autovod  # noqa: E402


class TempDirMixin:
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="autovod-test-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def write_config(self, name, text):
        path = os.path.join(self.dir, name + ".config")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def load_config(self, text, name="tester"):
        return autovod.Config(self.write_config(name, text))

    def make_app(self, extra="", name="tester", **kwargs):
        text = (
            'STREAM_SOURCE="twitch"\n'
            'UPLOAD_SERVICE="local"\n'
            'LOCAL_FILENAME="rec_$STREAMER_NAME"\n'
            'VIDEO_TITLE="$STREAMER_NAME - TIME_DATE"\n'
            'STATE_DIR=".autovod"\n'
            'TEMP_DIR="tmp"\n'
        ) + extra
        cfg = self.load_config(text, name=name)
        return autovod.AutoVod(cfg, autovod.Log("error"), **kwargs)


class ConfigTest(TempDirMixin, unittest.TestCase):
    def test_scalars_quotes_and_comments(self):
        cfg = self.load_config(
            'A="hello world"   #? trailing comment\n'
            "B=unquoted\n"
            "C='single $NOT_EXPANDED'\n"
            'D="a # b"\n'
            'E="$A suffix"\n'
            'F=("x" "y z")\n'
            "set -a\n"
        )
        self.assertEqual(cfg.get("A"), "hello world")
        self.assertEqual(cfg.get("B"), "unquoted")
        self.assertEqual(cfg.get("C"), "single $NOT_EXPANDED")
        self.assertEqual(cfg.get("D"), "a # b")
        self.assertEqual(cfg.get("E"), "hello world suffix")
        self.assertEqual(cfg.get_list("F"), ["x", "y z"])
        self.assertFalse(cfg.warnings)

    def test_streamer_name_expansion(self):
        cfg = self.load_config('VIDEO_TITLE="$STREAMER_NAME - TIME_DATE"', name="asmongold")
        self.assertEqual(cfg.get("VIDEO_TITLE"), "asmongold - TIME_DATE")
        self.assertEqual(cfg.streamer, "asmongold")

    def test_undefined_variable_warns_instead_of_crashing(self):
        cfg = self.load_config('A="x $MISSING y"')
        self.assertEqual(cfg.get("A"), "x  y")
        self.assertTrue(any("MISSING" in warning for warning in cfg.warnings))

    def test_aliases(self):
        cfg = self.load_config('TITLE="my title"\nVISIBILITY="public"\n')
        self.assertEqual(cfg.get("VIDEO_TITLE"), "my title")
        self.assertEqual(cfg.get("VIDEO_VISIBILITY"), "public")

    def test_types_and_defaults(self):
        cfg = self.load_config('B="true"\nI="7"\nF="2.5"\n')
        self.assertTrue(cfg.get_bool("B"))
        self.assertFalse(cfg.get_bool("MISSING"))
        self.assertTrue(cfg.get_bool("MISSING", True))
        self.assertEqual(cfg.get_int("I"), 7)
        self.assertEqual(cfg.get_int("MISSING", 3), 3)
        self.assertAlmostEqual(cfg.get_float("F"), 2.5)
        with self.assertRaises(autovod.ConfigError):
            cfg.get_int("B")

    def test_env_override(self):
        os.environ["AUTOVOD_POLL_INTERVAL"] = "7"
        try:
            cfg = self.load_config('POLL_INTERVAL="60"\n')
            self.assertEqual(cfg.get("POLL_INTERVAL"), "7")
        finally:
            del os.environ["AUTOVOD_POLL_INTERVAL"]

    def test_missing_file(self):
        with self.assertRaises(autovod.ConfigError):
            autovod.Config(os.path.join(self.dir, "nope.config"))


class DurationTest(unittest.TestCase):
    def test_formats(self):
        for value, expected in (("12:00:00", 43200), ("06:00:00", 21600), ("0:30", 30),
                                ("1:30", 90), ("45", 45), ("45s", 45), ("30m", 1800),
                                ("1h30m", 5400), ("2h", 7200), ("", None)):
            self.assertEqual(autovod.parse_duration(value, None), expected, value)

    def test_invalid(self):
        for value in ("abc", "1:2:3:4", "12:xx"):
            with self.assertRaises(autovod.ConfigError):
                autovod.parse_duration(value)

    def test_format_roundtrip(self):
        self.assertEqual(autovod.format_duration(43200), "12:00:00")
        self.assertEqual(autovod.format_duration(0), "00:00:00")


class ProbeTest(unittest.TestCase):
    def test_live(self):
        probe = autovod.parse_probe_output(json.dumps({
            "plugin": "twitch",
            "metadata": {"id": "1", "title": "Hello", "category": "Music"},
            "streams": {"best": {"type": "hls"}, "720p": {"type": "hls"}},
        }))
        self.assertTrue(probe.live)
        self.assertEqual(probe.title, "Hello")
        self.assertEqual(probe.game, "Music")
        self.assertEqual(probe.stream_id, "1")
        self.assertIn("720p", probe.streams)

    def test_offline_error_object(self):
        probe = autovod.parse_probe_output('{"error": "No playable streams found on this URL: twitch.tv/x"}')
        self.assertFalse(probe.live)
        self.assertIn("No playable streams", probe.error)

    def test_garbage_and_empty_streams(self):
        self.assertFalse(autovod.parse_probe_output("streamlink is confused").live)
        self.assertFalse(autovod.parse_probe_output("").live)
        self.assertFalse(autovod.parse_probe_output('{"streams": {}}').live)

    def test_leading_noise_is_tolerated(self):
        probe = autovod.parse_probe_output('warning: something\n{"streams": {"best": {}}, "metadata": {}}')
        self.assertTrue(probe.live)


class RenderTest(TempDirMixin, unittest.TestCase):
    def test_legacy_placeholders(self):
        app = self.make_app()
        out = app.render("$STREAMER_NAME - TIME_DATE TIME_CLOCK", metadata={"title": "T"})
        self.assertTrue(out.startswith("tester - "))
        self.assertNotIn("TIME_DATE", out)
        self.assertNotIn("TIME_CLOCK", out)

    def test_modern_placeholders(self):
        app = self.make_app()
        out = app.render("{{STREAMER}}|{{TITLE}}|{{GAME}}|{{ID}}|{{PART}}",
                         metadata={"title": "Stream", "category": "Games", "id": "42"})
        self.assertEqual(out, "tester|Stream|Games|42|")

    def test_two_x_sentinel_values(self):
        app = self.make_app()
        self.assertEqual(app.render("x initial_title y", metadata={"title": "Real"}), "x Real y")
        self.assertEqual(app.render("x inital_game y", metadata={"category": "Chess"}), "x Chess y")

    def test_metadata_is_not_executed(self):
        """The 2.x eval based substitution ran code embedded in a stream title."""
        app = self.make_app()
        nasty = '$(touch %s) `id` "; rm -rf /' % os.path.join(self.dir, "pwned")
        out = app.render("{{TITLE}}", metadata={"title": nasty})
        self.assertEqual(out, nasty)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "pwned")))

    def test_good_filename(self):
        self.assertEqual(autovod.good_filename('a/b:c*d?"e<f>g|h'), "a-b-c-d-e-f-g-h")
        self.assertEqual(autovod.good_filename("  a   b  "), "a b")


class StateAndLockTest(TempDirMixin, unittest.TestCase):
    def test_part_numbering_per_day(self):
        app = self.make_app(extra='VIDEO_DURATION="00:10:00"\n')
        now = autovod.datetime(2026, 10, 15, 12, 0, 0)
        self.assertEqual(app.next_part_index(now), 1)
        app.state.save()
        self.assertEqual(app.next_part_index(now), 2)
        app.state.save()
        later = autovod.datetime(2026, 10, 16, 1, 0, 0)
        self.assertEqual(app.next_part_index(later), 1)

    def test_state_survives_restart(self):
        app = self.make_app()
        now = autovod.datetime(2026, 10, 15, 12, 0, 0)
        app.next_part_index(now)
        app.state.save()
        second = self.make_app()
        self.assertEqual(second.next_part_index(now), 2)

    def test_make_part_suffix(self):
        app = self.make_app(extra='SPLIT_INTO_PARTS="true"\nSPLIT_VIDEO_DURATION="01:00:00"\n')
        now = autovod.datetime(2026, 10, 15, 12, 0, 0)
        part = app.make_part({"title": "T"}, now)
        self.assertEqual(part.index, 1)
        self.assertEqual(part.suffix, "")
        self.assertEqual(part.title, "tester - 15-10-26 Part: 1")
        app.state.save()
        part2 = app.make_part({"title": "T"}, now)
        self.assertEqual(part2.suffix, "-Part_2")
        self.assertTrue(part2.title.endswith("Part: 2"))

    def test_no_suffix_without_split_on_first_part(self):
        app = self.make_app(extra='SPLIT_INTO_PARTS="false"\n')
        part = app.make_part({"title": "T"}, autovod.datetime(2026, 10, 15, 12, 0, 0))
        self.assertEqual(part.suffix, "")
        self.assertEqual(part.title, "tester - 15-10-26")

    def test_unique_path(self):
        app = self.make_app()
        target = os.path.join(self.dir, "file.mkv")
        self.assertEqual(app.unique_path(target), target)
        open(target, "w").close()
        self.assertEqual(app.unique_path(target), os.path.join(self.dir, "file-1.mkv"))

    def test_lock_is_exclusive(self):
        path = os.path.join(self.dir, "t.lock")
        first = autovod.FileLock(path)
        first.acquire()
        try:
            with self.assertRaises(autovod.LockError):
                autovod.FileLock(path).acquire()
        finally:
            first.release()
        second = autovod.FileLock(path)
        second.acquire()
        second.release()


class ArgumentsTest(TempDirMixin, unittest.TestCase):
    def test_streamlink_record_argv(self):
        app = self.make_app(extra='STREAMLINK_QUALITY="1080p60"\nQUALITY_FALLBACK="best"\nVIDEO_DURATION="01:00:00"\n')
        argv = app.streamlink_argv(duration=3600)
        self.assertEqual(argv[0], "streamlink")
        self.assertIn("--stdout", argv)
        self.assertIn("--retry-streams", argv)
        self.assertEqual(argv[argv.index("--hls-duration") + 1], "01:00:00")
        self.assertEqual(argv[-2], "twitch.tv/tester")
        self.assertEqual(argv[-1], "1080p60,best")

    def test_best_quality_has_no_fallback_list(self):
        app = self.make_app(extra='STREAMLINK_QUALITY="best"\n')
        self.assertEqual(app.streamlink_argv()[-1], "best")

    def test_deprecated_flags_are_dropped(self):
        app = self.make_app(extra='STREAMLINK_FLAGS=("--twitch-disable-ads" "--twitch-disable-reruns" "--foo")\n')
        flags = app.streamlink_flags()
        self.assertEqual(flags, ["--foo"])

    def test_restream_forces_h264_codec_preference(self):
        app = self.make_app(extra='UPLOAD_SERVICE="restream"\nRTMPS_STREAM_KEY="key"\n')
        self.assertIn("--twitch-supported-codecs=h264", app.streamlink_flags())

    def test_kick_and_youtube_urls(self):
        app = self.make_app(extra='STREAM_SOURCE="kick"\n')
        self.assertEqual(app.stream_url, "kick.com/tester")
        app = self.make_app(extra='STREAM_SOURCE="youtube"\n')
        self.assertEqual(app.stream_url, "youtube.com/@tester/live")
        app = self.make_app(extra='STREAM_URL="https://example.com/live.m3u8"\n')
        self.assertEqual(app.stream_url, "https://example.com/live.m3u8")
        with self.assertRaises(autovod.ConfigError):
            self.make_app(extra='STREAM_SOURCE="myspace"\n')

    def test_bin_overrides(self):
        app = self.make_app(extra='STREAMLINK_BIN=("/opt/venv/bin/streamlink" "--loglevel" "debug")\n')
        argv = app.streamlink_argv()
        self.assertEqual(argv[0], "/opt/venv/bin/streamlink")

    def test_audio_settings(self):
        app = self.make_app(extra='AUDIO_BITRATE="192"\n')
        audio = app.audio_settings()
        self.assertFalse(audio["legacy"])
        self.assertEqual(audio["bitrate"], "192k")
        self.assertEqual(audio["samplerate"], 44100)
        legacy = self.make_app(extra='AUDIO_BITRATE="44100"\n').audio_settings()
        self.assertTrue(legacy["legacy"])
        self.assertEqual(legacy["bitrate"], "128k")
        self.assertEqual(legacy["samplerate"], 44100)

    def test_youtube_metadata(self):
        app = self.make_app(extra=(
            'UPLOAD_SERVICE="youtube"\n'
            'VIDEO_TITLE="T"\n'
            'VIDEO_PLAYLIST=""\n'
            'VIDEO_TAGS="a, b,c"\n'
            'VIDEO_LANGUAGE="de"\n'
            'VIDEO_DESCRIPTION="line1\\nline2"\n'
        ), name="tester")
        meta = app.youtube_metadata()
        self.assertEqual(meta["title"], "T")
        self.assertNotIn("playlistTitles", meta)
        self.assertEqual(meta["tags"], ["a", "b", "c"])
        self.assertEqual(meta["language"], "de")
        self.assertEqual(meta["description"], "line1\nline2")

    def test_youtube_metadata_playlist_and_extra_json(self):
        extra = os.path.join(self.dir, "extra.json")
        with open(extra, "w", encoding="utf-8") as handle:
            json.dump({"categoryId": "20", "madeForKids": False}, handle)
        app = self.make_app(extra=(
            'UPLOAD_SERVICE="youtube"\n'
            'VIDEO_PLAYLIST="VODs"\n'
            'VIDEO_META_EXTRA_JSON="extra.json"\n'
        ))
        meta = app.youtube_metadata()
        self.assertEqual(meta["playlistTitles"], ["VODs"])
        self.assertEqual(meta["categoryId"], "20")
        self.assertFalse(meta["madeForKids"])

    def test_preflight_reports_missing_binaries(self):
        app = self.make_app(extra='STREAMLINK_BIN=("definitely-not-installed-xyz")\n')
        problems = app.preflight()
        self.assertTrue(any("definitely-not-installed-xyz" in problem for problem in problems))

    def test_invalid_upload_service(self):
        with self.assertRaises(autovod.ConfigError):
            self.make_app(extra='UPLOAD_SERVICE="dropbox"\n')


class CliTest(TempDirMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self._cwd = os.getcwd()
        os.chdir(self.dir)
        self.addCleanup(os.chdir, self._cwd)

    def test_no_config(self):
        self.assertEqual(autovod.main([]), 2)

    def test_multiple_configs_need_a_name(self):
        self.write_config("a", 'UPLOAD_SERVICE="local"\nLOCAL_FILENAME="x"\n')
        self.write_config("b", 'UPLOAD_SERVICE="local"\nLOCAL_FILENAME="y"\n')
        self.assertEqual(autovod.main([]), 2)

    def test_exactly_one_config_is_auto_selected(self):
        self.write_config("solo", 'UPLOAD_SERVICE="local"\nLOCAL_FILENAME="x"\n')
        self.assertEqual(autovod.main(["--print-config"]), 0)

    def test_print_config(self):
        self.write_config("solo", 'LOCAL_FILENAME="x"\n')
        self.assertEqual(autovod.main(["-n", "solo", "--print-config"]), 0)

    def test_missing_config_file(self):
        self.assertEqual(autovod.main(["-n", "ghost"]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
