import pyvista as pv


class PointsRenderer:

    def render(self, points):

        return pv.PolyData(points.coordinates)
