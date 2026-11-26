from abc import ABC, abstractmethod


class SpeechRecognitionEngine(ABC):
    @abstractmethod
    def load(self): ...

    @abstractmethod
    def transcribe(self, audio_path, language=None): ...

    @abstractmethod
    def unload(self): ...
