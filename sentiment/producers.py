from kafka import KafkaProducer
import json
from django.conf import settings

try:
    sentiment_producer = KafkaProducer(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        api_version=(0, 10, 2),
    )
except Exception as e:
    print(f"Could not connect to Kafka: {e}")
    sentiment_producer = None

def add_to_sentiment_queue(data, keyword="N/A"):
    if not sentiment_producer:
        print("Kafka producer is not initialized. Using local file fallback: mock_kafka_queue.jsonl")
        try:
            with open("mock_kafka_queue.jsonl", "a", encoding="utf-8") as f:
                for post in data:
                    post["keyword"] = keyword
                    f.write(json.dumps(post) + "\n")
            print(f"Successfully wrote {len(data)} items to mock_kafka_queue.jsonl")
        except Exception as e:
            print(f"Failed to write to local fallback: {e}")
        return
    
    for post in data:
        post["keyword"] = keyword
        print(f"Sending post to Kafka: {post.get('post_id')}")
        sentiment_producer.send(settings.KAFKA_SENTIMENT_TOPIC, post)
    
    sentiment_producer.flush()
