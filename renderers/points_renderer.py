import numpy as np
import pyvista as pv


class PointsRenderer:

    def render(self, points):

        mesh = pv.PolyData(points.coordinates)

        vertex_count = points.coordinates.shape[0]
        mesh.verts = np.column_stack((
            np.ones(vertex_count, dtype=np.int32),
            np.arange(vertex_count, dtype=np.int32)
        )).ravel()

        return mesh
