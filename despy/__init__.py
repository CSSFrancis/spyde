import yaml

# Load the configuration .yaml files at package initialization

with open("toolbars.yaml", 'r') as f:
    TOOLBAR_ACTIONS = yaml.safe_load(f)

with open("metadata_widget.yaml", 'r') as f:
    METADATA_WIDGET_CONFIG = yaml.safe_load(f)
print(METADATA_WIDGET_CONFIG)

__all__ = ["TOOLBAR_ACTIONS", "METADATA_WIDGET_CONFIG"]


