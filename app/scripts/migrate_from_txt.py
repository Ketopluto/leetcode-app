"""
One-time migration script to move data from students.txt to SQLite database.
Run this from project root: python -m app.scripts.migrate_from_txt
"""
import os
import sys

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

# Import app components
from app import app, db
from app.models import Student

def migrate_students():
    with app.app_context():
        # Create tables if they don't exist
        db.create_all()
        
        # Look for students.txt in project root
        students_txt_path = os.path.join(project_root, 'students.txt')
        
        if not os.path.exists(students_txt_path):
            print(f"❌ students.txt not found at: {students_txt_path}")
            print(f"   Please ensure students.txt is in the project root directory.")
            return
        
        current_year = None
        added = 0
        skipped = 0
        
        print("📚 Starting migration from students.txt to database...")
        print(f"📁 Reading from: {students_txt_path}")
        
        with open(students_txt_path, 'r', encoding='utf-8') as file:
            for line_num, line in enumerate(file, 1):
                line = line.strip()
                if not line:
                    continue
                
                if line.endswith("Students:"):
                    year_text = line.replace("Students:", "").strip()
                    if "3rd" in year_text:
                        current_year = 3
                    elif "4th" in year_text:
                        current_year = 4
                    elif "2nd" in year_text:
                        current_year = 2
                    elif "1st" in year_text:
                        current_year = 1
                    print(f"\n📖 Processing {year_text}...")
                else:
                    parts = line.split(",")
                    if len(parts) == 3 and current_year:
                        username = parts[0].strip()
                        name = parts[1].strip()
                        roll_no = parts[2].strip()
                        
                        # Check if already exists
                        existing = Student.query.filter_by(register_number=roll_no).first()
                        
                        if not existing:
                            year, section = Student.extract_year_and_section(roll_no)
                            
                            student = Student(
                                register_number=roll_no,
                                name=name,
                                leetcode_username=username,
                                year=current_year,  # Use detected year from file
                                section=section
                            )
                            db.session.add(student)
                            added += 1
                            print(f"  ✅ Added: {name} ({roll_no})")
                        else:
                            skipped += 1
                            print(f"  ⏭️  Skipped (exists): {name} ({roll_no})")
        
        db.session.commit()
        print(f"\n🎉 Migration complete!")
        print(f"   ✅ Added: {added} students")
        print(f"   ⏭️  Skipped: {skipped} students (already exist)")
        
        db_path = os.path.join(project_root, 'leetcode_stats.db')
        print(f"\n💾 Database location: {db_path}")

if __name__ == '__main__':
    migrate_students()
