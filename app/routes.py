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
from app.models import Student, UploadLog

# -----------------------
# Configurable tunables
# -----------------------
CACHE_TTL = 120            # seconds each student's stats are cached
CONCURRENCY = 50           # number of concurrent requests to LeetCode API (tune if you see errors)
TIMEOUT_SECONDS = 5        # aiohttp total timeout for each request
FETCH_ATTEMPTS = 2         # retry attempts per username
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

    print(f"Available year-section options: {options}")
    return options


def load_students_from_db():
    """Load all students from database"""
    students = Student.query.all()
    return [(s.leetcode_username, s.name, s.register_number, s.year, s.section)
            for s in students]


# -----------------------
# Optimized concurrent fetcher
# -----------------------

async def _fetch_student_with_session(username, name, roll_no, year, section, session, attempts=FETCH_ATTEMPTS):
    """Internal: fetch one student's stats using provided aiohttp session."""
    uname = (username or "").strip()
    if not uname or uname.lower() == "higher studies":
        stats = {"easy": 0, "medium": 0, "hard": 0, "total": 0}
    else:
        url = f"https://alfa-leetcode-api-blush.vercel.app/{uname}/solved"
        stats = {"easy": 0, "medium": 0, "hard": 0, "total": 0}
        for attempt in range(attempts):
            try:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        stats = {
                            "easy": data.get("easySolved", 0),
                            "medium": data.get("mediumSolved", 0),
                            "hard": data.get("hardSolved", 0),
                            "total": data.get("solvedProblem", 0),
                        }
                        break
                    else:
                        # non-200: break or retry depending on status
                        # for now, retry on server errors, otherwise give up
                        if 500 <= resp.status < 600:
                            # server error: let it retry
                            pass
                        else:
                            break
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if attempt + 1 < attempts:
                    await asyncio.sleep(0.15 * (attempt + 1))
                else:
                    # final attempt failed -> keep zeros
                    pass

    year_suffix = 'st' if year == 1 else 'nd' if year == 2 else 'rd' if year == 3 else 'th'
    year_str = f"{year}{year_suffix} Year"
    year_display = f"{year_str} ({section})" if section else year_str

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
        "total": stats["total"],
        "fetched_at": int(time.time())
    }


async def fetch_students_concurrent(students_to_fetch, concurrency=CONCURRENCY, timeout_seconds=TIMEOUT_SECONDS):
    """
    Fetch a list of students ([(username,name,roll,year,section), ...]) concurrently
    using a semaphore and a single aiohttp session.
    """
    if not students_to_fetch:
        return []

    # limit_per_host + limit tuned to overall concurrency
    connector = aiohttp.TCPConnector(limit_per_host=concurrency, limit=concurrency)
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    sem = asyncio.Semaphore(concurrency)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        async def guarded_fetch(item):
            async with sem:
                username, name, roll, year, section = item
                try:
                    return await _fetch_student_with_session(username, name, roll, year, section, session)
                except Exception as e:
                    # return a default dict on error
                    return {
                        "roll_no": roll,
                        "actual_name": name,
                        "username": username,
                        "year": f"{year}",
                        "year_display": f"{year}",
                        "year_number": year,
                        "section": section,
                        "easy": 0,
                        "medium": 0,
                        "hard": 0,
                        "total": 0,
                        "fetched_at": int(time.time())
                    }

        tasks = [asyncio.create_task(guarded_fetch(s)) for s in students_to_fetch]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        return results


def get_all_stats(cache_ttl=CACHE_TTL, concurrency=CONCURRENCY, timeout_seconds=TIMEOUT_SECONDS):
    """
    Synchronous wrapper used by Flask routes. It:
    1) loads students from DB,
    2) returns cached stats for students that have them,
    3) concurrently fetches only the missing ones,
    4) stores fetched results in cache and returns combined list.
    """
    students = load_students_from_db()  # returns tuples (username, name, roll, year, section)
    cached_results = []
    to_fetch = []

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

    # fetch missing ones concurrently
    if to_fetch:
        try:
            fetched = asyncio.run(fetch_students_concurrent(to_fetch, concurrency=concurrency, timeout_seconds=timeout_seconds))
        except Exception as e:
            # on a catastrophic failure, fallback to returning cached results only
            print("Error during concurrent fetch:", e)
            fetched = []

        # save to cache
        for item in fetched:
            try:
                uname = (item.get("username") or "").strip().lower()
                cache_key = f"stats:{uname}"
                # cache.set(key, value, timeout) — Flask-Caching signature
                cache.set(cache_key, item, timeout=cache_ttl)
            except Exception:
                pass

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
            _ = get_all_stats(cache_ttl=cache_ttl, concurrency=concurrency, timeout_seconds=timeout_seconds)
        except Exception as e:
            print("Background refresh failed:", e)
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
        print(f"Error fetching detailed stats for {username}: {e}")
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
        print("fetch_detailed_leetcode_stats error:", e)
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

    # Use fast cached/concurrent fetcher
    all_results = get_all_stats()

    if selected_filter:
        results = [r for r in all_results if r["year_display"] == selected_filter]
        print(f"Filtered results: {len(results)} out of {len(all_results)}")
    else:
        results = all_results

    # Optionally refresh in background so next call is extremely fast
    refresh_all_stats_in_background()

    return {"results": results, "available_years": get_available_year_sections()}
