"""Apply display settings to an existing actor without rebuilding geometry."""

import numpy as np
import pyvista as pv
from models.DataCube import DataCube
from models.Surface import Surface
from renderers.point_cells import CELL_SOURCE_ROW
from renderers.display_points import DISPLAY_CELLS, display_field


PALETTE_SCALARS = "_xsearch_palette_values"


def filtered_palette_mesh(mesh, obj):
    """Return only the primitives inside a palette's optional value interval."""
    palette = obj.appearance.color_map
    if palette is None or palette.filter_range is None:
        return mesh
    derived = DISPLAY_CELLS in mesh.field_data
    cell_scalars = derived or isinstance(obj, DataCube) and obj.is_corner_point or obj.appearance.mode == "cells"
    data = mesh.cell_data if cell_scalars else mesh.point_data
    values = (np.asarray(data[display_field(palette.field)], dtype=float) if derived
              else np.asarray(obj.color_values(palette.field), dtype=float))
    if cell_scalars and CELL_SOURCE_ROW in data:
        values = values[np.asarray(data[CELL_SOURCE_ROW], dtype=np.int64)]
    data[PALETTE_SCALARS] = values
    if isinstance(obj, Surface):
        # Clip faces at the requested values so the remaining surface reaches
        # the interval boundary instead of disappearing one whole face early.
        lower, upper = palette.filter_range
        clipped = mesh.clip_scalar(scalars=PALETTE_SCALARS, value=lower, invert=False)
        return clipped.clip_scalar(scalars=PALETTE_SCALARS, value=upper, invert=True)
    return mesh.threshold(palette.filter_range, scalars=PALETTE_SCALARS,
                          preference="cell" if cell_scalars else "point",
                          all_scalars=True)


def apply_color_map(actor, obj):
    palette = obj.appearance.color_map
    mapper = actor.mapper
    if palette is None:
        mapper.scalar_visibility = False
        mapper.Modified()
        actor.Modified()
        return
    derived = DISPLAY_CELLS in mapper.dataset.field_data
    cell_scalars = derived or isinstance(obj, DataCube) and obj.is_corner_point or obj.appearance.mode == "cells"
    data = mapper.dataset.cell_data if cell_scalars else mapper.dataset.point_data
    # Thresholding copies the selected scalar values onto its output. The
    # original object's array is longer than a filtered mesh's point/cell set.
    values = (np.asarray(data[PALETTE_SCALARS], dtype=float)
              if palette.filter_range is not None else
              np.asarray(data[display_field(palette.field)], dtype=float) if derived else
              obj.color_values(palette.field))
    if palette.filter_range is None and cell_scalars and CELL_SOURCE_ROW in data:
        values = np.asarray(values)[np.asarray(data[CELL_SOURCE_ROW], dtype=np.int64)]
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
    prop.style = ("points" if appearance.mode == "spheres" else
                  "surface" if appearance.mode in ("cells", "corner_grid") else
                  "wireframe" if appearance.mode == "grid_wireframe" else appearance.mode)
    prop.color = appearance.color
    prop.edge_color = appearance.outline_color
    prop.line_width = appearance.line_width
    outline = (appearance.prism_outline if appearance.mode in ("cells", "corner_grid")
               and appearance.prism_outline is not None else appearance.outline)
    prop.show_edges = appearance.mode in ("surface", "cells", "corner_grid") and outline
    prop.render_points_as_spheres = appearance.mode == "spheres"
    prop.lighting = appearance.mode in ("surface", "cells", "corner_grid", "spheres")
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
