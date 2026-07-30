from .Folder import Folder

class Project:

    def __init__(self, name="New Project"):

        self.name = name
        self.path = None

        self.root = Folder(name)

        self.modified = False

    def add(self, obj, parent=None):

        if parent is None:
            parent = self.root

        parent.add(obj)
        self.modified = True

    def remove(self, obj):

        if obj.parent is not None:
            obj.parent.remove(obj)
            self.modified = True

    def clear(self):

        self.root.children.clear()
        self.modified = True