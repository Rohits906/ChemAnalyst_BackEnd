import logging
from celery import shared_task
from django.utils import timezone
from django.core.cache import cache
from .models import Platform, PlatformFetchTask
from .services import fetch_platform_data

logger = logging.getLogger(__name__)

@shared_task
def trigger_all_platforms_sync():
    """
    Periodic task that triggers sync for all active platforms.
    This serves as the batch processor.
    """
    logger.info("Starting hourly batch platform sync trigger")
    platforms = Platform.objects.filter(is_active=True)
    
    for platform in platforms:
        sync_platform_task.delay(str(platform.id))
    
    return f"Triggered sync for {platforms.count()} platforms"

@shared_task(bind=True, max_retries=3)
def sync_platform_task(self, platform_id):
    """
    Atomic task worker to sync a single platform.
    Uses distributed Redis locking to prevent duplicate processing.
    """
    # Create a unique lock key for this platform
    lock_key = f"lock_sync_platform_{platform_id}"
    
    # Try to acquire lock for 15 minutes (900 seconds)
    # This prevents 3-4 workers from hitting the same API simultaneously.
    # .add() returns True if the key was set (lock acquired), False if it already exists.
    if not cache.add(lock_key, "locked", timeout=900):
        logger.info(f"Task for platform {platform_id} is already being processed by another worker. Skipping.")
        return "Skipped (locked)"
    
    try:
        platform = Platform.objects.get(id=platform_id)
        logger.info(f"Processing sync for {platform.name}: {platform.channel_name}")
        
        # Create fetch task record for audit/visibility
        fetch_task = PlatformFetchTask.objects.create(
            platform=platform,
            user=platform.user,
            task_type="hourly_sync",
            status="processing",
            started_at=timezone.now()
        )
        
        # Perform the actual data fetch
        try:
            success, message = fetch_platform_data(platform)
            
            fetch_task.status = "completed" if success else "failed"
            fetch_task.error_message = message if not success else ""
            fetch_task.completed_at = timezone.now()
            fetch_task.save()
            
            logger.info(f"Sync result for {platform.id}: {message}")
            return f"Success: {message}"
            
        except Exception as e:
            fetch_task.status = "failed"
            fetch_task.error_message = str(e)
            fetch_task.completed_at = timezone.now()
            fetch_task.save()
            logger.error(f"Error in fetch_platform_data for {platform_id}: {e}", exc_info=True)
            raise self.retry(exc=e, countdown=60) # Retry after 1 minute on crash
            
    except Platform.DoesNotExist:
        logger.error(f"Platform {platform_id} not found")
        return "Failed (not found)"
    finally:
        # Always release the lock
        cache.delete(lock_key)
