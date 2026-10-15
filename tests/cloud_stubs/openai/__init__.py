# Offline stand-in for running LOKI's suites without PyPI (cloud workspace only).
class OpenAIError(Exception): pass
class APIStatusError(OpenAIError):
    def __init__(self, message="", response=None, body=None, status_code=0):
        super().__init__(message); self.message=message; self.status_code=status_code; self.body=body
class APIConnectionError(OpenAIError): pass
class APITimeoutError(APIConnectionError): pass
class RateLimitError(APIStatusError): pass
class _Completions:
    async def create(self, **kw): raise APIConnectionError("stub: no network")
class _Chat:
    def __init__(self): self.completions=_Completions()
class AsyncOpenAI:
    def __init__(self, *a, **k): self.chat=_Chat(); self.base_url=k.get("base_url"); self.api_key=k.get("api_key")
class OpenAI(AsyncOpenAI): pass
__version__="0-stub"
