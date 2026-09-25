"""Goatbeat: a type-safe, distributed periodic task scheduler."""

from pkgutil import extend_path

# Editable installs give each workspace package its own sys.path entry; extending __path__
# lets goatbeat.core, goatbeat.postgres, ... resolve as portions of this regular package.
__path__ = extend_path(__path__, __name__)
