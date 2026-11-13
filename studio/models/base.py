from abc import ABC, abstractmethod


class ModelAdapter(ABC):
    """A module receives frozen, provider-neutral decisions and writes a new checkpoint.

    Each decision is {state, questions, expected, row_id, language, slices}.
    Each prediction is {row_id, question, expected, predicted, confidence,
    language, slices}. Confidence means probability of the selected class.
    No adapter may change a dataset, split assignment, or active registry entry.
    """

    @abstractmethod
    def train(self, training, calibration, output, settings, progress):
        """Return calibration/training metadata. Write only inside output."""

    @abstractmethod
    def evaluate(self, checkpoint, decisions, settings, progress):
        """Return prediction records and timing. Never train on these decisions."""

    @abstractmethod
    def load(self, checkpoint, settings):
        """Load a checkpoint for inference; return an opaque runtime."""

    @abstractmethod
    def predict(self, runtime, state, questions):
        """Return a System One compatible answer object."""
