import colorama
from logging import getLogger, LogRecord, Formatter, INFO, StreamHandler

from tqdm import tqdm

class CustomAsyncHandler(StreamHandler):
    def __init__(self):
        super().__init__()
        colorama.init()
        self._colors = {
            "INFO": colorama.Fore.GREEN,
            "WARNING": colorama.Fore.YELLOW,
            "ERROR": colorama.Fore.RED,
            "CRITICAL": colorama.Fore.MAGENTA
        }
        self._reset = colorama.Style.RESET_ALL

    def get_color(self, levelname: str) -> str:
        return self._colors.get(levelname, '')

    def format(self, record: LogRecord) -> str:
        message = super().format(record)
        return f"{self.get_color(record.levelname)}{message}{self._reset}"

    def emit(self, record):
        try:
            msg = self.format(record)
            tqdm.write(msg)
            self.flush()
        except Exception:
            self.handleError(record)
            
logger = getLogger("asx_app_logger")
logger.setLevel(INFO)

handler = CustomAsyncHandler()
formatter = Formatter("%(asctime)s | %(levelname)s | %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)