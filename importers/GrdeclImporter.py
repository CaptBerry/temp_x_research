"""Read a GRDECL corner-point grid with repeat counts and relative INCLUDEs."""

from pathlib import Path
import re

import numpy as np

from models.CornerPointGrid import CornerPointGrid


_TOKEN = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|/|[^\s/]+")
_FLAGS = {"GRID", "RUNSPEC", "EDIT", "PROPS", "SOLUTION", "SCHEDULE", "END",
          "METRIC", "FIELD", "FIELD_US", "FIELD_USA", "NOECHO", "ECHO"}
_REJECT = {"MAPAXES", "BOX", "ENDBOX", "EQUALS", "COPY", "ADD", "MULTIPLY",
           "OPERATE", "CARFIN", "ENDFIN", "EXTERNAL_FILE"}
_NON_PROPERTY = {"SPECGRID", "DIMENS", "COORD", "ZCORN", "ACTNUM", "GRIDUNITS",
                 "GRIDUNIT", "MAPUNITS", "GRIDOPTS", "GRIDFILE", "PINCH", "MINPV",
                 "FAULTS", "MULTFLT", "GDORIENT", "TITLE", "START"}


def _blocks(path, stack=()):
    path = Path(path).resolve()
    if path in stack or len(stack) >= 16:
        raise ValueError(f"Цикл или слишком глубокая вложенность INCLUDE: {path}")
    try:
        content = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        content = path.read_text(encoding="cp1251")
    content = re.sub(r"--[^\n]*", "", content)
    tokens = _TOKEN.findall(content)
    position = 0
    while position < len(tokens):
        keyword = tokens[position].upper()
        position += 1
        if keyword == "/":
            continue
        if keyword in _FLAGS:
            continue
        values = []
        while position < len(tokens) and tokens[position] != "/":
            values.append(tokens[position])
            position += 1
        if position == len(tokens):
            raise ValueError(f"Блок {keyword} не завершён символом / в {path.name}.")
        position += 1
        if keyword == "INCLUDE":
            if len(values) != 1:
                raise ValueError("INCLUDE должен содержать один путь к файлу.")
            include = values[0].strip("'\"")
            yield from _blocks(path.parent / include, (*stack, path))
        else:
            yield keyword, values


def _numbers(values, keyword, expected, default=None):
    result = []
    for token in values:
        count, separator, raw = token.partition("*")
        if separator:
            if not count.isdigit() or int(count) < 1:
                raise ValueError(f"Некорректное повторение в {keyword}: {token}")
            repeat = int(count)
            raw = raw or (str(default) if default is not None else "")
        else:
            repeat = 1
            raw = token
        try:
            number = float(raw.replace("D", "E").replace("d", "e"))
        except ValueError as error:
            raise ValueError(f"Некорректное число в {keyword}: {token}") from error
        if len(result) + repeat > expected:
            raise ValueError(f"Слишком много значений в {keyword}: ожидалось {expected}.")
        result.extend([number] * repeat)
    if len(result) != expected:
        raise ValueError(f"Число значений в {keyword}: {len(result)}, ожидалось {expected}.")
    return np.asarray(result, dtype=np.float64)


def load_grdecl(path):
    blocks = {}
    for keyword, values in _blocks(path):
        if keyword in _REJECT:
            raise ValueError(f"GRDECL-операция {keyword} пока не поддерживается; сетка не импортирована.")
        if keyword in blocks:
            raise ValueError(f"Повторный блок {keyword} в GRDECL не поддерживается.")
        blocks[keyword] = values
    dimensions = []
    for keyword in ("SPECGRID", "DIMENS"):
        if keyword in blocks:
            try:
                dimensions.append(tuple(int(value) for value in blocks[keyword][:3]))
            except (ValueError, TypeError) as error:
                raise ValueError(f"Некорректные размеры в {keyword}.") from error
    if not dimensions or len(dimensions[0]) != 3 or any(d != dimensions[0] for d in dimensions):
        raise ValueError("Не указан SPECGRID/DIMENS или их размеры не совпадают.")
    nx, ny, nz = dimensions[0]
    if min(nx, ny, nz) <= 0:
        raise ValueError("Размеры сетки должны быть положительными.")
    for keyword in ("COORD", "ZCORN"):
        if keyword not in blocks:
            raise ValueError(f"В GRDECL отсутствует обязательный блок {keyword}.")
    shape = (nz, ny, nx)
    coord = _numbers(blocks["COORD"], "COORD", 6 * (nx + 1) * (ny + 1))
    zcorn = _numbers(blocks["ZCORN"], "ZCORN", 8 * nx * ny * nz)
    actnum = (_numbers(blocks["ACTNUM"], "ACTNUM", nx * ny * nz, default=1)
              if "ACTNUM" in blocks else np.ones(nx * ny * nz))
    if not np.isfinite(actnum).all() or not np.isin(actnum, (0, 1)).all():
        raise ValueError("ACTNUM должен содержать только 0 и 1.")
    properties = {}
    for keyword, values in blocks.items():
        if keyword in _NON_PROPERTY or keyword in _FLAGS:
            continue
        # Unknown numeric cell arrays are useful geological properties; reject
        # non-array records instead of silently misrepresenting their values.
        try:
            properties[keyword] = _numbers(values, keyword, nx * ny * nz).reshape(shape)
        except ValueError as error:
            raise ValueError(f"Блок {keyword} не является массивом параметров ячеек: {error}") from error
    grid = CornerPointGrid((nx, ny, nz), coord.reshape(ny + 1, nx + 1, 2, 3),
                           zcorn.reshape(2 * nz, 2 * ny, 2 * nx),
                           actnum.reshape(shape).astype(bool), properties)
    grid.validate()
    return grid
