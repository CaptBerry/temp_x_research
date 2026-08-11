import pandas as pd


class TableData:

    def __init__(
            self,
            dataframe: pd.DataFrame | None = None,
            name: str = ""
    ):
        self.name = name
        self.dataframe = (
            dataframe
            if dataframe is not None
            else pd.DataFrame()
        )

        # Отображение координат
        self.x_column = None
        self.y_column = None
        self.z_column = None

        # Параметры
        self.parameters = []

    @property
    def shape(self):
        return self.dataframe.shape

    @property
    def columns(self):
        return list(self.dataframe.columns)

    @property
    def row_count(self):
        return len(self.dataframe)

    @property
    def column_count(self):
        return len(self.dataframe.columns)

    def set_coordinates(self, x, y, z):
        self.x_column = x
        self.y_column = y
        self.z_column = z

    def set_parameters(self, parameters):
        self.parameters = list(parameters)

    def get_coordinates(self):
        return self.dataframe[
            [self.x_column, self.y_column, self.z_column]
        ]

    def get_parameter(self, name):
        return self.dataframe[name]

    def clear(self):
        self.dataframe = pd.DataFrame()
        self.x_column = None
        self.y_column = None
        self.z_column = None
        self.parameters = []