"""Scriptable stand-ins for a PydanticAI streamed run.

``agent.override(model=...)`` cannot express what E07 needs to test: the
override wins over the per-run ``model=`` argument, so the fallback retry would
run the same model twice and be invisible, and a real ``TestModel`` cannot be
told to die after exactly one token. These fakes implement only the surface
``assistant.views._sse_response`` actually touches, so a change in that surface
breaks them loudly instead of letting a stale stub keep passing.
"""


class FakeUsage:
    def __init__(self, input_tokens=100, output_tokens=50):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class FakeStream:
    """One scripted attempt.

    ``fail_after`` is the index of the chunk at which the provider dies, so
    ``fail_after=0`` fails before anything reaches the client (retryable) and
    ``fail_after=1`` fails once one token is already rendered (not retryable).
    """

    def __init__(self, chunks, fail_after=None, usage=None):
        self._chunks = chunks
        self._fail_after = fail_after
        self._usage = usage if usage is not None else FakeUsage()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def stream_text(self, delta=True):
        for i, chunk in enumerate(self._chunks):
            if self._fail_after is not None and i >= self._fail_after:
                raise RuntimeError("provider died mid-stream")
            yield chunk

    def usage(self):
        return self._usage

    def all_messages(self):
        return []


class FakeRunResult:
    """What a non-streamed PydanticAI run returns, as `extract_receipt` uses it."""

    def __init__(self, output, usage=None):
        self.output = output
        self._usage = usage if usage is not None else FakeUsage()

    def usage(self):
        return self._usage


class FakeAgent:
    """An agent whose behaviour per attempt is keyed by the model name asked for."""

    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.calls = []
        # Per attempt, so a test can assert the fallback got its OWN provider
        # quirks rather than the primary's.
        self.settings = []

    def run_stream(self, prompt, *, deps, message_history, model=None, model_settings=None):
        self.calls.append(model)
        self.settings.append(model_settings)
        return self.behaviour[model]
