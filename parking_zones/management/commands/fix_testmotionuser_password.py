from django.core.management.base import BaseCommand
from django.contrib.auth.models import User


class Command(BaseCommand):
    help = 'Sets an unusable password for testmotionuser and any users with blank password fields.'

    def handle(self, *args, **options):
        empty_password_users = User.objects.filter(password='')
        count = 0
        for user in empty_password_users:
            user.set_unusable_password()
            user.save(update_fields=['password'])
            count += 1
            self.stdout.write(self.style.SUCCESS(
                f"Successfully set unusable password for user '{user.username}'. Legitimate password reset is now required."
            ))

        # Explicit check for testmotionuser
        motion_user = User.objects.filter(username='testmotionuser').first()
        if motion_user and motion_user.has_usable_password() and motion_user.password == '':
            motion_user.set_unusable_password()
            motion_user.save(update_fields=['password'])
            self.stdout.write(self.style.SUCCESS(
                f"Successfully set unusable password for user 'testmotionuser'."
            ))

        if count == 0:
            self.stdout.write(self.style.NOTICE("No users found with empty password fields."))
