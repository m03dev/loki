class _Fn:
    def __init__(self, name="", arguments=""): self.name=name; self.arguments=arguments
class ChatCompletionMessageToolCall:
    def __init__(self, id="", type="function", function=None):
        self.id=id; self.type=type; f=function or {}
        self.function=_Fn(**f) if isinstance(f, dict) else f
    def model_dump(self, **k): return {"id": self.id, "type": self.type, "function": {"name": self.function.name, "arguments": self.function.arguments}}
