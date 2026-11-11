from django.core.management.base import BaseCommand
from django.db import transaction
from portal.models import SchoolClass, Student, User


class Command(BaseCommand):
    help = 'Create 30 sample students (6 per class) with default password'

    def handle(self, *args, **options):
        first_names = [
            "James", "Mary", "John", "Patricia", "Robert", "Jennifer",
            "Michael", "Linda", "William", "Elizabeth", "David", "Barbara",
            "Richard", "Susan", "Joseph", "Jessica", "Thomas", "Sarah",
            "Charles", "Karen", "Christopher", "Nancy", "Daniel", "Lisa",
            "Matthew", "Betty", "Anthony", "Margaret", "Mark", "Sandra",
            "Donald", "Ashley"
        ]
        
        last_names = [
            "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia",
            "Miller", "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez",
            "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore",
            "Jackson", "Martin", "Lee", "Perez", "Thompson", "White",
            "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson"
        ]
        
        classes = list(SchoolClass.objects.all())
        if not classes:
            self.stdout.write(self.style.ERROR('No classes found. Please create classes first.'))
            return
        
        if len(classes) < 5:
            self.stdout.write(self.style.WARNING(f'Only {len(classes)} classes found. Will distribute students evenly.'))
        
        password = "1234567890"
        created_count = 0
        
        with transaction.atomic():
            for class_idx, classroom in enumerate(classes):
                for i in range(6):
                    first_name = first_names[(class_idx * 6 + i) % len(first_names)]
                    last_name = last_names[(class_idx * 6 + i) % len(last_names)]
                    full_name = f"{first_name} {last_name}"
                    
                    admission_no = f"2026{class_idx:02d}{i+1:02d}"
                    email = f"{first_name.lower()}.{last_name.lower()}@school.com"
                    
                    if User.objects.filter(username=admission_no).exists():
                        self.stdout.write(self.style.WARNING(f'Skipping {admission_no} - already exists'))
                        continue
                    
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
                        classroom=classroom,
                        user=user,
                        contact=email,
                        status="Active",
                    )
                    
                    created_count += 1
                    self.stdout.write(f'Created student: {full_name} ({admission_no}) in {classroom.name}')
        
        self.stdout.write(
            self.style.SUCCESS(f'Successfully created {created_count} sample students with default password: {password}')
        )
