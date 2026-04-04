from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("wallets", "0001_initial"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="wallet",
            name="currency",
        ),
    ]