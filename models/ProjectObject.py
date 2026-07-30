from uuid import uuid4


class ProjectObject:

    def __init__(self, name="Object"):

        self.id = str(uuid4())

        self.name = name

        self.parent = None

        self.visible = True

        self.metadata = {}

    @property
    def project(self):

        node = self

        while node.parent is not None:
            node = node.parent

        return node