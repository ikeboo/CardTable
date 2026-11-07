from threading import RLock


class Closure:
    """Registry for objects whose lifecycle is managed by a Dealer."""

    _instance = None
    _objects = []
    _lock = RLock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def add(cls, obj):
        with cls._lock:
            if not any(current is obj for current in cls._objects):
                cls._objects.append(obj)

    @property
    def objects(self):
        with self._lock:
            return tuple(self._objects)

    def close(self, obj):
        with self._lock:
            index = next(
                (
                    index
                    for index, current in enumerate(self._objects)
                    if current is obj
                ),
                None,
            )
            if index is None:
                return
            self._objects.pop(index)
        obj.stop()

    def close_all(self):
        with self._lock:
            objects = tuple(reversed(self._objects))
            self._objects.clear()
        for obj in objects:
            obj.stop()
