"""Entry point - run the agent framework server."""
import uvicorn
from config import HOST, PORT
from core.logging_config import configure_logging, get_logger

configure_logging(log_level="INFO", json_format=False)
logger = get_logger("run")

if __name__ == "__main__":
    logger.info("Starting Agent Framework", host=HOST, port=PORT)
    uvicorn.run("api.main:app", host=HOST, port=PORT, reload=False, log_level="info")
