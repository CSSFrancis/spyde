# Configuration file for the Sphinx documentation builder.
from __future__ import annotations

import importlib.util


# -- Project information -----------------------------------------------------
project = "spyde"
copyright = "2025, Direct Electron"
author = "Direct Electron"

release = "0.0.1"

# -- General configuration ---------------------------------------------------
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.intersphinx",
    "sphinx.ext.napoleon",
    "sphinx_gallery.gen_gallery",
]
templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# -- Options for HTML output -------------------------------------------------
# Ensure pydata-sphinx-theme is available
if importlib.util.find_spec("pydata_sphinx_theme") is None:
    raise RuntimeError("pydata-sphinx-theme is not installed in this environment")

html_theme = "pydata_sphinx_theme"
#html_static_path = ["_static"]
html_theme_options = {
    "logo": {
        "image_light": "_static/spyde_banner_light.svg",
        "image_dark": "_static/spyde_banner_dark.svg",
    }
}

html_favicon = "_static/icon.svg"


master_doc = "index"

# -- Autodoc / Autosummary ---------------------------------------------------
autosummary_ignore_module_all = False
autosummary_imported_members = True
autodoc_typehints_format = "short"
autodoc_default_options = {"show-inheritance": True}
autosummary_generate = True

# -- Sphinx Gallery ----------------------------------------------------------
sphinx_gallery_conf = {
    "examples_dirs": "../examples",
    "gallery_dirs": "examples",
    "filename_pattern": "^((?!sgskip).)*$",
    "ignore_pattern": "_sgskip.py",
    "backreferences_dir": "spyde",
    "doc_module": ("spyde",),
    "reference_url": {"spyde": None},
    "image_scrapers": ("spyde.qt_scrapper.qt_sg_scraper", ),
    'capture_repr': (),  # Disable text output capture
}
