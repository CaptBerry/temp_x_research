import json
from pathlib import Path
from .Folder import Folder
from .Surface import Surface
from .PointCloud import PointCloud


class Project:
    def __init__(self, name="New Project", path=None):
        self.name = name
        self.path = path
        self.work_path = None  # Путь к папке work
        self.source_path = None  # Путь к папке source
        self.root = Folder(name)
        self.modified = False
        self.version = "1.0"  # Версия формата проекта

    def add(self, obj, parent=None):
        if parent is None:
            parent = self.root
        parent.add(obj)
        self.modified = True

    def remove(self, obj):
        if obj.parent is not None:
            obj.parent.remove(obj)
            self.modified = True

    def clear(self):
        self.root.children.clear()
        self.modified = True

    def get_project_file_path(self) -> Path:
        """Получить путь к файлу проекта"""
        if self.path:
            return Path(self.path) / "project.json"
        return None

    def save(self, path=None):
        """Сохранить проект в JSON файл"""
        if path:
            self.path = str(path)
            self.work_path = str(Path(path) / "work")
            self.source_path = str(Path(path) / "source")

        if not self.path:
            raise ValueError("Путь к проекту не указан")

        project_file = self.get_project_file_path()

        # Создаем структуру папок
        Path(self.path).mkdir(parents=True, exist_ok=True)
        Path(self.work_path).mkdir(exist_ok=True)
        Path(self.source_path).mkdir(exist_ok=True)

        # Формируем данные для сохранения
        data = {
            "version": self.version,
            "name": self.name,
            "path": self.path,
            "work_path": self.work_path,
            "source_path": self.source_path,
            "tree": self.root.to_dict(),
            "metadata": {
                "modified": self.modified,
                "created": self._get_timestamp()
            }
        }

        # Сохраняем в файл
        with open(project_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        self.modified = False
        return project_file

    @classmethod
    def load(cls, file_path):
        """Загрузить проект из JSON файла"""
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Создаем объект проекта
        project = cls(
            name=data["name"],
            path=data["path"]
        )
        project.work_path = data.get("work_path")
        project.source_path = data.get("source_path")
        project.version = data.get("version", "1.0")

        # Восстанавливаем дерево проекта
        if "tree" in data:
            project.root = Folder.from_dict(data["tree"])
            # Обновляем parent для всех элементов
            project._update_parents(project.root)

        project.modified = False
        return project

    def _update_parents(self, node):
        """Рекурсивно обновить parent для всех детей"""
        for child in node.children:
            child.parent = node
            if hasattr(child, 'children'):
                self._update_parents(child)

    def _get_timestamp(self):
        """Получить текущую временную метку"""
        from datetime import datetime
        return datetime.now().isoformat()

    def find_by_name(self, name, node=None):
        """Найти объект по имени (поиск в глубину)"""
        if node is None:
            node = self.root

        # Проверяем текущий узел
        if node.name == name:
            return node

        # Проверяем детей
        if hasattr(node, 'children'):
            for child in node.children:
                result = self.find_by_name(name, child)
                if result:
                    return result
        return None

    def find_by_path(self, path_parts, node=None):
        """Найти объект по пути (список имен)"""
        if node is None:
            node = self.root

        if not path_parts:
            return node

        current_name = path_parts[0]
        if node.name != current_name:
            return None

        if len(path_parts) == 1:
            return node

        # Ищем среди детей
        if hasattr(node, 'children'):
            for child in node.children:
                result = self.find_by_path(path_parts[1:], child)
                if result:
                    return result
        return None

    def get_all_objects(self, node=None):
        """Получить все объекты проекта (плоский список)"""
        if node is None:
            node = self.root

        objects = []
        if hasattr(node, 'children'):
            for child in node.children:
                objects.append(child)
                if hasattr(child, 'children'):
                    objects.extend(self.get_all_objects(child))
        return objects