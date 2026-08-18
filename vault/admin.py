from django.contrib import admin

from .models import Secret


@admin.register(Secret)
class SecretAdmin(admin.ModelAdmin):
    list_display = ('name', 'owner', 'masked', 'created_at')
    search_fields = ('name', 'owner__username')
    readonly_fields = ('encrypted_value', 'created_at', 'updated_at')

    @admin.display(description='Value')
    def masked(self, obj):
        return f'{obj.encrypted_value[:12]}…{obj.encrypted_value[-6:]}'