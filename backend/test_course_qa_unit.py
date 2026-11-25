"""Pure validation tests: no PostgreSQL, network, Flask sessions or fixtures."""

import unittest
from course_qa import course_code, text_field


class CourseQAValidationTests(unittest.TestCase):
    def test_normalizes_supported_course_code_formats(self):
        for value, expected in [('csc510', 'CSC 510'), (' CSC-510 ', 'CSC 510'),
                                ('ma 141', 'MA 141'), ('ABCD 123A', 'ABCD 123A')]:
            with self.subTest(value=value):
                self.assertEqual(course_code(value), expected)

    def test_rejects_invalid_course_types_lengths_and_structure(self):
        for value in (None, True, 510, [], {}, '', 'A 510', 'ABCDE 510',
                      'CSC 51', 'CSC 5100', 'CSC 510AB', 'CSC 510; DROP TABLE', 'x' * 31):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    course_code(value)

    def test_trims_post_text_without_changing_content(self):
        value = "  A peer's advice\nSecond line: café ✓  "
        self.assertEqual(text_field({'body': value}, 'body', 4000),
                         "A peer's advice\nSecond line: café ✓")

    def test_accepts_exact_character_boundaries_after_trimming(self):
        for name, limit in (('title', 160), ('body', 4000)):
            for value in ('x', 'é' * limit, '  ' + 'x' * limit + '  '):
                with self.subTest(name=name, length=len(value)):
                    self.assertEqual(text_field({name: value}, name, limit), value.strip())

    def test_rejects_missing_blank_non_text_and_over_limit_content(self):
        for data in ({}, {'body': None}, {'body': True}, {'body': 12}, {'body': []},
                     {'body': {}}, {'body': ''}, {'body': '\n \t'}, {'body': 'x' * 4001}):
            with self.subTest(data=str(data)[:60]):
                with self.assertRaises(ValueError):
                    text_field(data, 'body', 4000)

    def test_validated_text_remains_plain_text_for_the_renderer(self):
        # Validation preserves user text; React, not this helper, performs HTML escaping.
        value = '<img src=x onerror=alert(1)>'
        self.assertEqual(text_field({'body': value}, 'body', 4000), value)
