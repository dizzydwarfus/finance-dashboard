import logging
from logging import INFO


class MyLogger:
    def __init__(self, name: str = __name__, level: str = 'debug', log_file: str = 'logs.log'):
        # Initialize logger
        self.logging_level = logging.DEBUG if level == 'debug' else logging.INFO
        self.scrape_logger = logging.getLogger(name)
        self.scrape_logger.setLevel(self.logging_level)

        # Check if the self.scrape_logger already has handlers to avoid duplicate logging.
        if not self.scrape_logger.hasHandlers():
            # Create a file handler
            file_handler = logging.FileHandler(log_file, mode='a')
            file_handler.setLevel(self.logging_level)

            # Create a stream handler
            stream_handler = logging.StreamHandler()
            stream_handler.setLevel(self.logging_level)

            # Create a logging format
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(formatter)
            stream_handler.setFormatter(formatter)

            # Add the handlers to the self.scrape_logger
            self.scrape_logger.addHandler(file_handler)
            self.scrape_logger.addHandler(stream_handler)
