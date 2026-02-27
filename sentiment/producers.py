from kafka import KafkaProducer
import json
from django.conf import settings

try:
    sentiment_producer = KafkaProducer(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )
except Exception as e:
    print(f"Could not connect to Kafka: {e}")
    sentiment_producer = None

def add_to_sentiment_quene(data, keyword="N/A"):
    if not sentiment_producer:
        print("Kafka producer is not initialized.")
        return
    
    for post in data:
        post["keyword"] = keyword
        print(f"Sending post to Kafka: {post.get('post_id')}")
        sentiment_producer.send(settings.KAFKA_SENTIMENT_TOPIC, post)
    
    sentiment_producer.flush()
