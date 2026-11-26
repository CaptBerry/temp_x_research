from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd

from importers.BaseImporter import BaseImporter

class CsvImporter(BaseImporter):
    DELIMITERS = {
        "auto": None,
        "comma": ",",
        "semicolon": ";",
        "tab": "\t",
        "space": r"\s+",
    }

    def preview(self, filename, delimiter="auto", header=True):
        return self._read_csv(filename, delimiter, header, nrows=100)

    def load(self, filename, delimiter="auto", header=True):
        return self._read_csv(filename, delimiter, header)

    def _read_csv(self, filename, delimiter="auto", header=True, nrows=None):
        path = Path(filename)
        sep = self._resolve_delimiter(path, delimiter)
        # Excel exports in Russian locales commonly use ; and decimal commas.
        # Retry the whole read: non-ASCII data may occur after the preview rows.
        for encoding in ("utf-8-sig", "cp1251"):
            try:
                dataframe = pd.read_csv(
                    path,
                    sep=sep,
                    header=0 if header else None,
                    nrows=nrows,
                    encoding=encoding,
                    decimal=self._resolve_decimal(path, sep, encoding),
                    engine="python" if sep in (None, r"\s+") else "c",
                )
                break
            except UnicodeDecodeError:
                if encoding == "cp1251":
                    raise
        # Stable string labels also support headerless files in Qt and JSON.
        dataframe.columns = [str(column) for column in dataframe.columns]
        return dataframe

    def _resolve_decimal(self, path, sep, encoding):
        with path.open(encoding=encoding) as stream:
            # Whole lines avoid splitting a UTF-8 character or a number.
            sample = []
            for _, line in zip(range(100), stream):
                sample.append(line)
        rows = (line.split() for line in sample) if sep == r"\s+" else csv.reader(sample, delimiter=sep or ",")
        counts = {".": 0, ",": 0}
        for row in rows:
            for value in row:
                for mark in counts:
                    pattern = rf"[+-]?(?:\d+{re.escape(mark)}\d*|{re.escape(mark)}\d+)(?:[eE][+-]?\d+)?"
                    counts[mark] += bool(re.fullmatch(pattern, value.strip()))
        return "," if counts[","] and not counts["."] else "."

    def _resolve_delimiter(self, path, delimiter):
        delimiter = (delimiter or "auto").lower()
        sep = self.DELIMITERS.get(delimiter, delimiter)

        if sep is not None:
            return sep

        with path.open(encoding="utf-8-sig", errors="ignore") as stream:
            sample = stream.read(4096)
        try:
            detected = csv.Sniffer().sniff(sample, delimiters=",;\t ").delimiter
            return r"\s+" if detected == " " else detected
        except csv.Error:
            return ","
