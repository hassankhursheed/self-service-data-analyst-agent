"""Load versioned YAML config files into Pydantic models with clear error messages."""

from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError


class ConfigFileError(Exception):
    """A config file is missing, is not valid YAML, or does not match its schema."""


def load_yaml_model[M: BaseModel](path: Path, model: type[M]) -> M:
    """Parse ``path`` and validate it as ``model``; errors name the file and the field."""
    try:
        data = yaml.safe_load(path.read_text("utf-8"))
    except FileNotFoundError as exc:
        raise ConfigFileError(f"{path}: file not found") from exc
    except yaml.YAMLError as exc:
        raise ConfigFileError(f"{path}: invalid YAML: {exc}") from exc
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or '(root)'}: {err['msg']}"
            for err in exc.errors()
        )
        raise ConfigFileError(f"{path}: {problems}") from exc
