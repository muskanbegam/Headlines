import logging
from app import app, scheduled_scrape
from apscheduler.schedulers.blocking import BlockingScheduler
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('worker.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    logger.info("🚀 Starting scheduler worker...")
    
    scheduler = BlockingScheduler()
    
    scheduler.add_job(
        id='worker_scraping_job',
        func=scheduled_scrape,
        trigger='cron',
        hour=8,
        minute=43,
        misfire_grace_time=3600,
        next_run_time=datetime.now()  # Run immediately on startup for first run
    )
    
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("🛑 Scheduler shutting down gracefully...")
    except Exception as e:
        logger.error(f"💥 Scheduler failed: {str(e)}")
        raise