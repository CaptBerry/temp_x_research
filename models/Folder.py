from .ProjectObject import ProjectObject


class Folder(ProjectObject):

    def __init__(self, name="Folder"):

        super().__init__(name)

        self.children = []

    def add(self, obj):

        obj.parent = self

        self.children.append(obj)

    def remove(self, obj):

        self.children.remove(obj)

        obj.parent = None

    def clear(self):

        for child in self.children:
            child.parent = None

        self.children.clear()

    def __iter__(self):

        return iter(self.children)

    def __len__(self):

        return len(self.children)