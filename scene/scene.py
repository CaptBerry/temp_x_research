from scene.camera import SceneCamera
from scene.scene_object import SceneObject


class Scene:

    def __init__(self):

        self.objects = []
        self.camera = SceneCamera()


    def add(self, obj: SceneObject):

        self.objects.append(obj)


    def remove(self, obj):

        self.objects.remove(obj)


    def clear(self):

        self.objects.clear()