from abc import ABC, abstractmethod


class LanguageModelEngine(ABC):
    @abstractmethod
    async def load(self): ...

    @abstractmethod
    def stream(self, messages, max_tokens): ...

    @abstractmethod
    async def unload(self): ...
