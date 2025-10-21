import yaml

with open("toolbars.yaml", 'r') as f:
    TOOLBAR_ACTIONS = yaml.safe_load(f)

print(TOOLBAR_ACTIONS)
__all__ = ["TOOLBAR_ACTIONS"]

