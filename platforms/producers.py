from kafka import KafkaProducer
import json
from django.conf import settings
from datetime import datetime

try:
    platform_producer = KafkaProducer(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
        acks='all',
        retries=3,
    )
except Exception as e:
    print(f"Could not connect to Kafka: {e}")
    platform_producer = None

def queue_platform_fetch(platform_id, task_type="update"):
    """Queue a platform data fetch task"""
    if not platform_producer:
        print("Kafka producer is not initialized.")
        return False
    
    message = {
        "platform_id": str(platform_id),
        "task_type": task_type,
        "timestamp": datetime.now().isoformat(),
    }
    
    try:
        platform_producer.send(
            settings.KAFKA_PLATFORM_FETCH_TOPIC, 
            message
        )
        platform_producer.flush()
        return True
    except Exception as e:
        print(f"Failed to queue platform fetch: {e}")
        return False

def queue_batch_platform_fetch(platform_ids, task_type="update"):
    """Queue multiple platform fetch tasks"""
    if not platform_producer:
        print("Kafka producer is not initialized.")
        return False
    
    success_count = 0
    for platform_id in platform_ids:
        message = {
            "platform_id": str(platform_id),
            "task_type": task_type,
            "timestamp": datetime.now().isoformat(),
        }
        
        try:
            platform_producer.send(
                settings.KAFKA_PLATFORM_FETCH_TOPIC, 
                message
            )
            success_count += 1
        except Exception as e:
            print(f"Failed to queue platform {platform_id}: {e}")
    
    platform_producer.flush()
    return success_count > 0