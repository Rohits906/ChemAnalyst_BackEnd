import json
from django.conf import settings
from confluent_kafka import Producer

def delivery_report(err, msg):
    """ Called once for each message produced to indicate delivery result.
        Triggered by poll() or flush(). """
    if err is not None:
        print(f'Message delivery failed: {err}')
    else:
        print(f'Message delivered to {msg.topic()} [{msg.partition()}]')


class KafkaProducerClient:
    def __init__(self):
        self._producer = None

    @property
    def producer(self):
        if self._producer is None:
            conf = {
                'bootstrap.servers': settings.KAFKA_BOOTSTRAP_SERVERS,
            }
            self._producer = Producer(conf)
        return self._producer

    def produce_message(self, topic, message):
        """
        Produces a JSON message to a Kafka topic.
        """
        try:
            # Produce the message
            self.producer.produce(
                topic, 
                value=json.dumps(message).encode('utf-8'), 
                callback=delivery_report
            )
            # Wait up to 1 second for events. Callbacks will be invoked during
            # this method call if the message is acknowledged.
            self.producer.poll(0)
        except Exception as e:
            print(f"Failed to produce message to {topic}: {str(e)}")

    def flush(self):
        """
        Wait for any outstanding messages to be delivered and delivery report
        callbacks to be triggered.
        """
        if self._producer:
            self._producer.flush()

# Singleton instance for easy import across the Django app
kafka_producer = KafkaProducerClient()
