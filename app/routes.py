import csv
import os
import io
import time
import threading
import asyncio
import aiohttp
from datetime import datetime
from flask import render_template, make_response, request, jsonify, redirect, url_for, flash, session
from werkzeug.utils import secure_filename
import pandas as pd

from app import app, cache, db
from app.models import Student, UploadLog, StudentStats, WeeklyReport
from app.logger import log_info, log_error, log_debug, log_exception
from app.leetcode_api import (
    fetch_students_concurrent,
    get_circuit_breaker_status,
    CACHE_TTL,
    CONCURRENCY,
    TIMEOUT_SECONDS
)

# -----------------------
# Configurable tunables (now in leetcode_api.py, kept here for backward compat)
# -----------------------
# CACHE_TTL, CONCURRENCY, TIMEOUT_SECONDS imported from leetcode_api
FETCH_ATTEMPTS = 3  # retry attempts per API source
# -----------------------

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

    log_debug(f"Available year-section options: {options}", tag="DB")
    return options


def load_students_from_db():
    """Load all students from database"""
    students = Student.query.all()
    return [(s.leetcode_username, s.name, s.register_number, s.year, s.section)
            for s in students]


# NOTE: fetch_students_concurrent is now imported from leetcode_api.py
# which has fallback APIs, circuit breaker, and exponential backoff


def get_all_stats(cache_ttl=CACHE_TTL, concurrency=CONCURRENCY, timeout_seconds=TIMEOUT_SECONDS):
    """
    Synchronous wrapper used by Flask routes. It:
    1) loads students from DB,
    2) returns cached stats for students that have them (memory cache),
    3) concurrently fetches only the missing ones using robust API module,
    4) stores fetched results in memory cache AND database (for fallback),
    5) returns combined list.
    """
    students = load_students_from_db()  # returns tuples (username, name, roll, year, section)
    cached_results = []
    to_fetch = []

    # Also load student IDs for database operations
    student_id_map = {}  # username.lower() -> student_id
    for student in Student.query.all():
        if student.leetcode_username:
            student_id_map[student.leetcode_username.strip().lower()] = student.id

    # Load cached stats from database for fallback
    db_stats_map = {}  # username.lower() -> {easy_solved, medium_solved, hard_solved, total_solved}
    for stats in StudentStats.query.all():
        if stats.student:
            uname = (stats.student.leetcode_username or "").strip().lower()
            db_stats_map[uname] = {
                "easy_solved": stats.easy_solved,
                "medium_solved": stats.medium_solved,
                "hard_solved": stats.hard_solved,
                "total_solved": stats.total_solved
            }

    # collect cached ones and decide which to fetch
    for username, name, roll, year, section in students:
        key = f"stats:{(username or '').strip().lower()}"
        try:
            cached = cache.get(key)
        except Exception:
            cached = None

        if cached and isinstance(cached, dict):
            cached_results.append(cached)
        else:
            to_fetch.append((username, name, roll, year, section))

    # fetch missing ones concurrently using robust API module
    if to_fetch:
        try:
            fetched = asyncio.run(fetch_students_concurrent(
                to_fetch,
                cached_stats_map=db_stats_map,
                concurrency=concurrency
            ))
        except Exception as e:
            # on a catastrophic failure, fallback to DB cached results
            log_error(f"Error during concurrent fetch: {e}", tag="API")
            fetched = []
            # Build fallback results from database
            for username, name, roll, year, section in to_fetch:
                uname = (username or "").strip().lower()
                db_cached = db_stats_map.get(uname, {})
                year_suffix = 'st' if year == 1 else 'nd' if year == 2 else 'rd' if year == 3 else 'th'
                year_str = f"{year}{year_suffix} Year"
                year_display = f"{year_str} ({section})" if section else year_str
                fetched.append({
                    "roll_no": roll,
                    "actual_name": name,
                    "username": username,
                    "year": year_str,
                    "year_display": year_display,
                    "year_number": year,
                    "section": section,
                    "easy": db_cached.get("easy_solved", 0),
                    "medium": db_cached.get("medium_solved", 0),
                    "hard": db_cached.get("hard_solved", 0),
                    "total": db_cached.get("total_solved", 0),
                    "fetch_error": None,
                    "is_stale": True,
                    "fetched_at": int(time.time())
                })

        # save to memory cache AND database
        for item in fetched:
            try:
                uname = (item.get("username") or "").strip().lower()
                
                # Save to memory cache
                cache_key = f"stats:{uname}"
                cache.set(cache_key, item, timeout=cache_ttl)
                
                # Save to database (for fallback on future failures)
                # Only update DB if we got fresh data (not stale) and there's no error
                is_stale = item.get("is_stale", False)
                has_error = item.get("fetch_error") is not None
                if not is_stale and not has_error:
                    student_id = student_id_map.get(uname)
                    if student_id:
                        stats = StudentStats.query.filter_by(student_id=student_id).first()
                        if not stats:
                            stats = StudentStats(student_id=student_id)
                            db.session.add(stats)
                        
                        stats.easy_solved = item.get("easy", 0)
                        stats.medium_solved = item.get("medium", 0)
                        stats.hard_solved = item.get("hard", 0)
                        stats.total_solved = item.get("total", 0)
                        stats.last_updated = datetime.utcnow()
                        stats.is_stale = False
                        
            except Exception as e:
                log_error(f"Error saving stats for {uname}: {e}", tag="DB")
        
        # Commit database changes
        try:
            db.session.commit()
        except Exception as e:
            log_error(f"Error committing stats to database: {e}", tag="DB")
            db.session.rollback()

        results = cached_results + fetched
    else:
        results = cached_results

    # final sort by roll_no (numeric if possible)
    def safe_roll(x):
        try:
            return int(''.join(filter(str.isdigit, str(x.get("roll_no") or "")))) or 0
        except Exception:
            return 0

    results.sort(key=lambda r: safe_roll(r))
    return results


# Optional: helper to refresh cache in background (non-blocking)
def refresh_all_stats_in_background(cache_ttl=CACHE_TTL, concurrency=CONCURRENCY, timeout_seconds=TIMEOUT_SECONDS):
    def _refresh():
        try:
            with app.app_context():
                _ = get_all_stats(cache_ttl=cache_ttl, concurrency=concurrency, timeout_seconds=timeout_seconds)
        except Exception as e:
            log_error(f"Background refresh failed: {e}", tag="Cache")
    t = threading.Thread(target=_refresh, daemon=True)
    t.start()


# -----------------------
# Detailed single student fetch (used in profile view)
# -----------------------
async def _fetch_detailed_with_session(username, session, timeout_seconds=10):
    """Async helper to fetch detailed LeetCode stats for a single username."""
    if not username or username.lower() == "higher studies":
        return None

    base_url = "https://alfa-leetcode-api-blush.vercel.app"
    profile_url = f"{base_url}/{username}"
    solved_url = f"{base_url}/{username}/solved"
    submission_url = f"{base_url}/{username}/submission?limit=20"
    
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as s:
            # Fetch all endpoints concurrently
            results = await asyncio.gather(
                s.get(profile_url),
                s.get(solved_url),
                s.get(submission_url),
                return_exceptions=True
            )
            
            profile_data = {}
            solved_data = {}
            submission_data = {}
            
            # Process profile
            if isinstance(results[0], aiohttp.ClientResponse) and results[0].status == 200:
                profile_data = await results[0].json()
            
            # Process solved
            if isinstance(results[1], aiohttp.ClientResponse) and results[1].status == 200:
                solved_data = await results[1].json()
            
            # Process submissions
            if isinstance(results[2], aiohttp.ClientResponse) and results[2].status == 200:
                submission_data = await results[2].json()
            
            # Calculate acceptance rate from acSubmissionNum and totalSubmissionNum
            acceptance_rate = 0
            total_submissions_data = solved_data.get("totalSubmissionNum", [])
            ac_submissions_data = solved_data.get("acSubmissionNum", [])
            
            all_total = next((x for x in total_submissions_data if x.get('difficulty') == 'All'), None)
            all_ac = next((x for x in ac_submissions_data if x.get('difficulty') == 'All'), None)
            
            if all_total and all_ac:
                total_sub_count = all_total.get('submissions', 0)
                ac_sub_count = all_ac.get('submissions', 0)
                if total_sub_count > 0:
                    acceptance_rate = round((ac_sub_count / total_sub_count) * 100, 2)
            
            recent_submissions = submission_data.get("submission", [])[:20]
            
            return {
                "username": username,
                "totalSolved": solved_data.get("solvedProblem", 0),
                "easySolved": solved_data.get("easySolved", 0),
                "mediumSolved": solved_data.get("mediumSolved", 0),
                "hardSolved": solved_data.get("hardSolved", 0),
                "totalSubmissions": solved_data.get("totalSubmissionNum", []),
                "recentSubmissions": recent_submissions,
                "ranking": profile_data.get("ranking", 0),
                "contributionPoint": 0,  # Not available in this API
                "reputation": profile_data.get("reputation", 0),
                "acceptance_rate": acceptance_rate,
                "profile_url": f"https://leetcode.com/u/{username}/"
            }
    except Exception as e:
        log_error(f"Error fetching detailed stats for {username}: {e}", tag="API")
    return None


def fetch_detailed_leetcode_stats(username):
    """Synchronous wrapper used by Flask to fetch detailed stats for a single student."""
    if not username or username.lower() == "higher studies":
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
    try:
        # run short async helper
        return asyncio.run(_fetch_detailed_with_session(username, None))
    except Exception as e:
        log_error(f"fetch_detailed_leetcode_stats error: {e}", tag="API")
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


# -----------------------
# Flask routes (your existing endpoints, adapted to use optimized fetcher)
# -----------------------

def get_all_stats_deprecated():
    """Deprecated alias kept for backward compatibility if code calls it explicitly."""
    return get_all_stats()


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
        stats = fetch_detailed_leetcode_stats(username)

        return render_template(
            "student_profile.html",
            student=student,
            stats=stats,
            year_display=f"{student.year}{'st' if student.year == 1 else 'nd' if student.year == 2 else 'rd' if student.year == 3 else 'th'} Year"
        )
    except Exception as e:
        flash(f'Error fetching student stats: {str(e)}', 'error')
        return redirect(url_for('index'))


@app.route("/api/refresh-student/<register_number>", methods=['POST'])
def api_refresh_single_student(register_number):
    """
    Quickly refresh stats for a single student.
    Much faster than refreshing everyone!
    """
    student = Student.query.filter_by(register_number=register_number).first()
    
    if not student:
        return jsonify({'success': False, 'message': 'Student not found'}), 404
    
    username = student.leetcode_username
    
    if not username or username.lower() == "higher studies":
        return jsonify({'success': False, 'message': 'Invalid LeetCode username'}), 400
    
    try:
        # Clear this student's cache entry
        cache_key = f"stats:{username.strip().lower()}"
        try:
            cache.delete(cache_key)
        except Exception:
            pass
        
        # Fetch fresh stats from API
        stats = fetch_detailed_leetcode_stats(username)
        
        if stats:
            # Update database
            student_stats = StudentStats.query.filter_by(student_id=student.id).first()
            if not student_stats:
                student_stats = StudentStats(student_id=student.id)
                db.session.add(student_stats)
            
            student_stats.easy_solved = stats.get('easySolved', 0)
            student_stats.medium_solved = stats.get('mediumSolved', 0)
            student_stats.hard_solved = stats.get('hardSolved', 0)
            student_stats.total_solved = stats.get('totalSolved', 0)
            student_stats.last_updated = datetime.utcnow()
            student_stats.is_stale = False
            
            db.session.commit()
            
            log_info(f"Refreshed stats for {username}: {stats.get('totalSolved', 0)} total solved", tag="API")
            
            return jsonify({
                'success': True,
                'message': f"Stats updated! Total solved: {stats.get('totalSolved', 0)}",
                'stats': {
                    'easy': stats.get('easySolved', 0),
                    'medium': stats.get('mediumSolved', 0),
                    'hard': stats.get('hardSolved', 0),
                    'total': stats.get('totalSolved', 0)
                }
            })
        else:
            return jsonify({'success': False, 'message': 'Failed to fetch stats from LeetCode API'}), 500
            
    except Exception as e:
        db.session.rollback()
        log_error(f"Error refreshing stats for {username}: {e}", tag="API")
        return jsonify({'success': False, 'message': f'Error: {str(e)}'}), 500


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
        # pandas can read file-like objects
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

        log_debug(f"Detected columns: {list(df.columns)}", tag="Upload")

        column_mapping = {}

        for col in df.columns:
            col_str = str(col).lower().strip()

            if ('register' in col_str or 'roll' in col_str or 'reg' in col_str) and 'register_number' not in column_mapping:
                column_mapping['register_number'] = col

            elif 'name' in col_str and 'user' not in col_str and 'name' not in column_mapping:
                column_mapping['name'] = col

            elif ('leetcode' in col_str or 'profile' in col_str or 'username' in col_str or 'url' in col_str) and 'leetcode' not in column_mapping:
                column_mapping['leetcode'] = col

        log_debug(f"Column mapping: {column_mapping}", tag="Upload")

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

        # clear cache — optional: you might want to only clear affected users
        try:
            cache.clear()
        except Exception:
            pass

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
        log_exception(f"ERROR in upload_excel: {e}", tag="Upload")
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
            try:
                cache.clear()
            except Exception:
                pass

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
        try:
            cache.clear()
        except Exception:
            pass

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


@app.route("/admin/refresh-stats", methods=['POST'])
def admin_refresh_stats():
    """Force refresh all student stats from LeetCode API"""
    if not session.get('hod_authenticated'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    try:
        # Clear memory cache
        try:
            cache.clear()
            log_info("Memory cache cleared for admin refresh", tag="Cache")
        except Exception as e:
            log_error(f"Failed to clear cache: {e}", tag="Cache")
        
        # Fetch fresh stats from API (this will update the database)
        log_info("Starting admin-triggered stats refresh...", tag="Admin")
        start_time = time.time()
        
        all_results = get_all_stats()
        
        elapsed = time.time() - start_time
        log_info(f"Stats refresh completed in {elapsed:.2f}s, updated {len(all_results)} students", tag="Admin")
        
        return jsonify({
            'success': True,
            'message': f'Successfully refreshed stats for {len(all_results)} students in {elapsed:.1f} seconds',
            'students_updated': len(all_results)
        })
    except Exception as e:
        log_error(f"Admin refresh failed: {e}", tag="Admin")
        return jsonify({
            'success': False,
            'message': f'Error refreshing stats: {str(e)}'
        }), 500


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
    """
    Fast API endpoint that returns cached database stats immediately.
    On Vercel, we can't wait for live LeetCode API calls (10s timeout).
    Background refresh happens separately.
    
    Query params:
        - year: Filter by year/section (e.g., "2nd Year (A)")
        - force_refresh: If "1" or "true", clears cache and fetches fresh data from LeetCode API
    """
    selected_filter = request.args.get("year", None)
    force_refresh = request.args.get("force_refresh", "").lower() in ("1", "true")
    IS_VERCEL = os.environ.get('VERCEL') or os.environ.get('VERCEL_ENV')

    log_debug(f"API called with filter: '{selected_filter}', force_refresh: {force_refresh}, Vercel: {bool(IS_VERCEL)}", tag="API")

    # If force refresh requested, clear the memory cache first
    if force_refresh:
        try:
            cache.clear()
            log_info("Memory cache cleared for force refresh", tag="Cache")
        except Exception as e:
            log_error(f"Failed to clear cache: {e}", tag="Cache")

    if IS_VERCEL and not force_refresh:
        # FAST PATH for Vercel: Return DB cached data immediately
        results = get_stats_from_db(selected_filter)
    else:
        # Local or force_refresh: Use the full fetcher with live data
        all_results = get_all_stats()
        if selected_filter:
            results = [r for r in all_results if r["year_display"] == selected_filter]
        else:
            results = all_results
        # Refresh in background for next call (only if not already refreshed)
        if not force_refresh:
            refresh_all_stats_in_background()

    log_debug(f"Returning {len(results)} results", tag="API")
    return {"results": results, "available_years": get_available_year_sections()}


def get_stats_from_db(year_filter=None):
    """
    Fast database-only stats retrieval for Vercel deployment.
    Returns cached stats from StudentStats table without making any API calls.
    """
    from sqlalchemy import text
    
    query = db.session.query(Student, StudentStats).outerjoin(
        StudentStats, Student.id == StudentStats.student_id
    )
    
    if year_filter:
        # Parse year filter like "2nd Year (A)" or "3rd Year"
        parts = year_filter.split(" (")
        if len(parts) == 2:
            year_num = int(parts[0][0])  # "2nd Year (A)" -> 2
            section = parts[1].rstrip(")")  # "(A)" -> "A"
            query = query.filter(Student.year == year_num, Student.section == section)
        else:
            year_num = int(year_filter[0])  # "3rd Year" -> 3
            query = query.filter(Student.year == year_num)
    
    results = []
    for student, stats in query.all():
        year = student.year
        year_suffix = 'st' if year == 1 else 'nd' if year == 2 else 'rd' if year == 3 else 'th'
        year_str = f"{year}{year_suffix} Year"
        year_display = f"{year_str} ({student.section})" if student.section else year_str
        
        results.append({
            "roll_no": student.register_number,
            "actual_name": student.name,
            "username": student.leetcode_username,
            "year": year_str,
            "year_display": year_display,
            "year_number": year,
            "section": student.section,
            "easy": stats.easy_solved if stats else 0,
            "medium": stats.medium_solved if stats else 0,
            "hard": stats.hard_solved if stats else 0,
            "total": stats.total_solved if stats else 0,
            "fetch_error": None,
            "is_stale": stats.is_stale if stats else True,
            "fetched_at": int(stats.last_updated.timestamp()) if stats and stats.last_updated else 0
        })
    
    # Sort by total solved descending
    results.sort(key=lambda x: x["total"], reverse=True)
    return results


# -----------------------
# Weekly Reports Admin Routes
# -----------------------

@app.route("/admin/reports")
def admin_reports():
    """View weekly reports dashboard"""
    if not session.get('hod_authenticated'):
        return redirect(url_for('admin_login'))
    
    from app.reports import get_report_summary
    from app.email_service import get_email_status
    from app.scheduler import get_scheduler_status
    
    # Get all reports grouped by year, ordered by date
    reports = WeeklyReport.query.order_by(WeeklyReport.report_date.desc()).limit(50).all()
    report_summaries = [get_report_summary(r) for r in reports]
    
    return render_template(
        "admin_reports.html",
        reports=report_summaries,
        email_status=get_email_status(),
        scheduler_status=get_scheduler_status()
    )


@app.route("/admin/reports/<int:report_id>")
def admin_report_detail(report_id):
    """View a specific report's details"""
    if not session.get('hod_authenticated'):
        return redirect(url_for('admin_login'))
    
    import json
    from app.reports import get_report_email_html
    
    report = WeeklyReport.query.get_or_404(report_id)
    data = json.loads(report.data_json) if report.data_json else {}
    
    year_suffix = 'st' if report.year == 1 else 'nd' if report.year == 2 else 'rd' if report.year == 3 else 'th'
    year_str = f"{report.year}{year_suffix} Year"
    if report.section:
        year_str += f" ({report.section})"
    
    return render_template(
        "admin_report_detail.html",
        report=report,
        data=data,
        year_str=year_str,
        html_preview=get_report_email_html(report)
    )


@app.route("/admin/reports/generate", methods=['POST'])
def admin_generate_reports():
    """Manually generate weekly reports"""
    if not session.get('hod_authenticated'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    from app.reports import generate_all_weekly_reports, get_report_email_html
    from app.email_service import send_report_email, is_email_configured
    
    try:
        reports = generate_all_weekly_reports()
        
        email_results = []
        if is_email_configured():
            for report in reports:
                html_content = get_report_email_html(report)
                success, message = send_report_email(report, html_content)
                email_results.append({
                    'year': report.year,
                    'section': report.section,
                    'email_sent': success,
                    'message': message
                })
        
        return jsonify({
            'success': True,
            'message': f'Generated {len(reports)} reports',
            'reports_count': len(reports),
            'email_results': email_results
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route("/admin/reports/<int:report_id>/send-email", methods=['POST'])
def admin_send_report_email(report_id):
    """Manually send email for a specific report"""
    if not session.get('hod_authenticated'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    from app.reports import get_report_email_html
    from app.email_service import send_report_email
    
    report = WeeklyReport.query.get_or_404(report_id)
    html_content = get_report_email_html(report)
    success, message = send_report_email(report, html_content)
    
    return jsonify({
        'success': success,
        'message': message
    })


@app.route("/api/circuit-breaker-status")
def api_circuit_breaker_status():
    """Get current circuit breaker status for monitoring"""
    return jsonify(get_circuit_breaker_status())


# -----------------------
# External Cron API Endpoints (for Vercel serverless deployment)
# Use cron-job.org or similar to trigger these on schedule
# -----------------------

@app.route("/api/cron/weekly-reports", methods=['POST', 'GET'])
def api_cron_weekly_reports():
    """
    External cron endpoint to trigger weekly report generation.
    For Vercel serverless where APScheduler doesn't work.
    
    Security: Set CRON_SECRET env var and pass it as ?secret=xxx
    
    Usage with cron-job.org:
    - URL: https://your-app.vercel.app/api/cron/weekly-reports?secret=YOUR_SECRET
    - Method: GET or POST
    - Schedule: Every Monday at 8:00 AM
    
    Optional params:
    - send_email=true (default: false on Vercel to avoid timeout)
    """
    import os
    
    # Simple secret-based auth for cron jobs
    cron_secret = os.environ.get('CRON_SECRET', '')
    provided_secret = request.args.get('secret', '')
    
    # Skip auth if no secret is configured (development mode)
    if cron_secret and provided_secret != cron_secret:
        return jsonify({
            'success': False,
            'message': 'Unauthorized - invalid or missing secret'
        }), 401
    
    try:
        from app.reports import generate_all_weekly_reports, get_report_email_html
        from app.email_service import send_report_email, is_email_configured
        
        log_info("Starting weekly report generation via cron", tag="Cron")
        
        reports = generate_all_weekly_reports()
        log_info(f"Generated {len(reports)} reports", tag="Cron")
        
        # Send emails by default (use send_email=false to skip)
        send_emails = request.args.get('send_email', 'true').lower() != 'false'
        email_results = []
        
        if send_emails and is_email_configured():
            for report in reports:
                try:
                    html_content = get_report_email_html(report)
                    success, message = send_report_email(report, html_content)
                    email_results.append({
                        'year': report.year,
                        'section': report.section,
                        'email_sent': success,
                        'message': message
                    })
                except Exception as email_err:
                    log_error(f"Email error for year {report.year}: {email_err}", tag="Cron")
                    email_results.append({
                        'year': report.year,
                        'section': report.section,
                        'email_sent': False,
                        'message': str(email_err)
                    })
        
        return jsonify({
            'success': True,
            'message': f'Generated {len(reports)} reports',
            'reports_count': len(reports),
            'email_sent': send_emails,
            'email_results': email_results,
            'timestamp': datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        import traceback
        log_error(f"Error generating weekly reports: {traceback.format_exc()}", tag="Cron")
        return jsonify({
            'success': False, 
            'message': str(e)
        }), 500


@app.route("/api/cron/refresh-stats", methods=['POST', 'GET'])
def api_cron_refresh_stats():
    """
    External cron endpoint - optimized for Vercel cold starts.
    Uses paginated DB queries to avoid loading all students.
    """
    import os
    import time as time_module
    import asyncio
    
    start_total = time_module.time()
    
    cron_secret = os.environ.get('CRON_SECRET', '')
    provided_secret = request.args.get('secret', '')
    
    if cron_secret and provided_secret != cron_secret:
        return jsonify({"ok": False, "err": "auth"}), 401
    
    try:
        from app.leetcode_api import fetch_students_concurrent
        
        batch_size = min(int(request.args.get('batch_size', 5)), 10)
        
        # Count total students efficiently
        total = Student.query.count()
        
        if total == 0:
            return jsonify({"ok": True, "n": 0})
        
        # Calculate which batch to process
        batches = (total + batch_size - 1) // batch_size
        batch_num = (datetime.utcnow().minute // 2) % batches if batches > 0 else 0
        offset = batch_num * batch_size
        
        # Query ONLY the batch we need (not all students)
        batch_students = Student.query.order_by(Student.id).offset(offset).limit(batch_size).all()
        
        if not batch_students:
            batch_students = Student.query.order_by(Student.id).limit(batch_size).all()
        
        # Build minimal data for API fetch
        batch_data = []
        student_ids = []
        for s in batch_students:
            if s.leetcode_username:
                batch_data.append({
                    "username": s.leetcode_username,
                    "roll_no": s.register_number,
                    "name": s.name
                })
                student_ids.append(s.id)
        
        if not batch_data:
            return jsonify({"ok": True, "b": batch_num + 1, "of": batches, "n": 0, "t": 0})
        
        # Get only stats for THIS batch
        existing_stats = {st.student_id: st for st in 
                        StudentStats.query.filter(StudentStats.student_id.in_(student_ids)).all()}
        
        # Build cached stats map for the fetcher
        stats_map = {}
        for s in batch_students:
            if s.id in existing_stats:
                st = existing_stats[s.id]
                stats_map[s.leetcode_username.lower()] = {
                    "easy_solved": st.easy_solved,
                    "medium_solved": st.medium_solved,
                    "hard_solved": st.hard_solved,
                    "total_solved": st.total_solved
                }
        
        # Fetch from LeetCode API
        try:
            fetched = asyncio.run(fetch_students_concurrent(
                batch_data,
                cached_stats_map=stats_map,
                concurrency=3
            ))
        except Exception:
            fetched = []
        
        # Update database
        updated = 0
        for item in fetched:
            if item.get("is_stale") or item.get("fetch_error"):
                continue
            
            uname = (item.get("username") or "").strip().lower()
            # Find matching student
            for s in batch_students:
                if s.leetcode_username and s.leetcode_username.lower() == uname:
                    st = existing_stats.get(s.id)
                    if not st:
                        st = StudentStats(student_id=s.id)
                        db.session.add(st)
                    st.easy_solved = item.get("easy", 0)
                    st.medium_solved = item.get("medium", 0)
                    st.hard_solved = item.get("hard", 0)
                    st.total_solved = item.get("total", 0)
                    st.last_updated = datetime.utcnow()
                    st.is_stale = False
                    updated += 1
                    break
        
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
        
        elapsed = round(time_module.time() - start_total, 1)
        
        response = jsonify({"ok": True, "b": batch_num + 1, "of": batches, "n": updated, "t": elapsed})
        response.headers['Connection'] = 'close'
        return response
        
    except Exception as e:
        import traceback
        log_error(f"Cron error: {traceback.format_exc()}", tag="Cron")
        return jsonify({"ok": False, "err": str(e)[:100]}), 500
