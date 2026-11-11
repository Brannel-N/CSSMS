from django.urls import include, path

urlpatterns = [
    path("", include("portal.urls")),
]

handler403 = "portal.views.permission_denied"
handler404 = "portal.views.page_not_found"
