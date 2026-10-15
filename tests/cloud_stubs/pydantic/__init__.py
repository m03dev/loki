class BaseModel:
    def __init__(self, **kw):
        for k, v in type(self).__dict__.items():
            if not k.startswith("_") and not callable(v): setattr(self, k, v)
        for k, v in kw.items(): setattr(self, k, v)
    def model_dump(self, **k): return dict(self.__dict__)
