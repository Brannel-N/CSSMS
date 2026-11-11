from datetime import timedelta
from io import BytesIO
from tempfile import TemporaryDirectory

from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from .models import (
    ActivityCheckIn,
    Assignment,
    Computer,
    Maintenance,
    Notification,
    Practical,
    SchoolClass,
    Student,
    Submission,
    User,
)


class PortalSmokeTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin",
            password="Admin@12345",
            email="admin@example.test",
            full_name="Test Administrator",
            role="admin",
        )

    def test_login_page_renders_and_includes_csrf(self):
        csrf_client = Client(enforce_csrf_checks=True)
        response = csrf_client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertContains(
            response,
            "document.documentElement.dataset.theme='light'",
        )
        token = response.cookies["csrftoken"].value
        response = csrf_client.post(
            reverse("login"),
            {"username": "admin", "password": "Admin@12345"},
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertRedirects(response, reverse("dashboard"))

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("dashboard"))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('dashboard')}")

    def test_profile_has_back_to_dashboard_link(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("profile"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="/dashboard/"')
        self.assertContains(response, "Back to dashboard")

    def test_presence_requires_login(self):
        response = self.client.post(reverse("presence"))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('presence')}")

    def test_presence_updates_last_seen_and_only_returns_active_users(self):
        self.client.force_login(self.admin)
        recent_user = User.objects.create_user(
            username="recent",
            password="Recent@12345",
            email="recent@example.test",
            full_name="Recently Active",
            role="teacher",
        )
        stale_user = User.objects.create_user(
            username="stale",
            password="Stale@12345",
            email="stale@example.test",
            full_name="Stale Account",
            role="student",
        )
        inactive_user = User.objects.create_user(
            username="inactive",
            password="Inactive@12345",
            email="inactive@example.test",
            full_name="Inactive Account",
            role="student",
            is_active=False,
        )
        User.objects.filter(pk=recent_user.pk).update(last_seen=timezone.now())
        User.objects.filter(pk=stale_user.pk).update(
            last_seen=timezone.now() - timedelta(minutes=5)
        )
        User.objects.filter(pk=inactive_user.pk).update(last_seen=timezone.now())

        response = self.client.post(reverse("presence"))

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(User.objects.get(pk=self.admin.pk).last_seen)
        presence_users = response.json()["users"]
        self.assertEqual(
            {user["id"] for user in presence_users},
            {self.admin.pk, recent_user.pk},
        )
        self.assertEqual(
            set(presence_users[0]),
            {"id", "full_name", "role"},
        )

    def test_admin_can_load_application_pages(self):
        self.client.force_login(self.admin)
        for name in (
            "dashboard",
            "students",
            "classes",
            "materials",
            "assignments",
            "submissions",
            "practicals",
            "attendance",
            "laboratory",
            "session_checkins",
            "notifications",
            "reports",
            "users",
        ):
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_dashboard_greeting_uses_full_profile_name(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "Good day, Test Administrator")
        self.assertNotContains(response, "Good day, Test <span")

    def test_student_directory_scales_past_600_and_preserves_search_state(self):
        Student.objects.bulk_create(
            [
                Student(
                    admission_no=f"LOAD-{index:03}",
                    full_name=f"Load Student {index:03}",
                )
                for index in range(601)
            ]
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse("students"), {"page": "2", "q": "Load"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "601 record(s)")
        self.assertContains(response, "LOAD-099")
        self.assertNotContains(response, "LOAD-000")
        self.assertEqual(response.content.count(b'aria-label="View Load Student'), 50)
        self.assertContains(response, "?page=1&amp;q=Load")
        self.assertContains(response, 'id="student-search"')
        self.assertContains(response, 'type="search"')
        self.assertContains(response, 'class="form-control" type="search"')

    def test_student_assignment_list_only_contains_global_or_own_class_assignments(self):
        classroom = SchoolClass.objects.create(name="Form 1", form="Form 1")
        other_classroom = SchoolClass.objects.create(name="Form 2", form="Form 2")
        student_user = User.objects.create_user(
            username="class-student",
            password="Student@12345",
            email="class-student@example.test",
            full_name="Class Student",
            role="student",
        )
        Student.objects.create(
            admission_no="CLASS-001",
            full_name="Class Student",
            user=student_user,
            classroom=classroom,
        )
        Assignment.objects.create(title="Global assignment")
        Assignment.objects.create(title="Own class assignment", classroom=classroom)
        Assignment.objects.create(
            title="Other class assignment", classroom=other_classroom
        )
        self.client.force_login(student_user)

        response = self.client.get(reverse("assignments"))

        self.assertContains(response, "Global assignment")
        self.assertContains(response, "Own class assignment")
        self.assertNotContains(response, "Other class assignment")

    def test_assignment_creation_notifies_students_in_target_class_or_all_classes(self):
        teacher = User.objects.create_user(
            username="notification-teacher",
            password="Teacher@12345",
            email="notification-teacher@example.test",
            full_name="Notification Teacher",
            role="teacher",
        )
        classroom = SchoolClass.objects.create(name="Form 1 North", form="Form 1")
        other_classroom = SchoolClass.objects.create(name="Form 2 South", form="Form 2")
        target_user = User.objects.create_user(
            username="target-student",
            password="Student@12345",
            email="target-student@example.test",
            full_name="Target Student",
            role="student",
        )
        other_user = User.objects.create_user(
            username="other-student",
            password="Student@12345",
            email="other-student@example.test",
            full_name="Other Student",
            role="student",
        )
        Student.objects.create(
            admission_no="NOTIFY-001",
            full_name="Target Student",
            user=target_user,
            classroom=classroom,
        )
        Student.objects.create(
            admission_no="NOTIFY-002",
            full_name="Other Student",
            user=other_user,
            classroom=other_classroom,
        )
        self.client.force_login(teacher)

        response = self.client.post(
            reverse("assignments"),
            {
                "title": "North class assignment",
                "instructions": "Complete the task.",
                "class_id": str(classroom.pk),
            },
        )

        self.assertRedirects(response, reverse("assignments"))
        self.assertTrue(
            Notification.objects.filter(
                user=target_user, message="New assignment posted: North class assignment."
            ).exists()
        )
        self.assertFalse(Notification.objects.filter(user=other_user).exists())
        self.assertFalse(Notification.objects.filter(user=self.admin).exists())

        self.client.post(
            reverse("assignments"),
            {"title": "Whole school assignment", "instructions": ""},
        )
        self.assertTrue(
            Notification.objects.filter(
                user=target_user,
                message="New assignment posted: Whole school assignment.",
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                user=other_user,
                message="New assignment posted: Whole school assignment.",
            ).exists()
        )

    def test_assignment_submission_and_first_checkin_notify_admins(self):
        student_user = User.objects.create_user(
            username="notify-submit-student",
            password="Student@12345",
            email="notify-submit-student@example.test",
            full_name="Submitting Student",
            role="student",
        )
        student = Student.objects.create(
            admission_no="NOTIFY-SUBMIT-001",
            full_name="Submitting Student",
            user=student_user,
        )
        assignment = Assignment.objects.create(title="Notification assignment")
        practical = Practical.objects.create(title="Notification practical")

        with TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                self.client.force_login(student_user)
                response = self.client.post(
                    reverse("submit_assignment", args=(assignment.pk,)),
                    {
                        "file": SimpleUploadedFile(
                            "submission.txt", b"student work", content_type="text/plain"
                        )
                    },
                )
                self.assertRedirects(response, reverse("assignments"))
                self.assertTrue(
                    Notification.objects.filter(
                        user=self.admin,
                        message="Submitting Student submitted Notification assignment.",
                    ).exists()
                )

                self.client.post(
                    reverse(
                        "activity_check_in",
                        args=("assignment", assignment.pk),
                    )
                )
                self.assertEqual(
                    Notification.objects.filter(
                        user=self.admin,
                        message="Submitting Student checked in for Notification assignment.",
                    ).count(),
                    1,
                )
                self.client.post(
                    reverse(
                        "activity_check_in",
                        args=("assignment", assignment.pk),
                    )
                )
                self.assertEqual(
                    Notification.objects.filter(
                        user=self.admin,
                        message="Submitting Student checked in for Notification assignment.",
                    ).count(),
                    1,
                )
                self.client.post(
                    reverse(
                        "activity_check_in",
                        args=("practical", practical.pk),
                    )
                )

        self.assertTrue(
            Notification.objects.filter(
                user=self.admin,
                message="Submitting Student checked in for Notification practical.",
            ).exists()
        )
        self.assertFalse(Notification.objects.filter(user=student_user).exists())

    def test_class_and_report_views_use_aggregated_enrollment_counts(self):
        classroom = SchoolClass.objects.create(name="Form 3", form="Form 3")
        for index in range(2):
            Student.objects.create(
                admission_no=f"COUNT-{index}",
                full_name=f"Count Student {index}",
                classroom=classroom,
            )
        self.client.force_login(self.admin)

        classes_response = self.client.get(reverse("classes"))
        reports_response = self.client.get(reverse("reports"))

        self.assertContains(classes_response, "2 students")
        self.assertContains(reports_response, "<td>2</td>")

    def test_admin_can_create_update_and_delete_class(self):
        student = Student.objects.create(
            admission_no="CLASS-CRUD-001",
            full_name="Class CRUD Student",
        )
        assignment = Assignment.objects.create(title="Class CRUD Assignment")
        self.client.force_login(self.admin)

        create_response = self.client.post(
            reverse("classes"),
            {"name": "Form 2 North", "form": "Form 2", "stream": "North"},
        )
        self.assertRedirects(create_response, reverse("classes"))
        classroom = SchoolClass.objects.get(name="Form 2 North")
        student.classroom = classroom
        student.save(update_fields=["classroom"])
        assignment.classroom = classroom
        assignment.save(update_fields=["classroom"])
        self.assertContains(self.client.get(reverse("classes")), "Edit")
        edit_page = self.client.get(reverse("edit_class", args=(classroom.pk,)))
        self.assertEqual(edit_page.status_code, 200)
        self.assertContains(edit_page, 'for="id_name"')
        self.assertContains(edit_page, 'for="id_form"')
        self.assertContains(edit_page, 'for="id_stream"')
        self.assertNotContains(edit_page, "bound method")

        update_response = self.client.post(
            reverse("edit_class", args=(classroom.pk,)),
            {"name": "Form 2 West", "form": "Form 2", "stream": "West"},
        )
        self.assertRedirects(update_response, reverse("classes"))
        classroom.refresh_from_db()
        self.assertEqual(classroom.name, "Form 2 West")
        self.assertEqual(classroom.stream, "West")

        delete_response = self.client.post(
            reverse("delete_class", args=(classroom.pk,)),
            follow=True,
        )
        self.assertRedirects(delete_response, reverse("classes"))
        self.assertContains(delete_response, "1 student(s) and 1 assignment(s)")
        self.assertFalse(SchoolClass.objects.filter(pk=classroom.pk).exists())
        student.refresh_from_db()
        assignment.refresh_from_db()
        self.assertIsNone(student.classroom_id)
        self.assertIsNone(assignment.classroom_id)

    def test_class_mutations_require_admin_or_teacher_and_delete_requires_post(self):
        classroom = SchoolClass.objects.create(name="Protected Class", form="Form 1")
        student_user = User.objects.create_user(
            username="class-protected-student",
            password="Student@12345",
            email="class-protected-student@example.test",
            full_name="Protected Class Student",
            role="student",
        )
        self.client.force_login(student_user)

        self.assertEqual(
            self.client.get(reverse("edit_class", args=(classroom.pk,))).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(reverse("delete_class", args=(classroom.pk,))).status_code,
            403,
        )
        self.client.force_login(self.admin)
        self.assertEqual(
            self.client.get(reverse("delete_class", args=(classroom.pk,))).status_code,
            405,
        )
        self.assertTrue(SchoolClass.objects.filter(pk=classroom.pk).exists())

    def test_submissions_are_paginated(self):
        student = Student.objects.create(
            admission_no="SUB-001",
            full_name="Submission Student",
        )
        assignment = Assignment.objects.create(title="Submission task")
        Submission.objects.bulk_create(
            [
                Submission(
                    student=student,
                    assignment=assignment,
                    comments=f"Submission {index}",
                )
                for index in range(51)
            ]
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse("submissions"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.count(b'data-bs-target="#mark'), 50)
        self.assertContains(response, 'aria-label="Next page"')

    def test_notifications_are_paginated(self):
        Notification.objects.bulk_create(
            [
                Notification(user=self.admin, message=f"Update {index}")
                for index in range(51)
            ]
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse("notifications"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.count(b'class="notification-row"'), 50)
        self.assertContains(response, 'aria-label="Next page"')

    def test_shared_layout_includes_presence_and_theme_controls(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "data-theme-toggle")
        self.assertContains(response, "data-presence-url")
        self.assertContains(response, 'id="sidebarClose"')
        self.assertContains(response, 'id="sidebarBackdrop"')
        self.assertContains(response, "responsive.css?v=3")
        self.assertContains(response, "static/js/app.js")
        self.assertContains(response, "?v=7")
        self.assertContains(response, "css/dark-mode.css")
        self.assertContains(response, "?v=3")

    def test_authenticated_success_messages_get_five_second_dismissal(self):
        response = self.client.post(
            reverse("login"),
            {"username": "admin", "password": "Admin@12345"},
            follow=True,
        )
        self.assertContains(response, "Welcome back, Test")
        self.assertContains(response, 'data-auto-dismiss-ms="5000"')

    def test_login_form_authenticates_and_redirects(self):
        response = self.client.post(
            reverse("login"),
            {"username": "admin", "password": "Admin@12345"},
        )
        self.assertRedirects(response, reverse("dashboard"))

    def test_invalid_login_error_is_shown_on_login_page(self):
        response = self.client.post(
            reverse("login"),
            {"username": "admin", "password": "incorrect-password"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid username or password.")
        self.assertContains(response, 'data-auto-dismiss-ms="5000"')

        dashboard_response = self.client.post(
            reverse("login"),
            {"username": "admin", "password": "Admin@12345"},
            follow=True,
        )
        self.assertRedirects(dashboard_response, reverse("dashboard"))
        self.assertNotContains(dashboard_response, "Invalid username or password.")

    def test_student_login_redirects_to_assignments(self):
        student = User.objects.create_user(
            username="student",
            password="Student@12345",
            email="student@example.test",
            full_name="Test Student",
            role="student",
        )
        response = self.client.post(
            reverse("login"),
            {"username": student.username, "password": "Student@12345"},
        )
        self.assertRedirects(response, reverse("assignments"))

    def test_student_dashboard_only_shows_class_related_staff_and_assignments(self):
        student_user = User.objects.create_user(
            username="student",
            password="Student@12345",
            email="student@example.test",
            full_name="Test Student",
            role="student",
        )
        student_class = SchoolClass.objects.create(
            name="Form 2 East", form="Form 2", stream="East"
        )
        other_class = SchoolClass.objects.create(
            name="Form 4 West", form="Form 4", stream="West"
        )
        Student.objects.create(
            admission_no="CSS/2026/040",
            full_name="Test Student",
            user=student_user,
            classroom=student_class,
        )
        related_teacher = User.objects.create_user(
            username="related-teacher",
            password="TeacherPass123",
            email="related@example.test",
            full_name="Related Teacher",
            role="teacher",
        )
        unrelated_teacher = User.objects.create_user(
            username="unrelated-teacher",
            password="TeacherPass123",
            email="unrelated@example.test",
            full_name="Unrelated Teacher",
            role="teacher",
        )
        Assignment.objects.create(
            title="Class 2 assignment",
            classroom=student_class,
            created_by=related_teacher,
        )
        Assignment.objects.create(
            title="Other class assignment",
            classroom=other_class,
            created_by=unrelated_teacher,
        )
        self.client.force_login(student_user)

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Form 2 East")
        self.assertContains(response, "Related Teacher")
        self.assertContains(response, "Class 2 assignment")
        self.assertNotContains(response, "Unrelated Teacher")
        self.assertNotContains(response, "Other class assignment")
        self.assertNotContains(response, "Registered Students")

    def test_student_dashboard_without_student_profile_shows_link_message(self):
        student_user = User.objects.create_user(
            username="unlinked-student",
            password="StudentPass123",
            email="unlinked@example.test",
            full_name="Unlinked Student",
            role="student",
        )
        self.client.force_login(student_user)

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "not linked to a student profile")

    def test_authenticated_student_home_redirects_to_assignments(self):
        student = User.objects.create_user(
            username="student",
            password="Student@12345",
            email="student@example.test",
            full_name="Test Student",
            role="student",
        )
        self.client.force_login(student)
        self.assertRedirects(self.client.get(reverse("index")), reverse("assignments"))
        self.assertRedirects(self.client.get(reverse("login")), reverse("assignments"))

    def test_student_cannot_access_staff_pages(self):
        student = User.objects.create_user(
            username="student",
            password="Student@123",
            email="student@example.test",
            full_name="Test Student",
            role="student",
        )
        self.client.force_login(student)
        self.assertEqual(self.client.get(reverse("students")).status_code, 403)

    def test_admin_registration_creates_student_login_account(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("students"),
            {
                "admission_no": "CSS/2026/030",
                "full_name": "New Student",
                "email": "new.student@example.test",
                "password": "InitialPass123",
                "gender": "Female",
            },
        )
        self.assertRedirects(response, reverse("students"))
        student = Student.objects.select_related("user").get(
            admission_no="CSS/2026/030"
        )
        self.assertEqual(student.user.role, User.Role.STUDENT)
        self.assertEqual(student.user.email, "new.student@example.test")
        self.assertEqual(student.user.username, student.admission_no)
        self.assertEqual(student.contact, "new.student@example.test")
        self.assertTrue(student.user.check_password("InitialPass123"))

        self.client.logout()
        login_response = self.client.post(
            reverse("login"),
            {"username": "new.student@example.test", "password": "InitialPass123"},
        )
        self.assertRedirects(login_response, reverse("assignments"))

    def test_teacher_cannot_register_student_accounts(self):
        teacher = User.objects.create_user(
            username="teacher",
            password="Teacher@12345",
            email="teacher@example.test",
            full_name="Test Teacher",
            role="teacher",
        )
        self.client.force_login(teacher)
        response = self.client.post(
            reverse("students"),
            {
                "admission_no": "CSS/2026/031",
                "full_name": "Not Registered",
                "email": "not.registered@example.test",
                "password": "InitialPass123",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Student.objects.filter(admission_no="CSS/2026/031").exists())

    def test_admin_can_view_and_update_student_and_login_details(self):
        student_user = User.objects.create_user(
            username="CSS/2026/032",
            password="OriginalPass123",
            email="old.student@example.test",
            full_name="Old Student Name",
            role="student",
        )
        student = Student.objects.create(
            admission_no="CSS/2026/032",
            full_name="Old Student Name",
            user=student_user,
        )
        self.client.force_login(self.admin)

        detail_response = self.client.get(
            reverse("student_detail", args=(student.pk,))
        )
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, "old.student@example.test")
        self.assertEqual(
            self.client.get(reverse("edit_student", args=(student.pk,))).status_code,
            200,
        )

        response = self.client.post(
            reverse("edit_student", args=(student.pk,)),
            {
                "admission_no": "CSS/2026/033",
                "full_name": "Updated Student Name",
                "email": "updated.student@example.test",
                "password": "ReplacementPass123",
                "gender": "Male",
                "guardian_name": "Guardian Name",
                "guardian_phone": "555-0100",
                "status": "Active",
            },
        )
        self.assertRedirects(response, reverse("student_detail", args=(student.pk,)))
        student.refresh_from_db()
        student_user.refresh_from_db()
        self.assertEqual(student.admission_no, "CSS/2026/033")
        self.assertEqual(student.full_name, "Updated Student Name")
        self.assertEqual(student.guardian_phone, "555-0100")
        self.assertEqual(student_user.username, "CSS/2026/033")
        self.assertEqual(student_user.email, "updated.student@example.test")
        self.assertEqual(student_user.full_name, "Updated Student Name")
        self.assertTrue(student_user.check_password("ReplacementPass123"))

    def test_deleting_student_also_deletes_linked_login(self):
        student_user = User.objects.create_user(
            username="CSS/2026/034",
            password="StudentPass123",
            email="delete.student@example.test",
            full_name="Delete Student",
            role="student",
        )
        student = Student.objects.create(
            admission_no="CSS/2026/034",
            full_name="Delete Student",
            user=student_user,
        )
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("delete_student", args=(student.pk,))
        )

        self.assertRedirects(response, reverse("students"))
        self.assertFalse(Student.objects.filter(pk=student.pk).exists())
        self.assertFalse(User.objects.filter(pk=student_user.pk).exists())

    def test_teacher_can_add_practical_with_attachment(self):
        teacher = User.objects.create(
            username="teacher",
            email="teacher@example.test",
            full_name="Test Teacher",
            role="teacher",
        )
        self.client.force_login(teacher)
        with TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                response = self.client.post(
                    reverse("practicals"),
                    {
                        "title": "Word document formatting",
                        "objectives": "Format a document.",
                        "instructions": "Create a one-page document.",
                        "software": "Microsoft Word",
                        "marks": "20",
                        "file": SimpleUploadedFile(
                            "word-guide.pdf",
                            b"sample practical guide",
                            content_type="application/pdf",
                        ),
                    },
                )
                self.assertRedirects(response, reverse("practicals"))
                practical = Practical.objects.get(title="Word document formatting")
                self.assertTrue(practical.attachment)
                self.assertTrue(default_storage.exists(practical.attachment))
                page = self.client.get(reverse("practicals"))
                self.assertContains(page, "Download practical file")
                self.assertContains(page, practical.attachment)

    def test_practical_rejects_disallowed_attachment_type(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("practicals"),
            {
                "title": "Invalid upload",
                "file": SimpleUploadedFile(
                    "script.exe",
                    b"not allowed",
                    content_type="application/octet-stream",
                ),
            },
        )
        self.assertRedirects(response, reverse("practicals"))
        self.assertFalse(Practical.objects.filter(title="Invalid upload").exists())

    def test_admin_can_register_computer_ip_and_assigned_student(self):
        student = Student.objects.create(
            admission_no="CSS/2026/010",
            full_name="Assigned Student",
        )
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("laboratory"),
            {
                "asset_tag": "LAB-010",
                "computer_name": "DESKTOP-010",
                "ip_address": "192.168.1.10",
                "assigned_student": str(student.pk),
            },
        )
        self.assertRedirects(response, reverse("laboratory"))
        computer = Computer.objects.get(asset_tag="LAB-010")
        self.assertEqual(computer.ip_address, "192.168.1.10")
        self.assertEqual(computer.assigned_student, student)
        self.assertContains(self.client.get(reverse("laboratory")), "192.168.1.10")
        self.assertContains(self.client.get(reverse("laboratory")), "computer-crud-button")
        self.assertContains(
            self.client.get(reverse("laboratory")), "Assigned Student"
        )

    def test_admin_cannot_register_invalid_computer_ip(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("laboratory"),
            {"asset_tag": "LAB-011", "ip_address": "not-an-ip"},
        )
        self.assertRedirects(response, reverse("laboratory"))
        self.assertFalse(Computer.objects.filter(asset_tag="LAB-011").exists())

    def test_computer_inventory_crud_and_maintenance_crud(self):
        student = Student.objects.create(
            admission_no="CSS/2026/012",
            full_name="Lab Student",
        )
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("laboratory"),
            {
                "asset_tag": "LAB-012",
                "computer_name": "DESKTOP-012",
                "assigned_student": str(student.pk),
            },
        )
        self.assertRedirects(response, reverse("laboratory"))
        computer = Computer.objects.get(asset_tag="LAB-012")
        self.assertEqual(
            self.client.get(reverse("computer_detail", args=(computer.pk,))).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(reverse("edit_computer", args=(computer.pk,))).status_code,
            200,
        )

        response = self.client.post(
            reverse("edit_computer", args=(computer.pk,)),
            {
                "asset_tag": "LAB-012-EDITED",
                "computer_name": "DESKTOP-UPDATED",
                "ip_address": "192.168.1.12",
                "assigned_student": str(student.pk),
                "brand_model": "Test Model",
                "processor": "Test CPU",
                "ram": "16 GB",
                "storage": "512 GB SSD",
                "operating_system": "Windows 11",
                "location": "Room 2",
                "condition": "Good",
                "status": "In Use",
            },
        )
        self.assertRedirects(
            response, reverse("computer_detail", args=(computer.pk,))
        )
        computer.refresh_from_db()
        self.assertEqual(computer.asset_tag, "LAB-012-EDITED")
        self.assertEqual(computer.assigned_student, student)
        self.assertEqual(computer.ip_address, "192.168.1.12")

        response = self.client.post(
            reverse("report_fault", args=(computer.pk,)),
            {"issue": "Keyboard keys are stuck"},
        )
        self.assertRedirects(
            response, reverse("computer_detail", args=(computer.pk,))
        )
        maintenance = Maintenance.objects.get(computer=computer)
        self.assertEqual(computer.__class__.objects.get(pk=computer.pk).status, "Faulty")
        self.assertContains(
            self.client.get(reverse("computer_detail", args=(computer.pk,))),
            "Keyboard keys are stuck",
        )
        self.assertEqual(
            self.client.get(
                reverse("edit_maintenance", args=(maintenance.pk,))
            ).status_code,
            200,
        )
        response = self.client.post(
            reverse("edit_maintenance", args=(maintenance.pk,)),
            {
                "issue": "Keyboard replaced",
                "action_taken": "Replaced faulty keyboard",
                "status": "Resolved",
            },
        )
        self.assertRedirects(
            response, reverse("computer_detail", args=(computer.pk,))
        )
        maintenance.refresh_from_db()
        self.assertEqual(maintenance.status, "Resolved")
        self.assertEqual(maintenance.action_taken, "Replaced faulty keyboard")

        response = self.client.post(
            reverse("delete_maintenance", args=(maintenance.pk,))
        )
        self.assertRedirects(
            response, reverse("computer_detail", args=(computer.pk,))
        )
        self.assertFalse(Maintenance.objects.filter(pk=maintenance.pk).exists())
        response = self.client.post(reverse("delete_computer", args=(computer.pk,)))
        self.assertRedirects(response, reverse("laboratory"))
        self.assertFalse(Computer.objects.filter(pk=computer.pk).exists())

    def test_technician_can_manage_laboratory_devices(self):
        technician = User.objects.create_user(
            username="technician",
            password="TechnicianPass123",
            email="technician@example.test",
            full_name="Test Technician",
            role="technician",
        )
        self.client.force_login(technician)
        response = self.client.post(
            reverse("laboratory"),
            {"asset_tag": "LAB-013"},
        )
        self.assertRedirects(response, reverse("laboratory"))
        computer = Computer.objects.get(asset_tag="LAB-013")
        self.assertEqual(
            self.client.post(
                reverse("delete_computer", args=(computer.pk,))
            ).status_code,
            302,
        )
        self.assertFalse(Computer.objects.filter(pk=computer.pk).exists())

    def test_student_can_check_in_once_for_assignment_and_admin_can_view(self):
        student_user = User.objects.create_user(
            username="student",
            email="student@example.test",
            full_name="Test Student",
            role="student",
        )
        student = Student.objects.create(
            admission_no="CSS/2026/020",
            full_name="Test Student",
            user=student_user,
        )
        assignment = Assignment.objects.create(title="Word processing task")
        self.client.force_login(student_user)

        response = self.client.post(
            reverse(
                "activity_check_in",
                args=("assignment", assignment.pk),
            )
        )
        self.assertRedirects(response, reverse("assignments"))
        self.assertEqual(
            ActivityCheckIn.objects.filter(student=student, assignment=assignment).count(),
            1,
        )
        checkin = ActivityCheckIn.objects.get(
            student=student, assignment=assignment
        )
        checkin.check_in_date -= timedelta(days=1)
        checkin.checkin_key = f"{student.pk}:assignment:{assignment.pk}:previous"
        checkin.save(update_fields=["check_in_date", "checkin_key"])
        assignments_page = self.client.get(reverse("assignments"))
        self.assertContains(assignments_page, "Already checked in")
        self.assertNotContains(assignments_page, "Check in for this assignment")

        response = self.client.post(
            reverse(
                "activity_check_in",
                args=("assignment", assignment.pk),
            )
        )
        self.assertRedirects(response, reverse("assignments"))
        self.assertEqual(
            ActivityCheckIn.objects.filter(student=student, assignment=assignment).count(),
            1,
        )
        self.assertEqual(
            Notification.objects.filter(
                user=self.admin,
                message="Test Student checked in for Word processing task.",
            ).count(),
            1,
        )

        self.client.force_login(self.admin)
        response = self.client.get(reverse("session_checkins"))
        self.assertContains(response, "Test Student")
        self.assertContains(response, "Word processing task")

    def test_student_can_check_in_for_practical(self):
        student_user = User.objects.create_user(
            username="student",
            email="student@example.test",
            full_name="Test Student",
            role="student",
        )
        student = Student.objects.create(
            admission_no="CSS/2026/021",
            full_name="Test Student",
            user=student_user,
        )
        practical = Practical.objects.create(title="Keyboard skills")
        self.client.force_login(student_user)

        response = self.client.post(
            reverse("activity_check_in", args=("practical", practical.pk))
        )
        self.assertRedirects(response, reverse("practicals"))
        self.assertTrue(
            ActivityCheckIn.objects.filter(
                student=student, practical=practical
            ).exists()
        )
        self.assertContains(self.client.get(reverse("practicals")), "Checked in today")

    def test_student_cannot_check_in_to_assignment_for_another_class(self):
        classroom = SchoolClass.objects.create(name="Form 1 North", form="Form 1")
        other_classroom = SchoolClass.objects.create(name="Form 2 South", form="Form 2")
        student_user = User.objects.create_user(
            username="student",
            email="student@example.test",
            full_name="Test Student",
            role="student",
        )
        Student.objects.create(
            admission_no="CSS/2026/022",
            full_name="Test Student",
            user=student_user,
            classroom=classroom,
        )
        assignment = Assignment.objects.create(
            title="Other class task", classroom=other_classroom
        )
        self.client.force_login(student_user)

        response = self.client.post(
            reverse("activity_check_in", args=("assignment", assignment.pk))
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(ActivityCheckIn.objects.exists())


class ProfilePhotoTests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="profile-user",
            password="ProfilePass123",
            email="profile@example.test",
            full_name="Profile User",
            role="student",
        )
        self.client.force_login(self.user)

    @staticmethod
    def image_file(image_format, filename):
        image_buffer = BytesIO()
        Image.new("RGB", (2, 2), "blue").save(image_buffer, format=image_format)
        return SimpleUploadedFile(
            filename,
            image_buffer.getvalue(),
            content_type=f"image/{image_format.lower()}",
        )

    def test_user_can_upload_replace_and_remove_profile_photo(self):
        with TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                upload_response = self.client.post(
                    reverse("profile"),
                    {"profile_image": self.image_file("PNG", "avatar.png")},
                )
                self.assertRedirects(upload_response, reverse("profile"))
                self.user.refresh_from_db()
                first_image = self.user.profile_image.name
                self.assertTrue(self.user.profile_image.storage.exists(first_image))
                profile_page = self.client.get(reverse("profile"))
                self.assertEqual(profile_page.status_code, 200)
                self.assertContains(
                    profile_page,
                    reverse("profile_photo", args=(self.user.pk,)),
                )

                replace_response = self.client.post(
                    reverse("profile"),
                    {"profile_image": self.image_file("JPEG", "new-avatar.jpg")},
                )
                self.assertRedirects(replace_response, reverse("profile"))
                self.user.refresh_from_db()
                self.assertNotEqual(self.user.profile_image.name, first_image)
                self.assertFalse(self.user.profile_image.storage.exists(first_image))

                remove_response = self.client.post(
                    reverse("profile"), {"remove_image": "on"}
                )
                self.assertRedirects(remove_response, reverse("profile"))
                self.user.refresh_from_db()
                self.assertFalse(self.user.profile_image)
                self.assertEqual(
                    self.client.get(
                        reverse("profile_photo", args=(self.user.pk,))
                    ).status_code,
                    404,
                )

    def test_profile_photo_is_served_to_authenticated_users(self):
        image_buffer = BytesIO()
        Image.new("RGB", (2, 2), "green").save(image_buffer, format="PNG")

        with TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                self.client.post(
                    reverse("profile"),
                    {
                        "profile_image": SimpleUploadedFile(
                            "avatar.png",
                            image_buffer.getvalue(),
                            content_type="image/png",
                        )
                    },
                )
                photo_response = self.client.get(
                    reverse("profile_photo", args=(self.user.pk,))
                )
                self.assertEqual(photo_response.status_code, 200)
                self.assertEqual(photo_response["Content-Type"], "image/png")
                self.assertTrue(b"".join(photo_response.streaming_content))
                photo_response.close()

    def test_profile_photo_upload_rejects_non_image(self):
        response = self.client.post(
            reverse("profile"),
            {
                "profile_image": SimpleUploadedFile(
                    "not-an-image.png", b"not an image", content_type="image/png"
                )
            },
        )
        self.assertRedirects(response, reverse("profile"))
        self.user.refresh_from_db()
        self.assertFalse(self.user.profile_image)
