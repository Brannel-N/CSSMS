from datetime import date

from .models import Notification


def template_context(request):
    unread_notifications = 0
    if request.user.is_authenticated:
        unread_notifications = Notification.objects.filter(
            user=request.user, read=False
        ).count()
    return {
        "current_user": request.user,
        "today": date.today(),
        "unread_notifications": unread_notifications,
    }
