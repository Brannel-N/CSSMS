from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", "Administrator"
        TEACHER = "teacher", "Teacher"
        STUDENT = "student", "Student"
        TECHNICIAN = "technician", "Laboratory Technician"

    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=150)
    role = models.CharField(max_length=30, choices=Role.choices, default=Role.STUDENT)
    profile_image = models.BinaryField(blank=True, null=True)
    profile_image_content_type = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    last_seen = models.DateTimeField(null=True, blank=True, db_index=True)

    @property
    def active(self):
        return self.is_active

    @active.setter
    def active(self, value):
        self.is_active = value


class AcademicYear(models.Model):
    name = models.CharField(max_length=30, unique=True)
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class SchoolClass(models.Model):
    name = models.CharField(max_length=40)
    form = models.CharField(max_length=20)
    stream = models.CharField(max_length=30, default="General")
    academic_year = models.ForeignKey(
        AcademicYear,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="classes",
    )

    def __str__(self):
        return self.name


class Student(models.Model):
    admission_no = models.CharField(max_length=40, unique=True)
    full_name = models.CharField(max_length=150, db_index=True)
    gender = models.CharField(max_length=20, blank=True)
    classroom = models.ForeignKey(
        SchoolClass,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="students",
        db_column="class_id",
    )
    user = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="student_profile",
    )
    guardian_name = models.CharField(max_length=120, blank=True)
    guardian_phone = models.CharField(max_length=40, blank=True)
    contact = models.CharField(max_length=120, blank=True)
    admission_date = models.DateField(default=timezone.localdate)
    status = models.CharField(max_length=20, default="Active")

    def __str__(self):
        return self.full_name


class Subject(models.Model):
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=20, unique=True, null=True, blank=True)

    def __str__(self):
        return self.name


class Material(models.Model):
    title = models.CharField(max_length=180)
    topic = models.CharField(max_length=120, blank=True)
    description = models.TextField(blank=True)
    filename = models.CharField(max_length=255, blank=True)
    file_content = models.BinaryField(blank=True, null=True)
    content_type = models.CharField(max_length=100, blank=True)
    uploaded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    def __str__(self):
        return self.title


class Assignment(models.Model):
    title = models.CharField(max_length=180)
    instructions = models.TextField(blank=True)
    classroom = models.ForeignKey(
        SchoolClass,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assignments",
        db_column="class_id",
    )
    due_date = models.DateTimeField(null=True, blank=True)
    max_marks = models.PositiveIntegerField(default=100)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    def __str__(self):
        return self.title


class Submission(models.Model):
    assignment = models.ForeignKey(
        Assignment, on_delete=models.CASCADE, related_name="submissions"
    )
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    filename = models.CharField(max_length=255, blank=True)
    file_content = models.BinaryField(blank=True, null=True)
    content_type = models.CharField(max_length=100, blank=True)
    comments = models.TextField(blank=True)
    marks = models.FloatField(null=True, blank=True)
    feedback = models.TextField(blank=True)
    submitted_at = models.DateTimeField(default=timezone.now, db_index=True)
    attempt_number = models.PositiveIntegerField(default=1)


class Practical(models.Model):
    title = models.CharField(max_length=180)
    objectives = models.TextField(blank=True)
    instructions = models.TextField(blank=True)
    software = models.CharField(max_length=180, blank=True)
    attachment = models.CharField(max_length=255, blank=True)
    attachment_content = models.BinaryField(blank=True, null=True)
    attachment_content_type = models.CharField(max_length=100, blank=True)
    marks = models.PositiveIntegerField(default=100)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    def __str__(self):
        return self.title


class ActivityCheckIn(models.Model):
    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name="activity_checkins"
    )
    assignment = models.ForeignKey(
        Assignment,
        on_delete=models.CASCADE,
        related_name="session_checkins",
        null=True,
        blank=True,
    )
    practical = models.ForeignKey(
        Practical,
        on_delete=models.CASCADE,
        related_name="session_checkins",
        null=True,
        blank=True,
    )
    check_in_date = models.DateField()
    checked_in_at = models.DateTimeField(default=timezone.now)
    checkin_key = models.CharField(max_length=100, unique=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(assignment__isnull=False, practical__isnull=True)
                    | models.Q(assignment__isnull=True, practical__isnull=False)
                ),
                name="activity_checkin_has_one_activity",
            ),
            models.UniqueConstraint(
                fields=["student", "assignment"],
                name="uniq_student_assignment_checkin",
            ),
        ]
        indexes = [
            models.Index(
                fields=["student", "assignment", "check_in_date"],
                name="checkin_student_assignment_idx",
            ),
            models.Index(
                fields=["student", "practical", "check_in_date"],
                name="checkin_student_practical_idx",
            ),
        ]


class Attendance(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    lesson_type = models.CharField(max_length=30, default="Theory")
    lesson_date = models.DateField(default=timezone.localdate)
    status = models.CharField(max_length=20, default="Present")
    marked_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True
    )

    class Meta:
        indexes = [
            models.Index(fields=["lesson_date"], name="attendance_lesson_date_idx"),
        ]


class Computer(models.Model):
    asset_tag = models.CharField(max_length=50, unique=True)
    computer_name = models.CharField(max_length=100, blank=True)
    ip_address = models.GenericIPAddressField(
        protocol="both", unpack_ipv4=False, blank=True, null=True
    )
    assigned_student = models.ForeignKey(
        Student,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_computers",
    )
    brand_model = models.CharField(max_length=120, blank=True)
    processor = models.CharField(max_length=120, blank=True)
    ram = models.CharField(max_length=40, blank=True)
    storage = models.CharField(max_length=40, blank=True)
    operating_system = models.CharField(max_length=100, blank=True)
    location = models.CharField(max_length=100, default="Computer Laboratory")
    condition = models.CharField(max_length=30, default="Good")
    status = models.CharField(max_length=30, default="Available")

    def __str__(self):
        return self.asset_tag


class Maintenance(models.Model):
    computer = models.ForeignKey(
        Computer, on_delete=models.CASCADE, related_name="maintenance_records"
    )
    issue = models.TextField()
    action_taken = models.TextField(blank=True)
    reported_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=30, default="Reported")


class Notification(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, null=True, blank=True
    )
    message = models.CharField(max_length=255)
    created_at = models.DateTimeField(default=timezone.now)
    read = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(
                fields=["user", "read", "created_at"],
                name="notif_user_read_date_idx",
            ),
        ]


class AuditLog(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True
    )
    action = models.CharField(max_length=180)
    created_at = models.DateTimeField(default=timezone.now)
