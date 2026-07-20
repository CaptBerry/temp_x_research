import pyvista as pv


class SurfaceRenderer:


    def render(self, surface):

        mesh = pv.PolyData(
            surface.vertices,
            surface.faces
        )

        return mesh
