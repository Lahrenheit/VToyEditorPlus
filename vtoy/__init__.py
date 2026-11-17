"""vtoy - tools for the Virtual Toys in-house engine (Torrente series): file formats, editor and viewer."""
from .binutil import VStr
from .scn import Scene, ModuleRecord
from .opt import OptMap
from .hm import HeightMap
from .tex import Texture
from .nfo import NfoModel
from .keys import KeyFile
from . import modules, vpk

__version__ = "0.1.0"
