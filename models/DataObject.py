from .ProjectObject import ProjectObject


class DataObject(ProjectObject):

    def __init__(self, name="Object"):

        super().__init__(name)

        self.filename = None

        self.loaded = False

    def load(self):

        self.loaded = True

    def unload(self):

        self.loaded = False