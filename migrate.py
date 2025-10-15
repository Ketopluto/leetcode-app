"""
Migration script: SQLite → PostgreSQL (Supabase)
Run this locally to migrate existing data to Supabase
"""

import os
from app import app, db
from app.models import Student, UploadLog
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
os.load_env('.env')

# Your Supabase connection string (get from Supabase dashboard)
SUPABASE_URL = os.getenv("DATABASE_URL")

def migrate_data():
    print("=" * 60)
    print("SQLite → PostgreSQL Migration")
    print("=" * 60)
    
    # Connect to SQLite (source)
    sqlite_engine = create_engine('sqlite:///leetcode_stats.db')
    SQLiteSession = sessionmaker(bind=sqlite_engine)
    sqlite_session = SQLiteSession()
    
    # Connect to PostgreSQL (destination)
    postgres_engine = create_engine(SUPABASE_URL)
    PostgresSession = sessionmaker(bind=postgres_engine)
    postgres_session = PostgresSession()
    
    try:
        # Create tables in PostgreSQL if they don't exist
        print("\n1️⃣ Creating tables in PostgreSQL...")
        with app.app_context():
            app.config['SQLALCHEMY_DATABASE_URI'] = SUPABASE_URL
            db.create_all()
        print("✅ Tables created!")
        
        # Migrate Students
        print("\n2️⃣ Migrating students...")
        students = sqlite_session.query(Student).all()
        print(f"Found {len(students)} students in SQLite")
        
        for student in students:
            # Check if student already exists in PostgreSQL
            existing = postgres_session.query(Student).filter_by(
                register_number=student.register_number
            ).first()
            
            if not existing:
                new_student = Student(
                    register_number=student.register_number,
                    name=student.name,
                    leetcode_username=student.leetcode_username,
                    year=student.year,
                    section=student.section,
                    created_at=student.created_at,
                    updated_at=student.updated_at
                )
                postgres_session.add(new_student)
                print(f"  ✅ Migrated: {student.name} ({student.register_number})")
            else:
                print(f"  ⏭️  Skipped (exists): {student.name}")
        
        postgres_session.commit()
        print(f"\n✅ Successfully migrated {len(students)} students!")
        
        # Migrate Upload Logs (optional)
        print("\n3️⃣ Migrating upload logs...")
        logs = sqlite_session.query(UploadLog).all()
        print(f"Found {len(logs)} upload logs")
        
        for log in logs:
            new_log = UploadLog(
                filename=log.filename,
                upload_time=log.upload_time,
                records_added=log.records_added,
                records_updated=log.records_updated,
                status=log.status,
                error_message=log.error_message
            )
            postgres_session.add(new_log)
        
        postgres_session.commit()
        print(f"✅ Successfully migrated {len(logs)} logs!")
        
        # Verify migration
        print("\n4️⃣ Verifying migration...")
        pg_student_count = postgres_session.query(Student).count()
        pg_log_count = postgres_session.query(UploadLog).count()
        
        print(f"\n📊 Final Count in PostgreSQL:")
        print(f"   Students: {pg_student_count}")
        print(f"   Logs: {pg_log_count}")
        
        print("\n" + "=" * 60)
        print("🎉 Migration completed successfully!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Error during migration: {e}")
        postgres_session.rollback()
        import traceback
        traceback.print_exc()
    
    finally:
        sqlite_session.close()
        postgres_session.close()

if __name__ == '__main__':
    print("\n⚠️  WARNING: Make sure you have:")
    print("   1. Created Supabase project")
    print("   2. Updated SUPABASE_URL in this script")
    print("   3. Installed psycopg2-binary: pip install psycopg2-binary")
    
    response = input("\nReady to migrate? (yes/no): ")
    
    if response.lower() == 'yes':
        migrate_data()
    else:
        print("Migration cancelled.")
