import logging
import os

def setup_logging(log_prefix="app", app_logger_name="app_log"):
    logger = logging.getLogger(app_logger_name)
    logger.setLevel(logging.INFO)
    
    # 避免重复绑定handler
    if not logger.handlers:
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        ch.setFormatter(formatter)
        logger.addHandler(ch)
        
    return logger