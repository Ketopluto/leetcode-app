"""
Fix incorrect sections in database
Sets Year 3 and Year 4 sections to None (no section)
Keeps Year 2 sections as A and B
"""
from app import app, db
from app.models import Student

def fix_sections():
    with app.app_context():
        # Get all students
        all_students = Student.query.all()
        
        print("Current database state:")
        for year in [2, 3, 4]:
            year_students = Student.query.filter_by(year=year).all()
            sections = set([s.section for s in year_students])
            print(f"Year {year}: {len(year_students)} students, Sections: {sections}")
        
        print("\n" + "="*50)
        print("Fixing sections...")
        print("="*50 + "\n")
        
        # Fix Year 3: Remove all sections
        year3_students = Student.query.filter_by(year=3).all()
        for student in year3_students:
            if student.section is not None:
                print(f"Fixing Year 3 student: {student.name} (was Section {student.section})")
                student.section = None
        
        # Fix Year 4: Remove all sections
        year4_students = Student.query.filter_by(year=4).all()
        for student in year4_students:
            if student.section is not None:
                print(f"Fixing Year 4 student: {student.name} (was Section {student.section})")
                student.section = None
        
        # Commit changes
        db.session.commit()
        
        print("\n" + "="*50)
        print("After fix:")
        print("="*50 + "\n")
        
        for year in [2, 3, 4]:
            year_students = Student.query.filter_by(year=year).all()
            sections = set([s.section for s in year_students])
            print(f"Year {year}: {len(year_students)} students, Sections: {sections}")
        
        print("\n✅ Database fixed successfully!")
        print("\nExpected result:")
        print("- Year 2: Sections A and B")
        print("- Year 3: No sections (None)")
        print("- Year 4: No sections (None)")

if __name__ == '__main__':
    fix_sections()
