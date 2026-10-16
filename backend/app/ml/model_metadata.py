"""Describes a trained model artifact."""
from dataclasses import asdict, dataclass, field


@dataclass
class ModelMetadata:
    version: str
    trained_at: str
    schema_hash: str
    data_source: str           # "synthetic" or the CSV path
    is_synthetic: bool
    n_rows: int
    n_fraud: int
    threshold: float
    metrics: dict = field(default_factory=dict)
    random_seed: int = 42
    model_type: str = "RandomForestClassifier"

    def to_dict(self):
        return asdict(self)
