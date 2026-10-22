from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [
        ("detect", "0002_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.AddField(model_name="videolog", name="event_id",
                            field=models.UUIDField(null=True, blank=True, unique=True)),
        migrations.AddField(model_name="videolog", name="description",
                            field=models.TextField(blank=True, default="")),
        migrations.AddField(model_name="videolog", name="detected_at",
                            field=models.DateTimeField(null=True, blank=True, db_index=True)),
        migrations.AddField(model_name="videolog", name="reported_by",
                            field=models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.SET_NULL,
                                                    related_name="bodycam_events", to=settings.AUTH_USER_MODEL)),
    ]
