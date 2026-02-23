from django.db import models

class ContactMessage(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField()
    message = models.TextField()
    timestamp = models.DateTimeField()

    def __str__(self):
        return self.name