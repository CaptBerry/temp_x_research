class SceneCamera:

    def __init__(
            self,
            position=None,
            focal_point=None,
            view_up=None,
            clipping_range=None
    ):

        self.position = position
        self.focal_point = focal_point
        self.view_up = view_up
        self.clipping_range = clipping_range

    def save_from_plotter(self, plotter):

        camera = plotter.camera

        self.position = tuple(camera.position)
        self.focal_point = tuple(camera.focal_point)
        self.view_up = tuple(camera.up)
        self.clipping_range = tuple(camera.clipping_range)

    def apply_to_plotter(self, plotter):

        if self.position is not None:
            plotter.camera.position = self.position

        if self.focal_point is not None:
            plotter.camera.focal_point = self.focal_point

        if self.view_up is not None:
            plotter.camera.up = self.view_up

        if self.clipping_range is not None:
            plotter.camera.clipping_range = self.clipping_range

    def focus_on_bounds(self, plotter, bounds):

        if bounds is None:
            return

        plotter.reset_camera(bounds=bounds)
        self.save_from_plotter(plotter)
