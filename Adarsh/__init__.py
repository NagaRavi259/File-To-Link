# (c) adarsh-goel

import logging
import time

logger = logging.getLogger("Adarsh")

StartTime = time.time()
__version__ = 1.1
logger.debug("Adarsh package imported (version %s, StartTime %s)", __version__, StartTime)
