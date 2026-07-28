# services/storage.py


class StorageService:
    def save(self, key, value):
        print(f"Saving {key}")

    def load(self, key, default=None):
        print(f"Loading {key}")

        return default
