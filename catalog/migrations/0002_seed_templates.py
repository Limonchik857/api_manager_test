from django.db import migrations

from catalog.services import TEMPLATE_DEFINITIONS


def seed(apps, schema_editor):
    WorkflowTemplate = apps.get_model('catalog', 'WorkflowTemplate')
    for item in TEMPLATE_DEFINITIONS:
        WorkflowTemplate.objects.update_or_create(
            name=item['name'],
            defaults={
                'description': item['description'],
                'category': item['category'],
                'definition': item['definition'],
            },
        )


def unseed(apps, schema_editor):
    WorkflowTemplate = apps.get_model('catalog', 'WorkflowTemplate')
    WorkflowTemplate.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]