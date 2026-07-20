from uuid import uuid4


class SceneObject:

    def __init__(self, name="Object"):

        self.id = str(uuid4())

        self.name = name

        self.visible = True