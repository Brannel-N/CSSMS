from datetime import date

from django.core.management.base import BaseCommand

from portal.models import (
    AcademicYear,
    Assignment,
    Computer,
    Practical,
    SchoolClass,
    Student,
    Subject,
    User,
)


class Command(BaseCommand):
    help = "Create the CSSMS demo accounts and sample records."

    def handle(self, *args, **options):
        year, _ = AcademicYear.objects.get_or_create(
            name=str(date.today().year), defaults={"active": True}
        )
        Subject.objects.get_or_create(
            code="CS", defaults={"name": "Computer Studies"}
        )
        demo_accounts = [
            ("admin", "admin@school.local", "System Administrator", "admin", "Admin@12345"),
            ("teacher", "teacher@school.local", "Computer Studies Teacher", "teacher", "Teacher@123"),
            ("student", "student@school.local", "Demo Student", "student", "Student@123"),
            ("technician", "lab@school.local", "Laboratory Technician", "technician", "Lab@12345"),
        ]
        for username, email, full_name, role, password in demo_accounts:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "email": email,
                    "full_name": full_name,
                    "role": role,
                },
            )
            if created:
                user.set_password(password)
                user.save(update_fields=["password"])

        classroom, _ = SchoolClass.objects.get_or_create(
            name="Form 3 East",
            defaults={"form": "Form 3", "stream": "East", "academic_year": year},
        )
        student_user = User.objects.get(username="student")
        Student.objects.get_or_create(
            admission_no="CSS/2026/001",
            defaults={
                "full_name": "Demo Student",
                "gender": "Female",
                "classroom": classroom,
                "user": student_user,
            },
        )
        Computer.objects.get_or_create(
            asset_tag="LAB-001",
            defaults={
                "computer_name": "DESKTOP-001",
                "brand_model": "HP ProDesk",
                "processor": "Intel Core i5",
                "ram": "8 GB",
                "storage": "256 GB SSD",
                "operating_system": "Windows 11",
                "status": "Available",
            },
        )
        Assignment.objects.get_or_create(
            title="Introduction to Computer Systems",
            defaults={
                "instructions": "Explain the main components of a computer system.",
                "classroom": classroom,
                "max_marks": 20,
                "created_by": User.objects.get(username="teacher"),
            },
        )
        Practical.objects.get_or_create(
            title="Word Processing: Document Formatting",
            defaults={
                "objectives": "Create and format a one-page document.",
                "instructions": (
                    "Use a word processor to create a document with headings, "
                    "tables and page numbers."
                ),
                "software": "Microsoft Word / LibreOffice Writer",
                "marks": 25,
            },
        )
        self.stdout.write(self.style.SUCCESS("CSSMS demo data is ready."))
