from importlib.resources import files
import yaml
import logging

logger = logging.getLogger(__name__)

# Load the configuration .yaml files at package initialization

with files(__package__).joinpath("toolbars.yaml").open("r", encoding="utf-8") as f:
    TOOLBAR_ACTIONS = yaml.safe_load(f)

with files(__package__).joinpath("metadata_widget.yaml").open(
    "r", encoding="utf-8"
) as f:
    METADATA_WIDGET_CONFIG = yaml.safe_load(f)
logger.debug("Loaded metadata widget config: %s", METADATA_WIDGET_CONFIG)

__all__ = ["TOOLBAR_ACTIONS", "METADATA_WIDGET_CONFIG"]


__version__ = "0.0.1"
