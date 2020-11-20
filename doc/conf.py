#!/usr/bin/env python3

import toml
import mock
import os
import sys

sys.path.insert(0, os.path.abspath(".."))
sys.path.insert(0, os.path.abspath("../slapd"))


class Mock(mock.MagicMock):
    @classmethod
    def __getattr__(cls, name):
        return mock.MagicMock()


MOCK_MODULES = ["ldap"]
sys.modules.update((mod_name, Mock()) for mod_name in MOCK_MODULES)

config = toml.load("../pyproject.toml")

# -- General configuration ------------------------------------------------


extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.doctest",
    "sphinx.ext.graphviz",
    "sphinx.ext.intersphinx",
    "sphinx.ext.todo",
    "sphinx.ext.viewcode",
    "sphinx_issues",
]

templates_path = ["_templates"]
source_suffix = [".rst"]
master_doc = "index"
project = "slapd"
copyright = "2020, python-ldap"
author = "python-ldap"

release = config["tool"]["poetry"]["version"]
version = "%s.%s" % tuple(map(int, release.split(".")[:2]))
language = None
exclude_patterns = []
pygments_style = "sphinx"
todo_include_todos = False

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}

issues_uri = "https://github.com/python-ldap/python-slapd/issues/{issue}"
issues_pr_uri = "https://github.com/python-ldap/python-slapd/pull/{pr}"
issues_commit_uri = "https://github.com/python-ldap/python-slapd/commit/{commit}"

# -- Options for HTML output ----------------------------------------------

html_theme = "sphinx_rtd_theme"
html_static_path = []


# -- Options for HTMLHelp output ------------------------------------------

htmlhelp_basename = "slapddoc"


# -- Options for LaTeX output ---------------------------------------------

latex_elements = {}
latex_documents = [
    (master_doc, "slapd.tex", "slapd Documentation", "python-ldap", "manual")
]

# -- Options for manual page output ---------------------------------------

man_pages = [(master_doc, "slapd", "slapd Documentation", [author], 1)]

# -- Options for Texinfo output -------------------------------------------

texinfo_documents = [
    (
        master_doc,
        "slapd",
        "slapd Documentation",
        author,
        "slapd",
        " Control a slapd process in a pythonic way",
        "Miscellaneous",
    )
]
