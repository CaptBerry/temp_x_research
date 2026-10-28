"""Desktop smoke test: corner-point cells, palette and full application restart."""

import os
os.environ["QT_QPA_PLATFORM"] = "windows"

from dataclasses import replace
from pathlib import Path
import subprocess
import sys
import tempfile


def phase(directory, reopen):
    import numpy as np
    import pandas as pd
    from PyQt6.QtCore import QSettings, QTimer
    from PyQt6.QtWidgets import QApplication

    from gui.MainWindow import MainWindow
    from gui.dialogs.PaletteDialog import PaletteDialog
    from importers.ObjectFactory import build_corner_point_cube, build_table_object
    from models.ColorMap import ColorMap, ColorStop
    from models.project.Project import Project
    from renderers.appearance import PALETTE_SCALARS
    from tests.test_corner_point_grid import write_fixture

    app = QApplication([])
    settings = QSettings(str(directory / "settings.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings=settings, restore_session=reopen)
    window.show()
    app.processEvents()
    try:
        if not reopen:
            source = write_fixture(directory)
            project = Project.create(directory / "project")
            cube = project.import_file(build_corner_point_cube(source))
            project.set_appearance(cube, color_map=ColorMap.default("PORO", 0.1, 0.4),
                                   opacity=0.75)
            centres_source = directory / "centres.csv"
            centres = pd.DataFrame([(x, y, z, x + y + z) for z in (0., 1.)
                                    for y in (0., 1.) for x in (0., 1.)],
                                   columns=["x", "y", "z", "grade"])
            centres.to_csv(centres_source, index=False)
            generated = project.import_file(build_table_object(
                "cube", centres, centres_source, ("x", "y", "z"), ("grade",),
                cube_geometry="auto"))
            project.set_appearance(generated, color_map=ColorMap.default("grade", 0, 3))
            window.set_project(project)
            assert window.save_project()
            source.unlink()
            centres_source.unlink()
            (directory / "properties.inc").unlink()
        else:
            assert window.project is not None
            cube = next(item for item in window.project.cubes() if item.name == "faulted")
            generated = next(item for item in window.project.cubes() if item.name == "centres")
        actor = window.viewer.actors[cube.uuid]
        mesh = actor.mapper.dataset
        assert mesh.n_cells == 3
        assert mesh.n_points < 24
        assert actor.prop.style == "Surface"
        assert actor.prop.opacity == 0.75
        assert actor.mapper.scalar_visibility
        np.testing.assert_allclose(mesh.cell_data[PALETTE_SCALARS], [0.1, 0.3, 0.4])
        assert PALETTE_SCALARS not in mesh.point_data
        generated_actor = window.viewer.actors[generated.uuid]
        assert generated_actor.mapper.dataset.n_cells == 8
        assert generated_actor.mapper.scalar_visibility
        assert generated.corner_grid.properties["N_POINTS"].sum() == 8
        plotter = window.viewer.plotter
        assert not plotter.scalar_bars, tuple(plotter.scalar_bars)
        frames = []
        observer = plotter.render_window.AddObserver(
            "StartEvent", lambda *_: frames.append((len(window.viewer.actors), len(plotter.scalar_bars)))
        )
        try:
            window.update_3d_viewer()
        finally:
            plotter.render_window.RemoveObserver(observer)
        assert frames == [(2, 0)], frames
        logarithmic = replace(ColorMap.default("grade", 1, 3), value_scale="log")
        window._change_appearance(generated.uuid, {"color_map": logarithmic})
        generated_actor = window.viewer.actors[generated.uuid]
        assert generated_actor.mapper.lookup_table.log_scale
        assert np.isnan(generated_actor.mapper.dataset.cell_data[PALETTE_SCALARS]).sum() == 1
        midpoint = generated_actor.mapper.lookup_table.map_value(np.sqrt(3))
        assert midpoint[0] > 0.9 and midpoint[1] > 0.9 and midpoint[2] < 0.1, midpoint
        actor = window.viewer.actors[cube.uuid]
        actor.visibility = False
        plotter.view_xy()
        plotter.reset_camera()
        def recolor(color):
            palette = ColorMap("grade", 0, 3, (ColorStop(0, color), ColorStop(100, color)))
            window._change_appearance(generated.uuid, {"color_map": palette})
            app.processEvents()
            actor = window.viewer.actors[generated.uuid]
            actor.prop.lighting = False
            image = plotter.screenshot(return_img=True)[:, :, :3].astype(int)
            expected = np.asarray(tuple(int(color[index:index + 2], 16)
                                        for index in (1, 3, 5)))
            return int(np.count_nonzero(np.max(np.abs(image - expected), axis=2) < 5))
        assert recolor("#0000ff") > 100
        assert recolor("#00ff00") > 100
        original_exec = PaletteDialog.exec
        def edit_exec(dialog):
            def edit_and_close():
                dialog.palette = ColorMap("grade", 0, 3,
                                          (ColorStop(0, "#0000ff"), ColorStop(100, "#0000ff")))
                dialog.accept()
            QTimer.singleShot(0, edit_and_close)
            return original_exec(dialog)
        PaletteDialog.exec = edit_exec
        try:
            window._open_palette(generated.uuid)
        finally:
            PaletteDialog.exec = original_exec
        app.processEvents()
        image = plotter.screenshot(return_img=True)[:, :, :3].astype(int)
        blue = np.asarray((0, 0, 255))
        assert np.count_nonzero(np.max(np.abs(image - blue), axis=2) < 5) > 100
        window.viewer.plotter.render()
        print(f"Corner-point Qt/VTK {'reopen' if reopen else 'create'} OK", flush=True)
    finally:
        if window.project is not None:
            window.project.modified = False
        window.close()
        app.processEvents()


def main():
    if len(sys.argv) == 3:
        phase(Path(sys.argv[2]), sys.argv[1] == "reopen")
        return
    with tempfile.TemporaryDirectory() as temporary:
        for stage in ("create", "reopen"):
            subprocess.run([sys.executable, "-B", "-m", "tests.vtk_corner_point_smoke",
                            stage, temporary], check=True, timeout=35)
    print("Corner-point project survived a full application restart")


if __name__ == "__main__":
    main()
