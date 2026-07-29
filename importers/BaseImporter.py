class BaseImporter:

    def preview(self, filename):
        raise NotImplementedError

    def load(self, filename):
        raise NotImplementedError