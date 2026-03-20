import logging
from celery import shared_task
from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


@shared_task
def trigger_all_sentiment_sync():
    """
    Hourly Celery Beat task: re-fetch & re-analyze social media posts
    for every user's saved keywords, across all platforms.
    Mirrors the pattern used by trigger_all_platforms_sync in platforms/tasks.py.
    """
    from .models import User_Keyword

    users_with_keywords = (
        User_Keyword.objects.select_related("user")
        .values_list("user_id", flat=True)
        .distinct()
    )

    triggered = 0
    for user_id in users_with_keywords:
        sync_sentiment_for_user.delay(user_id)
        triggered += 1

    logger.info(f"[SentimentSync] Queued sentiment sync for {triggered} user(s)")
    return f"Triggered sentiment sync for {triggered} users"


@shared_task(bind=True, max_retries=2)
def sync_sentiment_for_user(self, user_id):
    """
    Fetch fresh social media posts for all keywords belonging to a single user
    and push them into the sentiment analysis queue.
    """
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        logger.error(f"[SentimentSync] User {user_id} not found")
        return "Failed (user not found)"

    from .models import User_Keyword
    from .producers import add_to_sentiment_quene

    keywords = User_Keyword.objects.filter(user=user).values_list("keyword", flat=True)
    if not keywords:
        logger.info(f"[SentimentSync] No keywords for user {user.username}, skipping")
        return "Skipped (no keywords)"

    # Reuse SocialMediaSearchView's perform_search logic
    try:
        from sentiment.views import SocialMediaSearchView
        searcher = SocialMediaSearchView()

        for keyword in keywords:
            try:
                result = searcher.perform_search(keyword, hours=None, user=user)
                logger.info(
                    f"[SentimentSync] '{keyword}' for {user.username}: {result}"
                )
            except Exception as kw_err:
                logger.warning(
                    f"[SentimentSync] Failed for keyword '{keyword}': {kw_err}"
                )

        return f"Synced {len(keywords)} keyword(s) for {user.username}"

    except Exception as e:
        logger.error(
            f"[SentimentSync] Error for user {user.username}: {e}", exc_info=True
        )
        raise self.retry(exc=e, countdown=120)
