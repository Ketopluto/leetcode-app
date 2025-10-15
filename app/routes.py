import csv
import os
import io
import asyncio
import aiohttp
from datetime import datetime
from flask import render_template, make_response, request, jsonify, redirect, url_for, flash, session
from werkzeug.utils import secure_filename
import pandas as pd
from app import app, cache, db
from app.models import Student, UploadLog


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


def get_available_year_sections():
    """Get list of available year and section combinations from database"""
    year_sections = db.session.query(
        Student.year, 
        Student.section
    ).distinct().order_by(Student.year, Student.section).all()
    
    options = []
    for year, section in year_sections:
        year_suffix = 'st' if year == 1 else 'nd' if year == 2 else 'rd' if year == 3 else 'th'
        year_str = f"{year}{year_suffix} Year"
        
        if section:
            options.append(f"{year_str} ({section})")
        else:
            options.append(year_str)
    
    print(f"Available year-section options: {options}")
    return options


def load_students_from_db():
    """Load all students from database"""
    students = Student.query.all()
    return [(s.leetcode_username, s.name, s.register_number, s.year, s.section) 
            for s in students]


async def fetch_leetcode_stats_async(username):
    """Asynchronously fetch LeetCode statistics."""
    if username.lower() == "higher studies" or not username:
        return {"easy": 0, "medium": 0, "hard": 0, "total": 0}
    
    url = f"https://leetcode-api-faisalshohag.vercel.app/{username}"
    full_url = f"{url}?t={datetime.now().timestamp()}"
    
    timeout = aiohttp.ClientTimeout(total=5)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for attempt in range(3):
            try:
                async with session.get(full_url) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {
                            "easy": data.get("easySolved", 0),
                            "medium": data.get("mediumSolved", 0),
                            "hard": data.get("hardSolved", 0),
                            "total": data.get("totalSolved", 0)
                        }
                await asyncio.sleep(0.5 * (attempt + 1))
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                print(f"Attempt {attempt+1} failed for {username}: {e}")
                if attempt < 2:
                    await asyncio.sleep(0.5 * (attempt + 1))
    
    return {"easy": 0, "medium": 0, "hard": 0, "total": 0}


aasync def fetch_all_stats_async():
    """Fetch stats for all students in optimized batches."""
    students = load_students_from_db()
    
    # Larger batches for Vercel (has more memory than Render)
    batch_size = 50  # Increased from 20
    all_results = []
    
    connector = aiohttp.TCPConnector(limit=25)  # Increased from 10
    timeout = aiohttp.ClientTimeout(total=8)  # Slightly reduced for faster failure
    
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        for i in range(0, len(students), batch_size):
            batch = students[i:i+batch_size]
            print(f"Processing batch {i//batch_size + 1}/{(len(students) + batch_size - 1)//batch_size}")
            
            tasks = []
            for username, name, roll_no, year, section in batch:
                task = fetch_student_stats_async(username, name, roll_no, year, section, session)
                tasks.append(task)
            
            # Process this batch
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Filter out exceptions and add valid results
            for result in batch_results:
                if isinstance(result, dict):
                    all_results.append(result)
            
            # Smaller delay between batches
            if i + batch_size < len(students):
                await asyncio.sleep(0.2)  # Reduced from 0.5
    
    return all_results

async def fetch_student_stats_async(username, name, roll_no, year, section, session):
    """Fetch a student's stats using an existing session."""
    if username.lower() == "higher studies" or not username:
        stats = {"easy": 0, "medium": 0, "hard": 0, "total": 0}
    else:
        url = f"https://leetcode-api-faisalshohag.vercel.app/{username}"
        
        stats = {"easy": 0, "medium": 0, "hard": 0, "total": 0}
        try:
            for attempt in range(2):  # Reduced from 3 attempts to 2
                try:
                    async with session.get(url) as response:
                        if response.status == 200:
                            data = await response.json()
                            stats = {
                                "easy": data.get("easySolved", 0),
                                "medium": data.get("mediumSolved", 0),
                                "hard": data.get("hardSolved", 0),
                                "total": data.get("totalSolved", 0)
                            }
                            break
                except Exception as e:
                    if attempt < 1:
                        await asyncio.sleep(0.2)  # Reduced from 0.5
        except Exception as e:
            print(f"Error fetching {username}: {e}")
    
    # Format year string
    year_suffix = 'st' if year == 1 else 'nd' if year == 2 else 'rd' if year == 3 else 'th'
    year_str = f"{year}{year_suffix} Year"
    
    # Create display string with section if it exists
    if section:
        year_display = f"{year_str} ({section})"
    else:
        year_display = year_str
    
    return {
        "roll_no": roll_no,
        "actual_name": name,
        "username": username,
        "year": year_str,
        "year_display": year_display,
        "year_number": year,
        "section": section,
        "easy": stats["easy"],
        "medium": stats["medium"],
        "hard": stats["hard"],
        "total": stats["total"]
    }


async def fetch_detailed_leetcode_stats(username):
    """Fetch comprehensive LeetCode statistics for a student"""
    if username.lower() == "higher studies" or not username:
        return {
            "username": username,
            "totalSolved": 0,
            "easySolved": 0,
            "mediumSolved": 0,
            "hardSolved": 0,
            "totalSubmissions": [],
            "recentSubmissions": [],
            "ranking": 0,
            "contributionPoint": 0,
            "reputation": 0,
            "profile_url": None
        }
    
    url = f"https://leetcode-api-faisalshohag.vercel.app/{username}"
    
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    recent_submissions = data.get("recentSubmissions", [])[:20]
                    
                    return {
                        "username": username,
                        "totalSolved": data.get("totalSolved", 0),
                        "easySolved": data.get("easySolved", 0),
                        "mediumSolved": data.get("mediumSolved", 0),
                        "hardSolved": data.get("hardSolved", 0),
                        "totalSubmissions": data.get("totalSubmissions", []),
                        "recentSubmissions": recent_submissions,
                        "ranking": data.get("ranking", 0),
                        "contributionPoint": data.get("contributionPoint", 0),
                        "reputation": data.get("reputation", 0),
                        "acceptance_rate": data.get("acceptanceRate", 0),
                        "profile_url": f"https://leetcode.com/u/{username}/"
                    }
        except Exception as e:
            print(f"Error fetching detailed stats for {username}: {e}")
    
    return {
        "username": username,
        "totalSolved": 0,
        "easySolved": 0,
        "mediumSolved": 0,
        "hardSolved": 0,
        "totalSubmissions": [],
        "recentSubmissions": [],
        "ranking": 0,
        "contributionPoint": 0,
        "reputation": 0,
        "profile_url": f"https://leetcode.com/u/{username}/"
    }


def get_all_stats():
    """Synchronous wrapper to get all stats using asyncio."""
    return asyncio.run(fetch_all_stats_async())


@app.route("/")
def index():
    return render_template("index.html", available_years=get_available_year_sections())


@app.route("/health")
def health_check():
    """Health check endpoint for Render"""
    try:
        count = Student.query.count()
        return {
            "status": "healthy", 
            "message": "LeetCode Stats Dashboard is running",
            "students": count
        }, 200
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }, 500


@app.route("/student/<register_number>")
def student_profile(register_number):
    """Display detailed profile for a specific student"""
    student = Student.query.filter_by(register_number=register_number).first()
    
    if not student:
        flash('Student not found', 'error')
        return redirect(url_for('index'))
    
    username = student.leetcode_username
    
    try:
        stats = asyncio.run(fetch_detailed_leetcode_stats(username))
        
        return render_template(
            "student_profile.html",
            student=student,
            stats=stats,
            year_display=f"{student.year}{'st' if student.year == 1 else 'nd' if student.year == 2 else 'rd' if student.year == 3 else 'th'} Year"
        )
    except Exception as e:
        flash(f'Error fetching student stats: {str(e)}', 'error')
        return redirect(url_for('index'))


@app.route("/admin")
def admin():
    """Admin panel for HoD to upload Excel files"""
    if not session.get('hod_authenticated'):
        return redirect(url_for('admin_login'))
    
    logs = UploadLog.query.order_by(UploadLog.upload_time.desc()).limit(10).all()
    student_count = Student.query.count()
    years_data = db.session.query(Student.year, db.func.count(Student.id)).group_by(Student.year).all()
    
    return render_template("admin.html", logs=logs, student_count=student_count, years_data=years_data)


@app.route("/admin/login", methods=['GET', 'POST'])
def admin_login():
    """HoD login page"""
    if request.method == 'POST':
        password = request.form.get('password')
        if password == app.config['HOD_PASSWORD']:
            session['hod_authenticated'] = True
            session.permanent = True
            return redirect(url_for('admin'))
        else:
            flash('Invalid password. Please try again.', 'error')
    
    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    """Logout HoD"""
    session.pop('hod_authenticated', None)
    flash('Logged out successfully.', 'success')
    return redirect(url_for('index'))


@app.route("/admin/upload", methods=['POST'])
def upload_excel():
    """Handle Excel file upload and parse data"""
    if not session.get('hod_authenticated'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'No file uploaded'}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'success': False, 'message': 'No file selected'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'success': False, 'message': 'Invalid file type. Please upload .xlsx or .xls file'}), 400
    
    # Get year and section from form
    selected_year = request.form.get('year')
    selected_section = request.form.get('section')
    
    if not selected_year:
        return jsonify({'success': False, 'message': 'Please select a year'}), 400
    
    try:
        year = int(selected_year)
        if year < 1 or year > 4:
            return jsonify({'success': False, 'message': 'Invalid year. Must be between 1-4'}), 400
    except ValueError:
        return jsonify({'success': False, 'message': 'Invalid year format'}), 400
    
    # Section can be None or a letter (A, B, C, etc.)
    section = selected_section if selected_section and selected_section != '' else None
    
    try:
        df = pd.read_excel(file)
        
        # Clean column names - handle NaN and floats properly
        cleaned_columns = []
        for i, col in enumerate(df.columns):
            if pd.notna(col):
                col_clean = str(col).strip().lower()
                cleaned_columns.append(col_clean)
            else:
                cleaned_columns.append(f'unnamed_{i}')
        
        df.columns = cleaned_columns
        
        print(f"Detected columns: {list(df.columns)}")
        
        column_mapping = {}
        
        for col in df.columns:
            col_str = str(col).lower().strip()
            
            if ('register' in col_str or 'roll' in col_str or 'reg' in col_str) and 'register_number' not in column_mapping:
                column_mapping['register_number'] = col
            
            elif 'name' in col_str and 'user' not in col_str and 'name' not in column_mapping:
                column_mapping['name'] = col
            
            elif ('leetcode' in col_str or 'profile' in col_str or 'username' in col_str or 'url' in col_str) and 'leetcode' not in column_mapping:
                column_mapping['leetcode'] = col
        
        print(f"Column mapping: {column_mapping}")
        
        if len(column_mapping) < 3:
            return jsonify({
                'success': False,
                'message': f'Excel must contain columns for: Register Number, Name, and LeetCode Username/URL. Found columns: {list(df.columns)}. Detected: {list(column_mapping.keys())}'
            }), 400
        
        records_added = 0
        records_updated = 0
        errors = []
        
        for index, row in df.iterrows():
            try:
                register_number = str(row[column_mapping['register_number']]).strip()
                name = str(row[column_mapping['name']]).strip()
                leetcode_input = str(row[column_mapping['leetcode']]).strip()
                
                if (not register_number or register_number.lower() == 'nan' or pd.isna(row[column_mapping['register_number']])):
                    continue
                
                if (not name or name.lower() == 'nan' or pd.isna(row[column_mapping['name']])):
                    continue
                
                if (not leetcode_input or leetcode_input.lower() == 'nan' or pd.isna(row[column_mapping['leetcode']])):
                    continue
                
                leetcode_username = Student.extract_username_from_url(leetcode_input)
                
                if not leetcode_username:
                    errors.append(f"Row {index + 2}: Invalid LeetCode username for {name}")
                    continue
                
                existing_student = Student.query.filter_by(register_number=register_number).first()
                
                if existing_student:
                    existing_student.name = name
                    existing_student.leetcode_username = leetcode_username
                    existing_student.year = year
                    existing_student.section = section
                    existing_student.updated_at = datetime.utcnow()
                    records_updated += 1
                else:
                    new_student = Student(
                        register_number=register_number,
                        name=name,
                        leetcode_username=leetcode_username,
                        year=year,
                        section=section
                    )
                    db.session.add(new_student)
                    records_added += 1
                
            except Exception as e:
                errors.append(f"Row {index + 2}: {str(e)}")
                continue
        
        db.session.commit()
        
        upload_log = UploadLog(
            filename=secure_filename(file.filename),
            records_added=records_added,
            records_updated=records_updated,
            status='success' if not errors else 'partial',
            error_message='; '.join(errors[:5]) if errors else None
        )
        db.session.add(upload_log)
        db.session.commit()
        
        cache.clear()
        
        section_text = f" (Section {section})" if section else ""
        message = f"Successfully processed for Year {year}{section_text}! Added: {records_added}, Updated: {records_updated}"
        if errors:
            message += f". {len(errors)} errors occurred."
        
        return jsonify({
            'success': True,
            'message': message,
            'records_added': records_added,
            'records_updated': records_updated,
            'errors': errors[:10]
        })
    
    except Exception as e:
        db.session.rollback()
        import traceback
        print("=" * 50)
        print("ERROR in upload_excel:")
        print(traceback.format_exc())
        print("=" * 50)
        return jsonify({'success': False, 'message': f'Error processing file: {str(e)}'}), 500


@app.route("/admin/students")
def admin_students():
    """View and manage all students with pagination"""
    if not session.get('hod_authenticated'):
        return redirect(url_for('admin_login'))
    
    # Get filter parameters
    search = request.args.get('search', '')
    year_filter = request.args.get('year', '')
    section_filter = request.args.get('section', '')
    page = request.args.get('page', 1, type=int)
    per_page = 25
    
    # Build query
    query = Student.query
    
    if search:
        query = query.filter(
            (Student.name.ilike(f'%{search}%')) |
            (Student.register_number.ilike(f'%{search}%')) |
            (Student.leetcode_username.ilike(f'%{search}%'))
        )
    
    if year_filter:
        query = query.filter_by(year=int(year_filter))
    
    if section_filter:
        query = query.filter_by(section=section_filter)
    
    # Paginate
    pagination = query.order_by(Student.year, Student.section, Student.register_number).paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )
    
    # Get unique years and sections for filters
    years = db.session.query(Student.year).distinct().order_by(Student.year).all()
    sections = db.session.query(Student.section).filter(Student.section.isnot(None)).distinct().all()
    
    return render_template(
        "admin_students.html",
        students=pagination.items,
        pagination=pagination,
        years=[y[0] for y in years],
        sections=[s[0] for s in sections],
        search=search,
        year_filter=year_filter,
        section_filter=section_filter
    )


@app.route("/admin/student/edit/<int:student_id>", methods=['GET', 'POST'])
def admin_edit_student(student_id):
    """Edit a student's information"""
    if not session.get('hod_authenticated'):
        return redirect(url_for('admin_login'))
    
    student = Student.query.get_or_404(student_id)
    
    if request.method == 'POST':
        try:
            # Get form data
            name = request.form.get('name', '').strip()
            register_number = request.form.get('register_number', '').strip()
            leetcode_input = request.form.get('leetcode_username', '').strip()
            year = int(request.form.get('year'))
            section = request.form.get('section', '').strip()
            
            if not name or not register_number or not leetcode_input:
                flash('All fields are required', 'error')
                return redirect(url_for('admin_edit_student', student_id=student_id))
            
            # Check if register number already exists (for another student)
            existing = Student.query.filter(
                Student.register_number == register_number,
                Student.id != student_id
            ).first()
            
            if existing:
                flash(f'Register number {register_number} already exists for another student', 'error')
                return redirect(url_for('admin_edit_student', student_id=student_id))
            
            # Extract username from URL if needed
            leetcode_username = Student.extract_username_from_url(leetcode_input)
            
            # Update student
            student.name = name
            student.register_number = register_number
            student.leetcode_username = leetcode_username
            student.year = year
            student.section = section if section else None
            student.updated_at = datetime.utcnow()
            
            db.session.commit()
            cache.clear()
            
            flash(f'Successfully updated {name}', 'success')
            return redirect(url_for('admin_students'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating student: {str(e)}', 'error')
            return redirect(url_for('admin_edit_student', student_id=student_id))
    
    return render_template("admin_edit_student.html", student=student)


@app.route("/admin/student/delete/<int:student_id>", methods=['POST'])
def admin_delete_student(student_id):
    """Delete a student"""
    if not session.get('hod_authenticated'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    try:
        student = Student.query.get_or_404(student_id)
        name = student.name
        
        db.session.delete(student)
        db.session.commit()
        cache.clear()
        
        return jsonify({
            'success': True,
            'message': f'Successfully deleted {name}'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Error deleting student: {str(e)}'
        }), 500


@app.route("/admin/logs")
def admin_logs():
    """View upload logs"""
    if not session.get('hod_authenticated'):
        return redirect(url_for('admin_login'))
    
    logs = UploadLog.query.order_by(UploadLog.upload_time.desc()).limit(50).all()
    return render_template("admin_logs.html", logs=logs)


@app.route("/download")
def download_csv():
    selected_filter = request.args.get("year", None)
    
    all_results = get_all_stats()
    
    if selected_filter:
        results = [r for r in all_results if r["year_display"] == selected_filter]
    else:
        results = all_results
    
    results.sort(key=lambda x: x["roll_no"])
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Roll Number", "Name", "LeetCode Username", "Year", "Easy Solved", "Medium Solved", "Hard Solved", "Total Solved"])
    
    for row in results:
        writer.writerow([row["roll_no"], row["actual_name"], row["username"], row["year_display"],
                        row["easy"], row["medium"], row["hard"], row["total"]])
    
    response = make_response(output.getvalue())
    filename = f"leetcode_stats_{selected_filter.replace(' ', '_').replace('(', '').replace(')', '') if selected_filter else 'all'}.csv"
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    response.headers["Content-type"] = "text/csv"
    
    return response


@app.route("/api/stats")
def api_stats():
    selected_filter = request.args.get("year", None)
    
    print(f"API called with filter: '{selected_filter}'")
    
    all_results = get_all_stats()
    
    if selected_filter:
        results = [r for r in all_results if r["year_display"] == selected_filter]
        print(f"Filtered results: {len(results)} out of {len(all_results)}")
    else:
        results = all_results
    
    results.sort(key=lambda x: x["roll_no"])
    
    return {"results": results, "available_years": get_available_year_sections()}
