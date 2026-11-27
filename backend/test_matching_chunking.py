import unittest

from matching.chunking import split_phrases


class SplitPhrasesTests(unittest.TestCase):
    def test_splits_on_punctuation_newlines_and_bullets(self):
        text = "push notifications; demo days, SQL.\nindexing• caching · testing\r\n- linting"
        self.assertEqual(split_phrases(text),
                         ["push notifications", "demo days", "SQL", "indexing", "caching", "testing", "linting"])

    def test_drops_empties_and_case_insensitive_duplicates_keeping_first(self):
        self.assertEqual(split_phrases(" ; Python ,, python;  PYTHON ; Go ;"), ["Python", "Go"])

    def test_empty_inputs(self):
        for text in ("", "   ", None, ";;,.", "\n\n"):
            self.assertEqual(split_phrases(text), [])

    def test_truncates_and_caps(self):
        self.assertEqual(split_phrases("abcdefgh", max_chars=3), ["abc"])
        self.assertEqual(split_phrases(";".join(str(i) for i in range(50)), max_phrases=5),
                         ["0", "1", "2", "3", "4"])
        self.assertEqual(len(split_phrases(";".join(str(i) for i in range(50)))), 20)

    def test_single_phrase_without_separators(self):
        self.assertEqual(split_phrases("  full-stack web apps "), ["full-stack web apps"])


if __name__ == "__main__":
    unittest.main()
