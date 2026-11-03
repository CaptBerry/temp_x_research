"""Human-readable coordinate ranges for the graduated scene axes."""

import math


def rounded_axis_range(lower, upper, decimals):
    """Expand bounds to a 1/2/5 × 10ⁿ step without moving the data."""
    minimum_step = 10.0 ** -decimals
    span = upper - lower
    target = (span / 4 if span > 0 else abs(lower) * 1e-6)
    target = max(target, minimum_step)
    power = 10.0 ** math.floor(math.log10(target))
    step = next((factor * power for factor in (1, 2, 5, 10)
                 if factor * power >= target), 10 * power)
    step = max(step, minimum_step)

    def aligned(value):
        quotient = value / step
        nearest = round(quotient)
        return float(nearest) if abs(quotient - nearest) < 1e-10 else quotient

    first = math.floor(aligned(lower)) * step
    last = math.ceil(aligned(upper)) * step
    if first == last:
        first -= step
        last += step
    count = max(2, int(round((last - first) / step)) + 1)
    return (first, last), count


def readable_axis_labels(labels, screen_length, font_size=14):
    """Blank crowded labels while retaining their tick and grid positions."""
    labels = list(labels)
    count = len(labels)
    if count == 0:
        return tuple()
    max_chars = max(len(label) for label in labels)
    width = max_chars * font_size * 0.62
    if count >= 4 or max_chars >= 8:
        labels[0] = labels[-1] = ""
    # A single central label remains useful on a short projected axis. Hide
    # it only when even half its text width would reach the adjacent axes.
    if screen_length < width * 0.5:
        return ("",) * count
    gap = screen_length / max(1, count - 1)
    candidates = [index for index, label in enumerate(labels) if label]
    chosen = []
    for index in sorted(candidates, key=lambda i: abs(i - (count - 1) / 2)):
        if all(abs(index - kept) * gap >= width + font_size for kept in chosen):
            chosen.append(index)
    return tuple(label if index in chosen else "" for index, label in enumerate(labels))
