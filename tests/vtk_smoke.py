"""Run separately on a Windows desktop: python -B -m tests.vtk_smoke."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile


def run_phase(directory, phase):
    os.environ["QT_QPA_PLATFORM"] = "windows"
    import numpy as np
    import pandas as pd
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication
    from gui.MainWindow import MainWindow
    from importers.CsvImporter import CsvImporter
    from models.PointCloud import PointCloud
    from models.Surface import Surface
    from models.ColorMap import ColorMap
    from models.project.Project import Project
    from importers.ObjectFactory import build_table_object

    app = QApplication([])
    settings = QSettings(str(directory / "settings.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings=settings, restore_session=phase == "reopen")
    window.show()
    app.processEvents()
    fixture = Path(__file__).resolve().parents[1] / "data" / "example_points.csv"
    try:
        if phase == "create":
            source = directory / "input.csv"
            source.write_bytes(fixture.read_bytes())
            project = Project.create(directory / "demo")
            cloud = PointCloud("Example", source, CsvImporter().load(source))
            cloud.set_mapping("x", "y", "z", ["class", "sfgr"])
            project.import_file(cloud)
            project.set_appearance(cloud, mode="points", color="#e11d48", point_size=12,
                                   outline=True, outline_color="#182b49", line_width=2,
                                   opacity=0.65)
            project.set_axis_scale(1.5, 0.75, 2)
            surface = Surface("Triangle")
            surface.vertices = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]])
            surface.faces = np.array([3, 0, 1, 2])
            project.import_file(surface)
            wells_source = directory / "wells.csv"
            wells_data = pd.DataFrame({"id": ["A", "A", "B", "B"],
                "x": [10, 10, 20, 20], "y": [0, 0, 0, 0],
                "z": [0, -10, 0, -15], "gamma": [1, 2, 3, 4]})
            wells_data.to_csv(wells_source, index=False)
            project.import_file(build_table_object("wellfile", wells_data, wells_source,
                                                   ("x", "y", "z"), ("gamma",), "id"))
            cube_source = directory / "cube.csv"
            cube_data = pd.DataFrame([(x, y, z, x + y + z) for x in (0, 1)
                                      for y in (0, 1) for z in (0, 1)],
                                     columns=["x", "y", "z", "value"])
            cube_data.to_csv(cube_source, index=False)
            project.import_file(build_table_object("cube", cube_data, cube_source,
                                                   ("x", "y", "z"), ("value",)))
            window.set_project(project)
            well_file = project.well_files()[0]
            assert set(window.viewer.well_label_actors) == {well.uuid for well in well_file.wells}
            data_actors = {well.uuid: window.viewer.actors[well.uuid] for well in well_file.wells}
            window._change_appearance(well_file.uuid, {
                "label_color": "#00ff00", "label_font": "courier", "label_size": 23})
            for well in well_file.wells:
                assert window.viewer.actors[well.uuid] is data_actors[well.uuid]
                label = window.viewer.well_label_actors[well.uuid]
                text = label.GetMapper().GetInputConnection(0, 0).GetProducer().GetTextProperty()
                assert text.GetFontSize() == 23
                assert text.GetFontFamilyAsString() == "Courier"
                assert np.allclose(text.GetColor(), (0, 1, 0))
            window._change_appearance(well_file.uuid, {"label_visible": False})
            assert not window.viewer.well_label_actors
            window._change_appearance(well_file.uuid, {"label_visible": True})
            assert set(window.viewer.well_label_actors) == {well.uuid for well in well_file.wells}
            window.select_object(well_file.uuid)
            assert window.appearance_editor.fields.isEnabled()
            actors_before = {well.uuid: window.viewer.actors[well.uuid] for well in well_file.wells}
            meshes_before = {well.uuid: actors_before[well.uuid].mapper.dataset for well in well_file.wells}
            window._change_appearance(well_file.uuid, {
                "color_map": ColorMap.default("gamma", 1, 4), "opacity": 0.7})
            assert all(window.viewer.actors[well.uuid] is not actors_before[well.uuid]
                       and window.viewer.actors[well.uuid].mapper.dataset is meshes_before[well.uuid]
                       and window.viewer.actors[well.uuid].mapper.scalar_visibility
                       for well in well_file.wells)
            window.set_container_visibility(well_file, False)
            assert all(well.uuid not in window.viewer.actors for well in well_file.wells)
            window.set_container_visibility(well_file, True)
            assert all(well.uuid in window.viewer.actors for well in well_file.wells)
            window.set_theme("dark")
            assert window.viewer.plotter.background_color.hex_rgb == "#1a2028"
            assert window.save_project()
            source.unlink()
            wells_source.unlink()
            cube_source.unlink()
        else:
            assert window.project is not None
            assert not (directory / "input.csv").exists()
            cloud = window.project.pointclouds()[0]
            surface = window.project.surfaces()[0]
            assert window.project.well_files()[0].well_ids == ("A", "B")
            assert window.project.well_files()[0].appearance.color_map.field == "gamma"
            assert window.project.well_files()[0].appearance.label_font == "courier"
            assert set(window.viewer.well_label_actors) == {well.uuid for well in window.project.wells()}
            assert len(window.project.wells()) == 2
            assert window.project.cubes()[0].is_regular_grid
            assert window.theme == "dark"
            assert window.viewer.plotter.background_color.hex_rgb == "#1a2028"
            pd.testing.assert_frame_equal(cloud.dataframe, CsvImporter().load(fixture), check_exact=True)
        app.processEvents()
        assert cloud.uuid in window.viewer.actors
        assert surface.uuid in window.viewer.actors
        assert len(window.viewer.actors) == 5
        for well in window.project.wells():
            assert window.viewer.actors[well.uuid].mapper.dataset.lines.size > 0
            assert window.viewer.actors[well.uuid].mapper.scalar_visibility
            assert window.viewer.actors[well.uuid].prop.opacity == 0.7
        assert window.viewer.actors[window.project.cubes()[0].uuid].prop.style == "Points"
        assert cloud.appearance.color == "#e11d48"
        assert cloud.appearance.outline
        assert window.viewer.actors[cloud.uuid].prop.point_size == 16
        assert window.viewer.actors[cloud.uuid].prop.opacity == 0.65
        assert window.viewer.actors[cloud.uuid].scale == (1.5, 0.75, 2)
        assert surface.uuid in window.viewer.actors
        assert window.viewer.actors[surface.uuid].scale == (1.5, 0.75, 2)
        assert window.viewer.scene_bounds is not None
        window.viewer.plotter.render()
        print(f"Qt/VTK {phase} OK: {cloud.point_count} points, 5 typed actors", flush=True)
    finally:
        window.close()
        app.processEvents()


def main():
    if len(sys.argv) == 3:
        run_phase(Path(sys.argv[2]), sys.argv[1])
        return
    with tempfile.TemporaryDirectory() as temporary:
        for phase in ("create", "reopen"):
            subprocess.run(
                [sys.executable, "-B", "-m", "tests.vtk_smoke", phase, temporary],
                cwd=Path(__file__).resolve().parents[1], check=True, timeout=30,
            )
    print("Full application restart OK (two independent Python processes)")


if __name__ == "__main__":
    main()
