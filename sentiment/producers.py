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
    
    with open("producer_debug.log", "a") as f:
        f.write(f"\n--- Batch for keyword: {keyword} ---\n")
        for post in data:
            post["keyword"] = keyword
            pid = post.get('post_id')
            f.write(f"Sending post: {pid} | Keyword: {keyword}\n")
            sentiment_producer.send(settings.KAFKA_SENTIMENT_TOPIC, post)
    
    sentiment_producer.flush()
