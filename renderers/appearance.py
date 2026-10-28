"""Apply display settings to an existing actor without rebuilding geometry."""

import numpy as np
import pyvista as pv
from models.DataCube import DataCube


PALETTE_SCALARS = "_xsearch_palette_values"


def apply_color_map(actor, obj):
    palette = obj.appearance.color_map
    mapper = actor.mapper
    if palette is None:
        mapper.scalar_visibility = False
        mapper.Modified()
        actor.Modified()
        return
    values = obj.color_values(palette.field)
    cell_scalars = isinstance(obj, DataCube) and obj.is_corner_point
    data = mapper.dataset.cell_data if cell_scalars else mapper.dataset.point_data
    if palette.value_scale == "log":
        # Logarithms are undefined for zero and negative samples. Show them
        # with the lookup table's NaN color instead of the lowest palette color.
        values = np.asarray(values, dtype=float).copy()
        values[values <= 0] = np.nan
    data[PALETTE_SCALARS] = values
    mapper.set_active_scalars(PALETTE_SCALARS, preference="cell" if cell_scalars else "point")
    table = pv.LookupTable(values=palette.rgba())
    table.scalar_range = (palette.minimum, palette.maximum)
    table.log_scale = palette.value_scale == "log"
    table.nan_color = "#808080"
    mapper.lookup_table = table
    mapper.scalar_range = (palette.minimum, palette.maximum)
    mapper.scalar_visibility = True
    # An existing VTK mapper may retain its previous scalar-color texture.
    # Invalidate the data and lookup table when editing a palette in place.
    mapper.dataset.Modified()
    mapper.lookup_table.Modified()
    mapper.Modified()
    actor.Modified()


def set_point_viewport(actor, viewport):
    actor.GetShaderProperty().GetFragmentCustomUniforms().SetUniform4f("pointViewport", viewport)


def apply_appearance(actor, appearance, viewport):
    # Sprite coordinates are only meaningful for point primitives. Remove
    # previous shader replacements before switching to a mesh representation.
    actor.clear_point_sprite_shape()
    actor.clear_shader_replacements()
    prop = actor.prop
    prop.opacity = appearance.opacity
    prop.style = "points" if appearance.mode == "spheres" else appearance.mode
    prop.color = appearance.color
    prop.edge_color = appearance.outline_color
    prop.line_width = appearance.line_width
    prop.show_edges = appearance.mode == "surface" and appearance.outline
    prop.render_points_as_spheres = appearance.mode == "spheres"
    prop.lighting = appearance.mode in ("surface", "spheres")
    prop.point_size = appearance.point_size

    if appearance.mode not in ("points", "spheres"):
        return

    # The selected point size is the fill diameter; the border grows outward.
    outlined = appearance.mode == "points" and appearance.outline
    diameter = appearance.point_size + (2 * appearance.line_width if outlined else 0)
    prop.point_size = diameter
    set_point_viewport(actor, viewport)
    # Derive coordinates explicitly so markers and VTK's native sphere shader
    # do not depend on gl_PointCoord support in Windows OpenGL contexts.
    actor.add_shader_replacement(
        "vertex", "//VTK::PositionVC::Dec",
        "//VTK::PositionVC::Dec\nflat out vec2 pointCenterNDC;\n",
    )
    actor.add_shader_replacement(
        "vertex", "//VTK::PositionVC::Impl",
        "//VTK::PositionVC::Impl\npointCenterNDC = gl_Position.xy / gl_Position.w;\n",
    )
    actor.add_shader_replacement(
        "fragment", "//VTK::PositionVC::Dec",
        "//VTK::PositionVC::Dec\nflat in vec2 pointCenterNDC;\n",
    )
    actor.add_shader_replacement(
        "fragment", "//VTK::Depth::Impl",
        "vec2 pointCenter = pointViewport.xy + (pointCenterNDC + 1.0) * 0.5 * pointViewport.zw;\n"
        f"vec2 pointUV = (gl_FragCoord.xy - pointCenter) / {diameter:.9f} + 0.5;\n"
        "pointUV.y = 1.0 - pointUV.y;\n//VTK::Depth::Impl\n",
    )
    if appearance.mode == "spheres":
        actor.add_shader_replacement("fragment", "gl_PointCoord", "pointUV",
                                     replace_first=False, replace_all=True)
        return

    distance = "length(p)" if appearance.point_shape == "circle" else "max(abs(p.x), abs(p.y))"
    code = (
        "//VTK::Color::Impl\n"
        "vec2 p = pointUV * 2.0 - 1.0;\n"
        f"float pointDistance = {distance};\n"
        "if (pointDistance > 1.0) discard;\n"
    )
    if outlined:
        rgb = ", ".join(f"{component:.9f}" for component in pv.Color(appearance.outline_color).float_rgb)
        threshold = appearance.point_size / diameter
        code += (
            f"if (pointDistance > {threshold:.9f}) {{\n"
            f"  ambientColor = vec3({rgb});\n"
            "  diffuseColor = vec3(0.0);\n"
            "}\n"
        )
    actor.add_shader_replacement("fragment", "//VTK::Color::Impl", code)
