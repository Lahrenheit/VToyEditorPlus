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
APP_NAME = "VToyEditor Plus+"
APP_AUTHOR = "Lahrenheit"
APP_URL = "https://github.com/Lahrenheit/VToyEditorPlus"
APP_BASED_ON = "Based on Patoke's VToyEditor"
APP_REV = "v1.0.21"
APP_REV_DATE = "22/11/2026 16:20"
APP_VERSION = APP_REV                      # the version (About, update check, the .exe's properties:
#                                            version_info.txt is written from it by tools/make_version_info.py)
