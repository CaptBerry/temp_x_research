"""Desktop smoke test for layered-cube actors and a full application restart."""

import os
os.environ["QT_QPA_PLATFORM"] = "windows"

from pathlib import Path
import subprocess
import sys
import tempfile


def phase(directory, reopen):
    import pandas as pd
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication

    from gui.MainWindow import MainWindow
    from importers.ObjectFactory import build_table_object
    from models.ColorMap import ColorMap
    from models.LayeredCube import LayeredCube
    from models.project.Project import Project

    app = QApplication([])
    settings = QSettings(str(directory / "settings.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings=settings, restore_session=False)
    window.show()
    app.processEvents()
    try:
        if not reopen:
            source = directory / "layers.tsv"
            table = pd.DataFrame({
                "X": [0., 1., 0., 1.], "Y": [0.] * 4,
                "AbsRoof": [-100., -100., -200., -200.],
                "AbsBase": [-200., -200., -300., -300.],
                "layer": [30, 30, 31, 31], "УЭС": [10., 20., 30., 40.],
            })
            table.to_csv(source, sep="\t", index=False)
            project = Project.create(directory / "project")
            model = project.import_file(build_table_object(
                "cube", table, source, ("X", "Y", "AbsRoof"), ("УЭС",),
                cube_geometry="layered", layer_column="layer",
                roof_column="AbsRoof", base_column="AbsBase"))
            project.set_visible(model.get_layer(31), False)
            project.save()
            source.unlink()
        else:
            project = Project.open(directory / "project" / "project.json")
            model = next(obj for obj in project.walk() if isinstance(obj, LayeredCube))
        window.set_project(project)
        window.select_object(model.uuid)
        assert window.appearance_editor.fields.isEnabled()
        if not reopen:
            layer_actor = window.viewer.actors[model.get_layer(30).uuid]
            window._change_appearance(model.uuid, {
                "color_map": ColorMap.default("УЭС", 10, 40), "opacity": 0.65})
            assert window.viewer.actors[model.get_layer(30).uuid] is layer_actor
            assert layer_actor.mapper.scalar_visibility
            project.save()
        else:
            assert model.appearance.color_map.field == "УЭС"
        assert len(model.layers) == 2
        assert model.get_layer(30).uuid in window.viewer.actors
        assert model.get_layer(31).uuid not in window.viewer.actors
        assert window.viewer.actors[model.get_layer(30).uuid].mapper.dataset.n_cells == 2
        assert window.viewer.actors[model.get_layer(30).uuid].mapper.scalar_visibility
        assert window.viewer.actors[model.get_layer(30).uuid].prop.opacity == 0.65
        plotter = window.viewer.plotter
        assert not plotter.scalar_bars, tuple(plotter.scalar_bars)
        project.set_visible(model.get_layer(31), True)
        frames = []
        observer = plotter.render_window.AddObserver(
            "StartEvent", lambda *_: frames.append((len(window.viewer.actors), len(plotter.scalar_bars)))
        )
        try:
            window.update_3d_viewer()
        finally:
            plotter.render_window.RemoveObserver(observer)
        assert frames == [(2, 0)], frames
        project.set_visible(model.get_layer(31), False)
        window.update_3d_viewer()
        project.set_visible(model, False)
        window.update_3d_viewer()
        assert model.get_layer(30).uuid not in window.viewer.actors
        project.set_visible(model, True)
        window.update_3d_viewer()
        assert model.get_layer(30).uuid in window.viewer.actors
        print(f"Layered cube Qt/VTK {'reopen' if reopen else 'create'} OK", flush=True)
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
            subprocess.run([sys.executable, "-B", "-m", "tests.vtk_layered_smoke",
                            stage, temporary], check=True, timeout=35)
    print("Layered cube survived a full application restart")


if __name__ == "__main__":
    main()
