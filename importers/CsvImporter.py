import pandas as pd

from importers.BaseImporter import BaseImporter


class CsvImporter(BaseImporter):

    def preview(
            self,
            filename,
            delimiter=None,
            header=True
    ):

        if delimiter is None:
            delimiter = ","

        df = pd.read_csv(
            filename,
            sep=delimiter,
            header=0 if header else None,
            nrows=100
        )

        return df