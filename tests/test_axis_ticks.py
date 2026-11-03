import unittest

from scene.axis_ticks import readable_axis_labels, rounded_axis_range


class AxisTickTests(unittest.TestCase):
    def test_round_numbers_expand_bounds_and_choose_nice_steps(self):
        for values, expected in (
            ((3.2, 9.7, 0), ((2, 10), 5)),
            ((18556002.51, 18557502.51, 2), ((18556000, 18558000), 5)),
            ((0.12, 0.48, 2), ((0.1, 0.5), 5)),
            ((-3.2, 2.2, 0), ((-4, 4), 5)),
            ((0, 0, 0), ((-1, 1), 3)),
        ):
            with self.subTest(values=values):
                self.assertEqual(rounded_axis_range(*values), expected)

    def test_long_labels_are_thinned_when_axis_projects_short(self):
        labels = ("18556000.00", "18557000.00", "18558000.00",
                  "18559000.00", "18560000.00")
        self.assertEqual(readable_axis_labels(labels, 1000),
                         ("", "18557000.00", "18558000.00", "18559000.00", ""))
        self.assertEqual(readable_axis_labels(labels, 80),
                         ("", "", "18558000.00", "", ""))
        self.assertEqual(readable_axis_labels(labels, 10), ("",) * 5)
        self.assertEqual(readable_axis_labels(("-1", "0", "1"), 500),
                         ("-1", "0", "1"))


if __name__ == "__main__":
    unittest.main()
