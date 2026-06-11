import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

project = "Minecraft LogBrain"
author = "Brain AI Systems"
copyright = "2026"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
]

templates_path = ["_templates"]
exclude_patterns: list[str] = ["_build", "Thumbs.db", ".DS_Store"]

html_theme = "furo"
html_title = "Minecraft LogBrain"
html_theme_options = {
    "sidebar_hide_name": False,
    "navigation_with_keys": True,
}
autodoc_typehints = "description"
autodoc_member_order = "bysource"
