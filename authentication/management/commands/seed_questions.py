from django.core.management.base import BaseCommand
from authentication.models import SecurityQuestion

class Command(BaseCommand):
    help = 'Seed initial security questions'

    def handle(self, *args, **options):
        questions = [
            "What is your mother's maiden name?",
            "What was the name of your first pet?",
            "What was the name of your first school?",
            "In what city were you born?",
            "What is your favorite book?",
            "What was your childhood nickname?",
            "What is the name of your favorite childhood friend?",
            "In what city did your parents meet?",
            "What was the make and model of your first car?"
        ]

        count = 0
        for q_text in questions:
            obj, created = SecurityQuestion.objects.update_or_create(
                question=q_text
            )
            if created:
                count += 1
                self.stdout.write(self.style.SUCCESS(f"Created question: {q_text}"))
        
        if count == 0:
            self.stdout.write(self.style.WARNING("No new questions were added (all already exist)."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Successfully seeded {count} security questions!"))