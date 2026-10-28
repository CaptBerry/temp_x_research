from __future__ import annotations

import csv
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
        dataframe = pd.read_csv(
            path,
            sep=sep,
            header=0 if header else None,
            nrows=nrows,
            engine="python" if sep in (None, r"\s+") else "c",
        )
        # Stable string labels also support headerless files in Qt and JSON.
        dataframe.columns = [str(column) for column in dataframe.columns]
        return dataframe

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
