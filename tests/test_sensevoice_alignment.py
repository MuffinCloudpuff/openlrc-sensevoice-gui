import unittest

from openlrc.transcribe import Transcriber


class TestSenseVoiceAlignment(unittest.TestCase):
    def setUp(self) -> None:
        self.transcriber = Transcriber.__new__(Transcriber)
        self.transcriber.continuous_scripted = ["ja", "zh", "zh-cn", "th", "vi", "lo", "km", "my", "bo"]

    def test_build_segments_uses_word_timestamps_for_long_sentences(self):
        words = [
            "How", "could", "something", "be", "so", "beautiful", "?",
            "And", "yet", ",", "a", "total", "hot", "mess", ".",
            "I", "don", "'", "t", "know", ".",
            "You", "'", "ll", "have", "to", "ask", "my", "ex", "wife", ".",
            "Disclaimer", "it", "'", "s", "part", "of", "a", "growing", "trend", "in", "PC", "hardware", "to",
            "take", "the", "icky", "messy", "cables", "that", "have", "cluttered", "our", "gaming", "rigs", "for",
            "my", "entire", "life", "and", "hide", "them", "away", "by", "moving", "all", "the", "connectors", "to",
            "the", "back", "of", "the", "motherboard", "and", "I", "mean", "sounds", "pretty", "good", "to", "me",
            ",", "it", "'", "s", "not", "like", "we", "were", "using", "this", "space", "for", "anything", "else",
            ",", "but", "not", "everyone", "'", "s", "happy", "with", "this", "trend", ".",
        ]
        timestamps = [[10339 + idx * 120, 10339 + (idx + 1) * 120] for idx in range(len(words))]
        text = (
            "🎼How could something be so beautiful? And yet, a total hot mess. I don't know. "
            "You'll have to ask my ex wife. 😊Disclaimer it's part of a growing trend in PC hardware "
            "to take the icky messy cables that have cluttered our gaming rigs for my entire life and hide "
            "them away by moving all the connectors to the back of the motherboard and I mean sounds pretty "
            "good to me, it's not like we were using this space for anything else, but not everyone's happy "
            "with this trend."
        )

        segments = self.transcriber._build_segments(
            [{"text": text, "words": words, "timestamps": timestamps}],
            "en",
        )

        self.assertGreaterEqual(len(segments), 6)
        self.assertTrue(all(segment.end > segment.start for segment in segments))
        self.assertGreater(segments[-1].start, 10.0)
        self.assertTrue(any("Disclaimer" in segment.text for segment in segments))
