# Generated by Django 5.0.7 on 2024-08-03 16:55

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('alertrix', '0004_remove_directmessage_matrixroom_ptr_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='widget',
            name='activation_secret',
            field=models.CharField(default='', max_length=4, verbose_name='activation secret'),
            preserve_default=False,
        ),
    ]
