"""Construct typed project objects from imported tabular or mesh data."""

from pathlib import Path

import numpy as np
import pyvista as pv

from models.DataCube import DataCube
from models.PointCloud import PointCloud
from models.Surface import Surface
from models.Well import Well
from models.WellFile import WellFile
from importers.GrdeclImporter import load_grdecl
from importers.PointCloudGridBuilder import build_grid_from_centres
from importers.LayeredGridBuilder import build_layered_cube


TABLE_TYPES = ("pointcloud", "well", "wellfile", "cube", "surface")
MESH_SUFFIXES = {".vtk", ".vtp", ".stl", ".obj", ".ply", ".vtu", ".vts"}


def build_table_object(object_type, dataframe, source, coordinates, parameters=(), id_column=None,
                       surface_kind="general", cube_geometry="nodes", grid_dimensions=(0, 0, 0),
                       singleton_size=1.0, connect_existing=True, layer_column=None,
                       roof_column=None, base_column=None):
    if object_type not in TABLE_TYPES:
        raise ValueError("Неизвестный тип импортируемого объекта.")
    source = Path(source)
    parameters = [name for name in parameters if object_type not in ("well", "wellfile") or name != id_column]
    if object_type == "cube" and cube_geometry == "layered":
        return build_layered_cube(dataframe, source, coordinates, parameters,
                                  layer_column, roof_column, base_column,
                                  dimensions=grid_dimensions, singleton_size=singleton_size)
    if object_type == "cube" and cube_geometry != "nodes":
        grid, used_method = build_grid_from_centres(
            dataframe, coordinates, parameters, method=cube_geometry,
            dimensions=grid_dimensions, singleton_size=singleton_size,
            connect_existing=connect_existing)
        cube = DataCube(source.stem, source)
        cube.set_corner_grid(grid)
        cube.metadata.update({"source_point_count": len(dataframe),
                              "grid_build_method": used_method,
                              "singleton_axis_size": singleton_size,
                              "connect_existing_cells": connect_existing})
        cube.validate()
        return cube
    if object_type in ("well", "wellfile") and id_column in coordinates:
        raise ValueError("Колонка ID скважины должна отличаться от X, Y и Z.")
    if object_type == "surface":
        cloud = PointCloud(source.stem, source, dataframe)
        cloud.set_mapping(*coordinates)
        cloud.validate()
        if cloud.point_count < 3:
            raise ValueError("Для поверхности требуются минимум три точки.")
        mesh = pv.PolyData(cloud.coordinates).delaunay_2d()
        if mesh.n_cells == 0:
            raise ValueError("Не удалось построить поверхность из точек XYZ.")
        obj = Surface(source.stem, source)
        obj.surface_kind = surface_kind
        obj.vertices = np.asarray(mesh.points)
        obj.faces = np.asarray(mesh.faces)
        obj.validate()
        return obj
    if object_type == "wellfile":
        if id_column is None or id_column not in dataframe.columns:
            raise ValueError("Для файла скважин выберите колонку идентификатора.")
        if dataframe[id_column].isna().any() or dataframe[id_column].astype(str).str.strip().eq("").any():
            raise ValueError("Идентификатор скважины не должен быть пустым.")
        collection = WellFile(source.stem, id_column)
        identifiers = dataframe[id_column].astype(str).str.strip()
        for identifier, rows in dataframe.groupby(identifiers, sort=False):
            well = Well(str(identifier), source, rows.reset_index(drop=True).copy(), str(identifier))
            well.set_mapping(*coordinates, parameters=parameters)
            well.validate()
            collection._add(well)
        if not collection.wells:
            raise ValueError("Файл не содержит скважин.")
        return collection
    if object_type == "well":
        if id_column is None or id_column not in dataframe.columns:
            raise ValueError("Для скважины выберите колонку идентификатора.")
        identifiers = dataframe[id_column].dropna().astype(str).str.strip().unique()
        if len(identifiers) != 1 or dataframe[id_column].isna().any() or not identifiers[0]:
            raise ValueError("Для одной скважины в файле должен быть ровно один идентификатор.")
        obj = Well(str(identifiers[0]), source, dataframe.copy(), str(identifiers[0]))
    elif object_type == "cube":
        obj = DataCube(source.stem, source, dataframe.copy())
    else:
        obj = PointCloud(source.stem, source, dataframe.copy())
    obj.set_mapping(*coordinates, parameters=parameters)
    obj.validate()
    return obj


def build_mesh_surface(source, surface_kind="general"):
    source = Path(source)
    if source.suffix.lower() not in MESH_SUFFIXES:
        raise ValueError("Неподдерживаемый формат поверхности.")
    mesh = pv.read(source).extract_surface(algorithm="dataset_surface").triangulate()
    if mesh.n_points < 3 or mesh.n_cells == 0:
        raise ValueError("Файл не содержит граней поверхности.")
    surface = Surface(source.stem, source)
    surface.surface_kind = surface_kind
    surface.vertices = np.asarray(mesh.points)
    surface.faces = np.asarray(mesh.faces)
    surface.validate()
    return surface


def build_corner_point_cube(source, grid=None):
    source = Path(source)
    if source.suffix.lower() != ".grdecl":
        raise ValueError("Для corner-point grid выберите файл .grdecl.")
    cube = DataCube(source.stem, source)
    cube.set_corner_grid(grid if grid is not None else load_grdecl(source))
    cube.validate()
    return cube
