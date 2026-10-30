"""Local card UI attribute recognition, independent of layout and catalog."""

from .config import RecognitionConfig, load_config
from .models import CardAttributesResult, RecognitionError
from .normalizer import normalize_card

__all__ = ["RecognitionConfig", "RecognitionError", "CardAttributesResult", "load_config", "normalize_card"]
