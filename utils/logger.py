import logging
from logging import INFO


def get_logger(name: str, level=INFO, file: str = r'C:\Users\lianz\Python\finance-dashboard\scraper.log'):
    logger = logging.getLogger(name)
    logger.setLevel(logging.level)

    # Check if the logger already has handlers to avoid duplicate logging.
    if not logger.hasHandlers():
        # Create a file handler
        handler = logging.FileHandler(file)
        handler.setLevel(logging.level)

        # Create a logging format
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)

        # Add the handler to the logger
        logger.addHandler(handler)

    return logger
