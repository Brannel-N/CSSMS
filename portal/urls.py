from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("profile/", views.profile, name="profile"),
    path("profile-photo/<int:user_id>/", views.profile_photo, name="profile_photo"),
    path("presence/", views.presence, name="presence"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("students/", views.students, name="students"),
    path("students/<int:sid>/", views.student_detail, name="student_detail"),
    path("students/<int:sid>/edit/", views.edit_student, name="edit_student"),
    path("students/<int:sid>/delete/", views.delete_student, name="delete_student"),
    path("classes/", views.classes, name="classes"),
    path("classes/<int:cid>/edit/", views.edit_class, name="edit_class"),
    path("classes/<int:cid>/delete/", views.delete_class, name="delete_class"),
    path("materials/", views.materials, name="materials"),
    path("uploads/<path:filename>", views.download_file, name="download_file"),
    path("assignments/", views.assignments, name="assignments"),
    path(
        "activities/<str:activity_type>/<int:activity_id>/check-in/",
        views.activity_check_in,
        name="activity_check_in",
    ),
    path("session-checkins/", views.session_checkins, name="session_checkins"),
    path(
        "assignments/<int:aid>/submit/",
        views.submit_assignment,
        name="submit_assignment",
    ),
    path("submissions/", views.submissions, name="submissions"),
    path("practicals/", views.practicals, name="practicals"),
    path("attendance/", views.attendance, name="attendance"),
    path("laboratory/", views.laboratory, name="laboratory"),
    path("laboratory/<int:cid>/", views.computer_detail, name="computer_detail"),
    path("laboratory/<int:cid>/edit/", views.edit_computer, name="edit_computer"),
    path("laboratory/<int:cid>/delete/", views.delete_computer, name="delete_computer"),
    path(
        "laboratory/<int:cid>/maintenance/",
        views.report_fault,
        name="report_fault",
    ),
    path(
        "maintenance/<int:mid>/edit/",
        views.edit_maintenance,
        name="edit_maintenance",
    ),
    path(
        "maintenance/<int:mid>/delete/",
        views.delete_maintenance,
        name="delete_maintenance",
    ),
    path("notifications/", views.notifications, name="notifications"),
    path("reports/", views.reports, name="reports"),
    path("users/", views.users, name="users"),
]
