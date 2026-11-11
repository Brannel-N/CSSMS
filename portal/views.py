import secrets
from datetime import date, datetime, timedelta
from functools import wraps
from mimetypes import guess_type
from pathlib import Path

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Avg, Count, Exists, F, OuterRef, Q
from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import get_valid_filename
from django.views.decorators.http import require_http_methods
from PIL import Image

from .models import (
    AcademicYear,
    ActivityCheckIn,
    Assignment,
    Attendance,
    AuditLog,
    Computer,
    Material,
    Maintenance,
    Notification,
    Practical,
    SchoolClass,
    Student,
    Subject,
    Submission,
    User,
)

ALLOWED_EXTENSIONS = {
    "pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx", "zip",
    "png", "jpg", "jpeg", "txt",
}
PROFILE_IMAGE_MAX_SIZE = 5 * 1024 * 1024
PRESENCE_TIMEOUT = timedelta(seconds=150)
PROFILE_IMAGE_FORMATS = {
    "GIF": (".gif", "image/gif"),
    "JPEG": (".jpg", "image/jpeg"),
    "PNG": (".png", "image/png"),
    "WEBP": (".webp", "image/webp"),
}


class SchoolClassForm(forms.ModelForm):
    form = forms.CharField(
        widget=forms.Select(
            choices=(
                ("Form 1", "Form 1"),
                ("Form 2", "Form 2"),
                ("Form 3", "Form 3"),
                ("Form 4", "Form 4"),
                ("Grade 10", "Grade 10"),
                ("Grade 11", "Grade 11"),
                ("Grade 12", "Grade 12"),
            ),
            attrs={"class": "form-select"},
        )
    )

    class Meta:
        model = SchoolClass
        fields = ("name", "form", "stream")
        widgets = {
            "name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Form 2 North"}
            ),
            "stream": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "North"}
            ),
        }


def paginate_queryset(request, queryset, per_page):
    paginator = Paginator(queryset, per_page)
    page_obj = paginator.get_page(request.GET.get("page"))

    def page_url(page_number):
        params = request.GET.copy()
        params["page"] = page_number
        return f"{request.path}?{params.urlencode()}"

    page_links = []
    for page_number in paginator.get_elided_page_range(
        page_obj.number, on_each_side=2, on_ends=1
    ):
        is_number = isinstance(page_number, int)
        page_links.append(
            {
                "number": page_number,
                "url": page_url(page_number) if is_number else None,
                "current": page_number == page_obj.number,
            }
        )
    return {
        "page_obj": page_obj,
        "page_links": page_links,
        "previous_url": (
            page_url(page_obj.previous_page_number())
            if page_obj.has_previous()
            else None
        ),
        "next_url": (
            page_url(page_obj.next_page_number()) if page_obj.has_next() else None
        ),
    }


def roles_required(*roles):
    def decorator(view_func):
        @login_required
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if request.user.role not in roles:
                return render(
                    request,
                    "error.html",
                    {
                        "code": 403,
                        "message": "You do not have permission to access this page.",
                    },
                    status=403,
                )
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_upload(uploaded_file):
    safe_name = get_valid_filename(Path(uploaded_file.name).name)
    filename = f"{secrets.token_hex(8)}_{safe_name}"
    uploaded_file.seek(0)
    file_content = uploaded_file.read()
    content_type = guess_type(uploaded_file.name)[0] or "application/octet-stream"
    return filename, file_content, content_type


def log_action(user, action):
    AuditLog.objects.create(user=user, action=action)


def create_notifications(user_ids, message):
    Notification.objects.bulk_create(
        [
            Notification(user_id=user_id, message=message)
            for user_id in user_ids
        ]
    )


def landing_page_name(user):
    return "assignments" if user.role == "student" else "dashboard"


def index(request):
    return redirect(
        landing_page_name(request.user) if request.user.is_authenticated else "login"
    )


@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect(landing_page_name(request.user))
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        account = User.objects.filter(email__iexact=username).first()
        user = authenticate(
            request,
            username=account.username if account else username,
            password=request.POST.get("password", ""),
        )
        if user and user.is_active:
            login(request, user)
            messages.success(request, "Welcome back, " + user.full_name.split()[0] + ".")
            return redirect(landing_page_name(user))
        messages.error(request, "Invalid username or password.")
    return render(request, "login.html")


@login_required
def logout_view(request):
    if request.user.is_authenticated:
        User.objects.filter(pk=request.user.pk).update(last_seen=None)
    logout(request)
    messages.info(request, "You have been signed out.")
    return redirect("login")


@login_required
@require_http_methods(["GET", "POST"])
def profile(request):
    user = request.user
    if request.method == "POST":
        if request.POST.get("remove_image") == "on":
            user.profile_image = None
            user.profile_image_content_type = ""
            user.save(update_fields=["profile_image", "profile_image_content_type"])
            messages.success(request, "Profile photo removed.")
            return redirect("profile")

        try:
            image = forms.ImageField(required=True).clean(
                request.FILES.get("profile_image")
            )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
            return redirect("profile")

        if image.size > PROFILE_IMAGE_MAX_SIZE:
            messages.error(request, "Profile photos must be 5 MB or smaller.")
            return redirect("profile")

        image.seek(0)
        try:
            with Image.open(image) as uploaded_image:
                image_format = uploaded_image.format
        except (OSError, ValueError):
            messages.error(request, "The uploaded profile photo is invalid.")
            return redirect("profile")

        if image_format not in PROFILE_IMAGE_FORMATS:
            messages.error(request, "Use a JPEG, PNG, GIF, or WebP image.")
            return redirect("profile")

        extension, content_type = PROFILE_IMAGE_FORMATS[image_format]
        image.seek(0)
        image_content = image.read()
        user.profile_image = image_content
        user.profile_image_content_type = content_type
        user.save(update_fields=["profile_image", "profile_image_content_type"])
        messages.success(request, "Profile photo updated.")
        return redirect("profile")

    return render(request, "profile.html")


@login_required
def profile_photo(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    if not user.profile_image:
        raise Http404("No profile photo is available.")
    content_type = user.profile_image_content_type or "image/jpeg"
    return HttpResponse(user.profile_image, content_type=content_type)


@login_required
@require_http_methods(["POST"])
def presence(request):
    now = timezone.now()
    User.objects.filter(pk=request.user.pk, is_active=True).filter(
        Q(last_seen__isnull=True)
        | Q(last_seen__lt=now - timedelta(seconds=30))
    ).update(last_seen=now)
    online_users = list(
        User.objects.filter(
            is_active=True, last_seen__gte=now - PRESENCE_TIMEOUT
        )
        .order_by("full_name", "pk")
        .values("id", "full_name", "role")
    )
    return JsonResponse({"users": online_users})


@login_required
def dashboard(request):
    if request.user.role == User.Role.STUDENT:
        student = Student.objects.select_related("classroom").filter(
            user=request.user
        ).first()
        class_assignments = Assignment.objects.none()
        related_teachers = []
        assignment_count = 0
        submitted_count = 0
        if student and student.classroom_id:
            class_assignments = (
                Assignment.objects.filter(classroom_id=student.classroom_id)
                .select_related("created_by", "classroom")
                .order_by("-created_at", "-pk")
            )
            assignment_count = class_assignments.count()
            related_teachers = list(
                Assignment.objects.filter(
                    classroom_id=student.classroom_id,
                    created_by__role=User.Role.TEACHER,
                )
                .values(
                    teacher_id=F("created_by_id"),
                    teacher_name=F("created_by__full_name"),
                    teacher_email=F("created_by__email"),
                )
                .annotate(assignment_count=Count("pk"))
                .order_by("teacher_name")
            )
            submitted_count = (
                Submission.objects.filter(
                    student=student,
                    assignment__classroom_id=student.classroom_id,
                )
                .values("assignment_id")
                .distinct()
                .count()
            )
        return render(
            request,
            "student_dashboard.html",
            {
                "student": student,
                "classroom": student.classroom if student else None,
                "related_teachers": related_teachers,
                "recent_assignments": class_assignments[:5],
                "assignment_count": assignment_count,
                "submitted_count": submitted_count,
                "pending_count": assignment_count - submitted_count,
            },
        )

    stats = {
        "students": Student.objects.count(),
        "classes": SchoolClass.objects.count(),
        "teachers": User.objects.filter(role="teacher").count(),
        "computers": Computer.objects.count(),
        "available": Computer.objects.filter(status="Available").count(),
        "faulty": Computer.objects.filter(status="Faulty").count(),
        "assignments": Assignment.objects.count(),
        "submissions": Submission.objects.count(),
    }
    recent_assignments = Assignment.objects.select_related("classroom").order_by(
        "-created_at"
    )[:5]
    performance = list(
        Submission.objects.values("student__full_name")
        .annotate(average=Avg("marks"))
        .order_by("student__full_name")[:7]
    )
    performance = [
        (row["student__full_name"], float(row["average"] or 0))
        for row in performance
    ]
    return render(
        request,
        "dashboard.html",
        {
            "stats": stats,
            "recent_assignments": recent_assignments,
            "performance": performance,
        },
    )


@roles_required("admin")
@require_http_methods(["GET", "POST"])
def students(request):
    if request.method == "POST":
        try:
            admission_no = forms.CharField(max_length=40).clean(
                request.POST.get("admission_no", "")
            )
            full_name = forms.CharField(max_length=150).clean(
                request.POST.get("full_name", "")
            )
            email = forms.EmailField().clean(request.POST.get("email", "")).lower()
            password = forms.CharField(min_length=10, strip=False).clean(
                request.POST.get("password", "")
            )
            classroom = forms.ModelChoiceField(
                queryset=SchoolClass.objects.all(), required=False
            ).clean(request.POST.get("class_id") or None)
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
            return redirect("students")

        if Student.objects.filter(admission_no=admission_no).exists():
            messages.error(request, "A student with that admission number already exists.")
            return redirect("students")
        if User.objects.filter(Q(username__iexact=admission_no) | Q(email__iexact=email)).exists():
            messages.error(request, "That admission number or email is already in use.")
            return redirect("students")

        with transaction.atomic():
            user = User.objects.create_user(
                username=admission_no,
                email=email,
                full_name=full_name,
                role=User.Role.STUDENT,
                password=password,
            )
            student = Student.objects.create(
                admission_no=admission_no,
                full_name=full_name,
                gender=request.POST.get("gender", ""),
                classroom=classroom,
                user=user,
                guardian_name=request.POST.get("guardian_name", "").strip(),
                guardian_phone=request.POST.get("guardian_phone", "").strip(),
                contact=email,
            )
        log_action(request.user, "Registered student " + student.admission_no)
        messages.success(
            request,
            f"Student registered. They can sign in with {email} and the password you set.",
        )
        return redirect("students")
    query = request.GET.get("q", "")
    student_list = Student.objects.select_related("classroom").all()
    if query:
        student_list = student_list.filter(
            Q(full_name__icontains=query) | Q(admission_no__icontains=query)
        )
    pagination = paginate_queryset(
        request, student_list.order_by("full_name", "pk"), 50
    )
    return render(
        request,
        "students.html",
        {
            "students": pagination["page_obj"].object_list,
            "total_students": pagination["page_obj"].paginator.count,
            "classes": SchoolClass.objects.all(),
            "q": query,
            **pagination,
        },
    )


@roles_required("admin")
def student_detail(request, sid):
    student = get_object_or_404(
        Student.objects.select_related("classroom", "user"), pk=sid
    )
    return render(request, "student_detail.html", {"student": student})


@roles_required("admin")
@require_http_methods(["GET", "POST"])
def edit_student(request, sid):
    student = get_object_or_404(
        Student.objects.select_related("user"), pk=sid
    )
    if request.method == "POST":
        try:
            admission_no = forms.CharField(max_length=40).clean(
                request.POST.get("admission_no", "")
            )
            full_name = forms.CharField(max_length=150).clean(
                request.POST.get("full_name", "")
            )
            email = forms.EmailField(required=bool(student.user)).clean(
                request.POST.get("email", "")
            ).lower()
            password = forms.CharField(
                min_length=10, strip=False, required=False
            ).clean(request.POST.get("password", ""))
            classroom = forms.ModelChoiceField(
                queryset=SchoolClass.objects.all(), required=False
            ).clean(request.POST.get("class_id") or None)
            gender = forms.CharField(max_length=20, required=False).clean(
                request.POST.get("gender", "")
            )
            guardian_name = forms.CharField(max_length=120, required=False).clean(
                request.POST.get("guardian_name", "")
            )
            guardian_phone = forms.CharField(max_length=40, required=False).clean(
                request.POST.get("guardian_phone", "")
            )
            contact = forms.CharField(max_length=120, required=False).clean(
                request.POST.get("contact", "")
            )
            status = forms.CharField(max_length=20).clean(
                request.POST.get("status", "")
            )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
            return redirect("edit_student", sid=student.pk)

        if Student.objects.filter(admission_no__iexact=admission_no).exclude(
            pk=student.pk
        ).exists():
            messages.error(request, "That admission number is already in use.")
            return redirect("edit_student", sid=student.pk)
        other_users = User.objects.all()
        if student.user_id:
            other_users = other_users.exclude(pk=student.user_id)
        if other_users.filter(username__iexact=admission_no).exists():
            messages.error(request, "That admission number is already in use as a username.")
            return redirect("edit_student", sid=student.pk)
        if student.user and User.objects.filter(email__iexact=email).exclude(
            pk=student.user_id
        ).exists():
            messages.error(request, "That email address is already in use.")
            return redirect("edit_student", sid=student.pk)

        with transaction.atomic():
            student.admission_no = admission_no
            student.full_name = full_name
            student.gender = gender
            student.classroom = classroom
            student.guardian_name = guardian_name
            student.guardian_phone = guardian_phone
            student.contact = email if student.user else contact
            student.status = status
            student.save()
            if student.user:
                student.user.username = admission_no
                student.user.full_name = full_name
                student.user.email = email
                if password:
                    student.user.set_password(password)
                update_fields = ["username", "full_name", "email"]
                if password:
                    update_fields.append("password")
                student.user.save(update_fields=update_fields)

        log_action(request.user, "Updated student " + student.admission_no)
        messages.success(request, "Student details updated.")
        return redirect("student_detail", sid=student.pk)

    return render(
        request,
        "student_edit.html",
        {
            "student": student,
            "classes": SchoolClass.objects.order_by("name"),
            "email": student.user.email if student.user else "",
        },
    )


@roles_required("admin")
@require_http_methods(["POST"])
def delete_student(request, sid):
    student = get_object_or_404(Student.objects.select_related("user"), pk=sid)
    admission_no = student.admission_no
    with transaction.atomic():
        user = student.user
        student.delete()
        if user:
            user.delete()
    log_action(request.user, "Deleted student " + admission_no)
    messages.success(request, "Student record and linked login account deleted.")
    return redirect("students")


@roles_required("admin", "teacher")
@require_http_methods(["GET", "POST"])
def classes(request):
    if request.method == "POST":
        class_form = SchoolClassForm(request.POST)
        if not class_form.is_valid():
            errors = [
                error
                for field_errors in class_form.errors.values()
                for error in field_errors
            ]
            messages.error(request, "; ".join(errors))
            return redirect("classes")

        classroom = class_form.save(commit=False)
        classroom.academic_year = AcademicYear.objects.filter(active=True).first()
        classroom.save()
        log_action(request.user, "Created class " + classroom.name)
        messages.success(request, "Class created.")
        return redirect("classes")
    return render(
        request,
        "classes.html",
        {
            "classes": SchoolClass.objects.select_related("academic_year")
            .annotate(
                student_count=Count("students", distinct=True),
                assignment_count=Count("assignments", distinct=True),
            )
            .order_by("form", "name")
        },
    )


@roles_required("admin", "teacher")
@require_http_methods(["GET", "POST"])
def edit_class(request, cid):
    classroom = get_object_or_404(SchoolClass, pk=cid)
    class_form = SchoolClassForm(request.POST or None, instance=classroom)
    if request.method == "POST" and class_form.is_valid():
        classroom = class_form.save()
        log_action(request.user, "Updated class " + classroom.name)
        messages.success(request, "Class details updated.")
        return redirect("classes")

    return render(
        request,
        "class_edit.html",
        {"classroom": classroom, "form": class_form},
    )


@roles_required("admin", "teacher")
@require_http_methods(["POST"])
def delete_class(request, cid):
    with transaction.atomic():
        classroom = get_object_or_404(
            SchoolClass.objects.select_for_update(), pk=cid
        )
        name = classroom.name
        student_count = classroom.students.count()
        assignment_count = classroom.assignments.count()
        classroom.delete()
        log_action(request.user, "Deleted class " + name)

    if student_count or assignment_count:
        messages.warning(
            request,
            f'{name} was deleted. {student_count} student(s) and '
            f'{assignment_count} assignment(s) are now unassigned.',
        )
    else:
        messages.success(request, name + " deleted.")
    return redirect("classes")


@login_required
@require_http_methods(["GET", "POST"])
def materials(request):
    if request.method == "POST":
        if request.user.role not in ("admin", "teacher"):
            return permission_denied(request)
        uploaded_file = request.FILES.get("file")
        filename = ""
        file_content = None
        content_type = ""
        if uploaded_file and uploaded_file.name:
            if not allowed_file(uploaded_file.name):
                messages.error(request, "File type not allowed.")
                return redirect("materials")
            filename, file_content, content_type = save_upload(uploaded_file)
        Material.objects.create(
            title=request.POST["title"],
            topic=request.POST.get("topic", ""),
            description=request.POST.get("description", ""),
            filename=filename,
            file_content=file_content,
            content_type=content_type,
            uploaded_by=request.user,
        )
        messages.success(request, "Learning material published.")
        return redirect("materials")
    pagination = paginate_queryset(
        request, Material.objects.order_by("-created_at", "-pk"), 30
    )
    return render(
        request,
        "materials.html",
        {"materials": pagination["page_obj"].object_list, **pagination},
    )


@login_required
def download_file(request, filename):
    material = Material.objects.filter(filename=filename).first()
    if material and material.file_content:
        response = HttpResponse(material.file_content, content_type=material.content_type)
        response['Content-Disposition'] = f'attachment; filename="{material.filename}"'
        return response
    submission = Submission.objects.filter(filename=filename).first()
    if submission and submission.file_content:
        response = HttpResponse(submission.file_content, content_type=submission.content_type)
        response['Content-Disposition'] = f'attachment; filename="{submission.filename}"'
        return response
    practical = Practical.objects.filter(attachment=filename).first()
    if practical and practical.attachment_content:
        response = HttpResponse(practical.attachment_content, content_type=practical.attachment_content_type)
        response['Content-Disposition'] = f'attachment; filename="{practical.attachment}"'
        return response
    raise Http404("The requested file could not be found.")


@login_required
@require_http_methods(["GET", "POST"])
def assignments(request):
    if request.method == "POST":
        if request.user.role not in ("admin", "teacher"):
            return permission_denied(request)
        due_date = request.POST.get("due_date")
        due = datetime.fromisoformat(due_date) if due_date else None
        assignment = Assignment.objects.create(
            title=request.POST["title"],
            instructions=request.POST.get("instructions", ""),
            classroom_id=request.POST.get("class_id") or None,
            due_date=due,
            max_marks=int(request.POST.get("max_marks", 100)),
            created_by=request.user,
        )
        student_users = User.objects.filter(
            role=User.Role.STUDENT,
            is_active=True,
            student_profile__isnull=False,
        )
        if assignment.classroom_id:
            student_users = student_users.filter(
                student_profile__classroom_id=assignment.classroom_id
            )
        create_notifications(
            student_users.values_list("pk", flat=True),
            f"New assignment posted: {assignment.title}.",
        )
        messages.success(request, "Assignment created.")
        return redirect("assignments")
    student = Student.objects.filter(user=request.user).first()
    assignments = Assignment.objects.select_related("classroom")
    if request.user.role == User.Role.STUDENT:
        assignments = assignments.filter(
            Q(classroom__isnull=True)
            | Q(classroom_id=student.classroom_id if student else None)
        )
        if student:
            assignments = assignments.annotate(
                checked_in=Exists(
                    ActivityCheckIn.objects.filter(
                        student=student,
                        assignment=OuterRef("pk"),
                    )
                ),
                submission_count=Count(
                    "submissions",
                    filter=Q(submissions__student=student),
                ),
            )
    else:
        assignments = assignments.annotate(
            submission_count=Count("submissions")
        )
    assignments = assignments.order_by("-created_at", "-pk")
    pagination = paginate_queryset(request, assignments, 20)
    return render(
        request,
        "assignments.html",
        {
            "assignments": pagination["page_obj"].object_list,
            "classes": SchoolClass.objects.all(),
            "student_profile": student,
            **pagination,
        },
    )


@roles_required("student")
@require_http_methods(["POST"])
def activity_check_in(request, activity_type, activity_id):
    student = Student.objects.filter(user=request.user).first()
    if not student:
        messages.warning(request, "Your account is not linked to a student profile.")
        return redirect("dashboard")

    today = timezone.localdate()
    if activity_type == "assignment":
        activity = get_object_or_404(Assignment, pk=activity_id)
        if (
            activity.classroom_id
            and activity.classroom_id != student.classroom_id
        ):
            return permission_denied(request)
        activity_field = {"assignment": activity, "practical": None}
    elif activity_type == "practical":
        activity = get_object_or_404(Practical, pk=activity_id)
        activity_field = {"assignment": None, "practical": activity}
    else:
        raise Http404("Unknown activity type.")

    defaults = {
        "student": student,
        **activity_field,
        "check_in_date": today,
        "checkin_key": (
            f"{student.pk}:assignment:{activity.pk}"
            if activity_type == "assignment"
            else f"{student.pk}:practical:{activity.pk}:{today.isoformat()}"
        ),
    }
    if activity_type == "assignment":
        _, created = ActivityCheckIn.objects.get_or_create(
            student=student,
            assignment=activity,
            defaults=defaults,
        )
    else:
        _, created = ActivityCheckIn.objects.get_or_create(
            checkin_key=defaults["checkin_key"],
            defaults=defaults,
        )
    if created:
        create_notifications(
            User.objects.filter(
                role=User.Role.ADMIN, is_active=True
            ).values_list("pk", flat=True),
            f"{student.full_name} checked in for {activity.title}.",
        )
        messages.success(request, f"You checked in for {activity.title}.")
    else:
        if activity_type == "assignment":
            messages.info(request, "You have already checked in for this assignment.")
        else:
            messages.info(request, "You have already checked in for this activity today.")
    return redirect("assignments" if activity_type == "assignment" else "practicals")


@roles_required("admin")
def session_checkins(request):
    today = timezone.localdate()
    checkins = ActivityCheckIn.objects.select_related(
        "student", "assignment", "practical"
    ).order_by("-checked_in_at")[:200]
    return render(
        request,
        "session_checkins.html",
        {
            "checkins": checkins,
            "today_count": ActivityCheckIn.objects.filter(
                check_in_date=today
            ).count(),
        },
    )


@roles_required("student")
@require_http_methods(["POST"])
def submit_assignment(request, aid):
    student = Student.objects.filter(user=request.user).first()
    if not student:
        messages.warning(request, "Your account is not linked to a student profile.")
        return redirect("assignments")
    uploaded_file = request.FILES.get("file")
    if not uploaded_file or not uploaded_file.name:
        messages.warning(request, "Choose a file to submit.")
        return redirect("assignments")
    if not allowed_file(uploaded_file.name):
        messages.error(request, "Unsupported file type.")
        return redirect("assignments")
    assignment = get_object_or_404(Assignment, pk=aid)
    if assignment.classroom_id and assignment.classroom_id != student.classroom_id:
        return permission_denied(request)
    existing_submissions = Submission.objects.filter(
        assignment=assignment, student=student
    ).count()
    if existing_submissions >= 2:
        messages.error(request, "You have reached the maximum of 2 submission attempts.")
        return redirect("assignments")
    filename, file_content, content_type = save_upload(uploaded_file)
    Submission.objects.create(
        assignment=assignment,
        student=student,
        filename=filename,
        file_content=file_content,
        content_type=content_type,
        comments=request.POST.get("comments", ""),
        attempt_number=existing_submissions + 1,
    )
    create_notifications(
        User.objects.filter(
            role=User.Role.ADMIN, is_active=True
        ).values_list("pk", flat=True),
        f"{student.full_name} submitted {assignment.title} (Attempt {existing_submissions + 1}).",
    )
    attempt_text = "first" if existing_submissions == 0 else "second"
    messages.success(request, f"Your work has been submitted ({attempt_text} attempt).")
    return redirect("assignments")


@roles_required("admin", "teacher")
@require_http_methods(["GET", "POST"])
def submissions(request):
    if request.method == "POST":
        submission = get_object_or_404(
            Submission.objects.select_related("student__user", "assignment"),
            pk=int(request.POST["submission_id"]),
        )
        submission.marks = float(request.POST["marks"])
        submission.feedback = request.POST.get("feedback", "")
        submission.save(update_fields=["marks", "feedback"])
        if submission.student.user_id:
            Notification.objects.create(
                user=submission.student.user,
                message=f"Your work for {submission.assignment.title} has been marked.",
            )
        messages.success(request, "Marks and feedback saved.")
        return redirect("submissions")
    pagination = paginate_queryset(
        request,
        Submission.objects.select_related("student", "assignment").order_by(
            "-submitted_at", "-pk"
        ),
        50,
    )
    return render(
        request,
        "submissions.html",
        {"submissions": pagination["page_obj"].object_list, **pagination},
    )


@login_required
@require_http_methods(["GET", "POST"])
def practicals(request):
    if request.method == "POST":
        if request.user.role not in ("admin", "teacher"):
            return HttpResponseForbidden()
        uploaded_file = request.FILES.get("file")
        filename = ""
        attachment_content = None
        attachment_content_type = ""
        if uploaded_file and uploaded_file.name:
            if not allowed_file(uploaded_file.name):
                messages.error(request, "File type not allowed.")
                return redirect("practicals")
            filename, attachment_content, attachment_content_type = save_upload(uploaded_file)
        Practical.objects.create(
            title=request.POST["title"],
            objectives=request.POST.get("objectives", ""),
            instructions=request.POST.get("instructions", ""),
            software=request.POST.get("software", ""),
            attachment=filename,
            attachment_content=attachment_content,
            attachment_content_type=attachment_content_type,
            marks=int(request.POST.get("marks", 100)),
        )
        messages.success(request, "Practical activity added.")
        return redirect("practicals")
    student = Student.objects.filter(user=request.user).first()
    practicals = Practical.objects.order_by("-created_at")
    if student:
        practicals = practicals.annotate(
            checked_in_today=Exists(
                ActivityCheckIn.objects.filter(
                    student=student,
                    practical=OuterRef("pk"),
                    check_in_date=timezone.localdate(),
                )
            )
        )
    pagination = paginate_queryset(
        request, practicals.order_by("-created_at", "-pk"), 30
    )
    return render(
        request,
        "practicals.html",
        {
            "practicals": pagination["page_obj"].object_list,
            "student_profile": student,
            **pagination,
        },
    )


@roles_required("admin", "teacher")
@require_http_methods(["GET", "POST"])
def attendance(request):
    if request.method == "POST":
        student = get_object_or_404(Student, pk=int(request.POST["student_id"]))
        Attendance.objects.create(
            student=student,
            lesson_type=request.POST.get("lesson_type", "Theory"),
            lesson_date=date.fromisoformat(request.POST["lesson_date"]),
            status=request.POST["status"],
            marked_by=request.user,
        )
        messages.success(request, "Attendance saved.")
        return redirect("attendance")
    return render(
        request,
        "attendance.html",
        {
            "students": Student.objects.order_by("full_name"),
            "records": Attendance.objects.select_related("student")
            .order_by("-lesson_date")[:100],
        },
    )


@roles_required("admin", "technician")
@require_http_methods(["GET", "POST"])
def laboratory(request):
    if request.method == "POST":
        values = clean_computer_form(request)
        if values is None:
            return redirect("laboratory")
        if Computer.objects.filter(asset_tag__iexact=values["asset_tag"]).exists():
            messages.error(request, "A computer with that asset tag already exists.")
            return redirect("laboratory")
        Computer.objects.create(**values)
        messages.success(request, "Computer added to inventory.")
        return redirect("laboratory")
    return render(
        request,
        "laboratory.html",
        {
            "computers": Computer.objects.select_related("assigned_student")
            .prefetch_related("maintenance_records")
            .order_by("asset_tag"),
            "students": Student.objects.order_by("full_name"),
        },
    )


def clean_computer_form(request):
    try:
        return {
            "asset_tag": forms.CharField(max_length=50).clean(
                request.POST.get("asset_tag", "")
            ),
            "computer_name": forms.CharField(max_length=100, required=False).clean(
                request.POST.get("computer_name", "")
            ),
            "ip_address": forms.GenericIPAddressField(
                protocol="both", unpack_ipv4=False, required=False
            ).clean(request.POST.get("ip_address") or None),
            "assigned_student": forms.ModelChoiceField(
                queryset=Student.objects.all(), required=False
            ).clean(request.POST.get("assigned_student") or None),
            "brand_model": forms.CharField(max_length=120, required=False).clean(
                request.POST.get("brand_model", "")
            ),
            "processor": forms.CharField(max_length=120, required=False).clean(
                request.POST.get("processor", "")
            ),
            "ram": forms.CharField(max_length=40, required=False).clean(
                request.POST.get("ram", "")
            ),
            "storage": forms.CharField(max_length=40, required=False).clean(
                request.POST.get("storage", "")
            ),
            "operating_system": forms.CharField(max_length=100, required=False).clean(
                request.POST.get("operating_system", "")
            ),
            "location": forms.CharField(max_length=100, required=False).clean(
                request.POST.get("location", "")
            )
            or "Computer Laboratory",
            "condition": forms.ChoiceField(
                choices=[("Good", "Good"), ("Fair", "Fair"), ("Faulty", "Faulty")]
            ).clean(request.POST.get("condition", "Good")),
            "status": forms.ChoiceField(
                choices=[
                    ("Available", "Available"),
                    ("In Use", "In Use"),
                    ("Faulty", "Faulty"),
                    ("Under Maintenance", "Under Maintenance"),
                ]
            ).clean(request.POST.get("status", "Available")),
        }
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
        return None


@roles_required("admin", "technician")
def computer_detail(request, cid):
    computer = get_object_or_404(
        Computer.objects.select_related("assigned_student").prefetch_related(
            "maintenance_records"
        ),
        pk=cid,
    )
    return render(request, "laboratory_detail.html", {"computer": computer})


@roles_required("admin", "technician")
@require_http_methods(["GET", "POST"])
def edit_computer(request, cid):
    computer = get_object_or_404(Computer, pk=cid)
    if request.method == "POST":
        values = clean_computer_form(request)
        if values is None:
            return redirect("edit_computer", cid=computer.pk)
        if Computer.objects.filter(asset_tag__iexact=values["asset_tag"]).exclude(
            pk=computer.pk
        ).exists():
            messages.error(request, "A computer with that asset tag already exists.")
            return redirect("edit_computer", cid=computer.pk)
        for field, value in values.items():
            setattr(computer, field, value)
        computer.save()
        log_action(request.user, "Updated computer " + computer.asset_tag)
        messages.success(request, "Computer details updated.")
        return redirect("computer_detail", cid=computer.pk)

    return render(
        request,
        "laboratory_edit.html",
        {
            "computer": computer,
            "students": Student.objects.order_by("full_name"),
        },
    )


@roles_required("admin", "technician")
@require_http_methods(["POST"])
def delete_computer(request, cid):
    computer = get_object_or_404(Computer, pk=cid)
    asset_tag = computer.asset_tag
    computer.delete()
    log_action(request.user, "Deleted computer " + asset_tag)
    messages.success(request, "Computer and its maintenance records deleted.")
    return redirect("laboratory")


@roles_required("admin", "technician")
@require_http_methods(["POST"])
def report_fault(request, cid):
    computer = get_object_or_404(Computer, pk=cid)
    try:
        issue = forms.CharField().clean(request.POST.get("issue", ""))
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
        return redirect("computer_detail", cid=computer.pk)
    computer.status = "Faulty"
    computer.condition = "Faulty"
    computer.save(update_fields=["status", "condition"])
    Maintenance.objects.create(computer=computer, issue=issue)
    messages.success(request, "Fault report recorded.")
    return redirect("computer_detail", cid=computer.pk)


@roles_required("admin", "technician")
@require_http_methods(["GET", "POST"])
def edit_maintenance(request, mid):
    maintenance = get_object_or_404(
        Maintenance.objects.select_related("computer"), pk=mid
    )
    if request.method == "POST":
        try:
            issue = forms.CharField().clean(request.POST.get("issue", ""))
            action_taken = forms.CharField(required=False).clean(
                request.POST.get("action_taken", "")
            )
            status = forms.ChoiceField(
                choices=[
                    ("Reported", "Reported"),
                    ("In Progress", "In Progress"),
                    ("Resolved", "Resolved"),
                    ("Closed", "Closed"),
                ]
            ).clean(request.POST.get("status", "Reported"))
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
            return redirect("edit_maintenance", mid=maintenance.pk)
        maintenance.issue = issue
        maintenance.action_taken = action_taken
        maintenance.status = status
        maintenance.save(update_fields=["issue", "action_taken", "status"])
        log_action(
            request.user,
            "Updated maintenance record for " + maintenance.computer.asset_tag,
        )
        messages.success(request, "Maintenance record updated.")
        return redirect("computer_detail", cid=maintenance.computer_id)

    return render(
        request,
        "maintenance_edit.html",
        {"maintenance": maintenance},
    )


@roles_required("admin", "technician")
@require_http_methods(["POST"])
def delete_maintenance(request, mid):
    maintenance = get_object_or_404(
        Maintenance.objects.select_related("computer"), pk=mid
    )
    computer_id = maintenance.computer_id
    asset_tag = maintenance.computer.asset_tag
    maintenance.delete()
    log_action(request.user, "Deleted maintenance record for " + asset_tag)
    messages.success(request, "Maintenance record deleted.")
    return redirect("computer_detail", cid=computer_id)


@login_required
def notifications(request):
    items = Notification.objects.filter(user=request.user).order_by("-created_at")
    items.filter(read=False).update(read=True)
    pagination = paginate_queryset(
        request, items.order_by("-created_at", "-pk"), 50
    )
    return render(
        request,
        "notifications.html",
        {"notifications": pagination["page_obj"].object_list, **pagination},
    )


@roles_required("admin", "teacher")
def reports(request):
    average = Submission.objects.aggregate(average=Avg("marks"))["average"] or 0
    return render(
        request,
        "reports.html",
        {
            "students": Student.objects.count(),
            "avg": round(average, 1),
            "attendance_count": Attendance.objects.count(),
            "classes": SchoolClass.objects.select_related("academic_year")
            .annotate(student_count=Count("students"))
            .order_by("form", "name"),
            "computers": Computer.objects.all(),
        },
    )


@roles_required("admin")
@require_http_methods(["GET", "POST"])
def users(request):
    if request.method == "POST":
        username = request.POST["username"].strip()
        email = request.POST["email"].strip()
        if User.objects.filter(Q(username=username) | Q(email=email)).exists():
            messages.error(request, "Username or email already exists.")
        else:
            user = User(
                username=username,
                email=email,
                full_name=request.POST["full_name"],
                role=request.POST["role"],
            )
            user.set_password(request.POST["password"])
            user.save()
            messages.success(request, "User account created.")
        return redirect("users")
    pagination = paginate_queryset(
        request, User.objects.order_by("-created_at", "-pk"), 50
    )
    return render(
        request,
        "users.html",
        {
            "users": pagination["page_obj"].object_list,
            **pagination,
            "online_cutoff": timezone.now() - PRESENCE_TIMEOUT,
        },
    )


def permission_denied(request, exception=None):
    return render(
        request,
        "error.html",
        {
            "code": 403,
            "message": "You do not have permission to access this page.",
        },
        status=403,
    )


def page_not_found(request, exception=None):
    return render(
        request,
        "error.html",
        {
            "code": 404,
            "message": "The requested record or page could not be found.",
        },
        status=404,
    )
