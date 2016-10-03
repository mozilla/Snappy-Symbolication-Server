import os
import logging
from logging.handlers import RotatingFileHandler

LOG_FORMAT = logging.Formatter('%(asctime)s\t%(levelname)s\t%(message)s')


class logLevel:
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    CRITICAL = logging.CRITICAL


class Logger:
    def __init__(self):
        self._log = logging.getLogger()

        streamHandler = logging.StreamHandler()
        streamHandler.setFormatter(LOG_FORMAT)
        self._log.addHandler(streamHandler)

    def configure(self, path, level, maxFiles, maxFileBytes):
        path = os.path.realpath(path)
        directory = os.path.dirname(path)
        try:
            if not os.path.exists(directory):
                os.makedirs(directory)

            rotatingHandler = RotatingFileHandler(filename=path, mode='a',
                                                  maxBytes=maxFileBytes,
                                                  backupCount=(maxFiles - 1))
            rotatingHandler.setFormatter(LOG_FORMAT)
            self._log.addHandler(rotatingHandler)
        except OSError as e:
            self._log.error("Invalid path '%s': %s.", path, e)
            self._log.error("Logging on screen only.")
        except IOError as e:
            self._log.error("Could not configure file logger: %s", e)
            self._log.error("Check the log path '%s'. Logging on screen only.", path)
        self.setLevel(level)

    def setLevel(self, level):
        self._log.setLevel(level)

    def log(self, level, message, remoteIP=None):
        pid = os.getpid()
        remoteIPString = " REMOTE IP={}".format(remoteIP) if remoteIP else ""
        self._log.log(level, "%d\t%s%s", pid, message, remoteIPString)

logger = Logger()
