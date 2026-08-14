import csv
import os
import io
import time
import random
import secrets
import threading
import asyncio
import aiohttp
from datetime import datetime
from flask import render_template, make_response, request, jsonify, redirect, url_for, flash, session
from werkzeug.utils import secure_filename
import pandas as pd

from app import app, cache, db, csrf, limiter
from app.models import Student, UploadLog, StudentStats, WeeklyReport
from app.logger import log_info, log_warning, log_error, log_debug, log_exception
from app.leetcode_api import (
    fetch_students_concurrent,
    fetch_student_detailed_stats,
    get_circuit_breaker_status,
    CACHE_TTL,
    CONCURRENCY,
    TIMEOUT_SECONDS
)

REFRESH_COOLDOWN_SECONDS = 30  # per-student cooldown for the public "refresh my stats" endpoint

# Roster slice size for the admin sync console. Small enough that each request
# finishes well inside a serverless execution limit, large enough that a few
# hundred students don't take hundreds of round trips.
SYNC_BATCH_SIZE = 8
SYNC_BATCH_MAX = 25


def _year_display(year, section):
    """'3rd Year (A)' / '4th Year' - the label used across the UI."""
    suffix = 'st' if year == 1 else 'nd' if year == 2 else 'rd' if year == 3 else 'th'
    label = f"{year}{suffix} Year"
    return f"{label} ({section})" if section else label


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


# -----------------------
# Single-flight locking (request coalescing)
# -----------------------
# When a cache entry is missing, several concurrent requests would otherwise
# each independently trigger their own live LeetCode API call for the exact
# same data ("cache stampede") - multiplying outbound traffic by however many
# requests land in that window. These per-key locks make every request but
# one for a given key block briefly and then read the cache the first one
# just filled, instead of all of them hitting the network.
#
# Caveat: this only coordinates requests handled by the *same* process. Under
# multiple gunicorn workers (Render) or separate serverless invocations
# (Vercel), each process has its own lock registry, so the effective
# duplication factor is bounded by worker/instance count, not eliminated
# entirely. A fully cross-process guarantee would need a shared store
# (Redis/DB-based lock) - not worth the added infra for this app's scale, but
# worth knowing if traffic ever grows enough to matter.
_fetch_locks = {}
_fetch_locks_guard = threading.Lock()


def _lock_for(key):
    with _fetch_locks_guard:
        lock = _fetch_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _fetch_locks[key] = lock
        return lock


def detail_cache_key(username):
    """Cache key for a student's detailed profile stats. Kept in a separate
    namespace from the leaderboard's `stats:` cache since the two endpoints
    return differently-shaped payloads (leaderboard: easy/medium/hard/total,
    detail: easySolved/mediumSolved/.../ranking/recentSubmissions/...)."""
    return f"detail:{(username or '').strip().lower()}"


def jittered_ttl(base_seconds, spread=0.2):
    """
    Add +/-`spread` random jitter to a cache TTL. Without this, a bulk
    operation (roster upload, admin refresh, cold start) caches many entries
    within the same second, all with the same fixed TTL - they'd then all
    expire in the same instant, causing a synchronized burst of cache misses
    (and therefore live API calls) instead of the load spreading out.
    """
    return int(base_seconds * random.uniform(1 - spread, 1 + spread))


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


def load_students_with_cached_stats():
    """
    Load all students together with their last-known DB stats in a single
    outer-joined query, instead of three separate full-table scans
    (Student.query.all() x2 + StudentStats.query.all()). Each extra round
    trip costs real latency against a remote Postgres instance.
    """
    students = []
    student_id_map = {}  # username.lower() -> student_id
    db_stats_map = {}    # username.lower() -> {easy_solved, medium_solved, hard_solved, total_solved}

    rows = db.session.query(Student, StudentStats).outerjoin(
        StudentStats, Student.id == StudentStats.student_id
    ).all()

    for student, stats in rows:
        students.append((student.leetcode_username, student.name, student.register_number, student.year, student.section))

        if student.leetcode_username:
            uname = student.leetcode_username.strip().lower()
            student_id_map[uname] = student.id

            if stats:
                db_stats_map[uname] = {
                    "easy_solved": stats.easy_solved,
                    "medium_solved": stats.medium_solved,
                    "hard_solved": stats.hard_solved,
                    "total_solved": stats.total_solved
                }

    return students, student_id_map, db_stats_map


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
    students, student_id_map, db_stats_map = load_students_with_cached_stats()
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

    # fetch missing ones concurrently using robust API module
    if to_fetch:
        # Single-flight: if another request is already fetching this batch of
        # cache misses (e.g. several people load the dashboard/CSV export at
        # once right after cache expiry), block briefly instead of also
        # hitting the network, then re-check cache for what the first caller
        # already filled.
        with _lock_for("get_all_stats:full-roster"):
            still_to_fetch = []
            for username, name, roll, year, section in to_fetch:
                key = f"stats:{(username or '').strip().lower()}"
                try:
                    cached = cache.get(key)
                except Exception:
                    cached = None
                if cached and isinstance(cached, dict):
                    cached_results.append(cached)
                else:
                    still_to_fetch.append((username, name, roll, year, section))
            to_fetch = still_to_fetch

            fetched = []
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

                        # Save to memory cache (small TTL jitter so many
                        # entries cached around the same moment don't all
                        # expire in the same instant and cause another
                        # simultaneous burst of misses later on)
                        cache_key = f"stats:{uname}"
                        cache.set(cache_key, item, timeout=jittered_ttl(cache_ttl))

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
# NOTE: fetch_student_detailed_stats is imported from leetcode_api.py, which
# runs it through the same 4-source fallback + circuit breaker chain used by
# the leaderboard fetch (plus best-effort ranking/reputation/submissions
# from the alfa mirrors specifically, since only they expose those fields).
async def _fetch_detailed_with_new_session(username, timeout_seconds=TIMEOUT_SECONDS):
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        return await fetch_student_detailed_stats(username, session, timeout_seconds)


def _default_detailed_stats(username):
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
        "acceptance_rate": 0,
        "profile_url": f"https://leetcode.com/u/{username}/"
    }


def fetch_detailed_leetcode_stats(username):
    """Synchronous wrapper used by Flask to fetch detailed stats for a single student."""
    if not username or username.lower() == "higher studies":
        return _default_detailed_stats(username)
    try:
        result = asyncio.run(_fetch_detailed_with_new_session(username))
        return result or _default_detailed_stats(username)
    except Exception as e:
        log_error(f"fetch_detailed_leetcode_stats error: {e}", tag="API")
        return _default_detailed_stats(username)


# -----------------------
# Flask routes (your existing endpoints, adapted to use optimized fetcher)
# -----------------------

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
        cache_key = detail_cache_key(username)
        try:
            stats = cache.get(cache_key)
        except Exception:
            stats = None

        if not stats:
            # Single-flight: only one concurrent request per username actually
            # calls the live API; the rest wait briefly and reuse its result.
            with _lock_for(cache_key):
                try:
                    stats = cache.get(cache_key)
                except Exception:
                    stats = None
                if not stats:
                    stats = fetch_detailed_leetcode_stats(username)
                    if stats:
                        try:
                            cache.set(cache_key, stats, timeout=jittered_ttl(CACHE_TTL))
                        except Exception:
                            pass

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
@csrf.exempt
@limiter.limit("10 per minute")
def api_refresh_single_student(register_number):
    """
    Quickly refresh stats for a single student.
    Much faster than refreshing everyone!

    This is a public, unauthenticated endpoint (anyone with the profile URL
    can click "Refresh My Stats"), so on top of the per-IP rate limit above,
    it enforces a short per-student cooldown - shared across all callers -
    so it can't be used to hammer a single student's data via many IPs/tabs.
    """
    student = Student.query.filter_by(register_number=register_number).first()

    if not student:
        return jsonify({'success': False, 'message': 'Student not found'}), 404

    username = student.leetcode_username

    if not username or username.lower() == "higher studies":
        return jsonify({'success': False, 'message': 'Invalid LeetCode username'}), 400

    cooldown_key = f"refresh-cooldown:{register_number}"
    if cache.get(cooldown_key):
        return jsonify({
            'success': False,
            'message': 'This student was just refreshed - please wait a bit before trying again.'
        }), 429
    cache.set(cooldown_key, True, timeout=REFRESH_COOLDOWN_SECONDS)

    try:
        # Clear this student's leaderboard cache entry (different shape/namespace
        # from the detail cache - see detail_cache_key()) so the leaderboard
        # re-fetches instead of showing stale data.
        try:
            cache.delete(f"stats:{username.strip().lower()}")
        except Exception:
            pass

        # Fetch fresh stats from API
        stats = fetch_detailed_leetcode_stats(username)

        # Write straight through to the detail cache so the profile page
        # reflects this refresh immediately instead of re-fetching.
        if stats:
            try:
                cache.set(detail_cache_key(username), stats, timeout=jittered_ttl(CACHE_TTL))
            except Exception:
                pass

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


@app.route("/api/student-stats/<register_number>")
def api_student_stats(register_number):
    """
    Lightweight DB-only stats read for a single student - no live LeetCode API
    call, just a StudentStats row lookup. Used by the profile page's
    auto-refresh polling so an open tab picks up whatever the periodic
    cron/scheduler refresh has written to the DB, without hammering the
    live API on every poll tick.
    """
    student = Student.query.filter_by(register_number=register_number).first()
    if not student:
        return jsonify({'success': False, 'message': 'Student not found'}), 404

    stats = StudentStats.query.filter_by(student_id=student.id).first()

    return jsonify({
        'success': True,
        'stats': {
            'easy': stats.easy_solved if stats else 0,
            'medium': stats.medium_solved if stats else 0,
            'hard': stats.hard_solved if stats else 0,
            'total': stats.total_solved if stats else 0,
        },
        'last_updated': stats.last_updated.isoformat() if stats and stats.last_updated else None,
    })


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
@limiter.limit("5 per minute", methods=['POST'])
def admin_login():
    """HoD login page"""
    if request.method == 'POST':
        password = request.form.get('password') or ''
        if secrets.compare_digest(password, app.config['HOD_PASSWORD']):
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


@app.route("/admin/sync-batch", methods=['POST'])
def admin_sync_batch():
    """
    Sync one slice of the roster and report per-student results.

    The client walks the roster by calling this repeatedly with an advancing
    offset, which buys three things over the single blocking
    /admin/refresh-stats call:

    1. Each request stays short, so a full-roster sync no longer has to fit
       inside a serverless function's execution limit (the reason the Vercel
       deployment needs the batched cron endpoint at all).
    2. Batches run one after another instead of opening the whole roster's
       worth of connections at once, so it's gentler on the upstream mirrors
       than the all-at-once path.
    3. The caller gets real per-student results while the work happens,
       rather than a single number once it's over.

    Admin session required - this triggers live third-party API traffic.
    """
    if not session.get('hod_authenticated'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403

    payload = request.get_json(silent=True) or {}

    try:
        offset = max(int(payload.get('offset', 0)), 0)
    except (TypeError, ValueError):
        offset = 0

    try:
        limit = int(payload.get('limit', SYNC_BATCH_SIZE))
    except (TypeError, ValueError):
        limit = SYNC_BATCH_SIZE
    limit = max(1, min(limit, SYNC_BATCH_MAX))

    total = Student.query.count()
    batch = Student.query.order_by(Student.id).offset(offset).limit(limit).all()

    if not batch:
        return jsonify({
            'success': True, 'total': total, 'offset': offset,
            'next_offset': None, 'results': []
        })

    student_ids = [s.id for s in batch]
    existing = {
        st.student_id: st
        for st in StudentStats.query.filter(StudentStats.student_id.in_(student_ids)).all()
    }

    # Previous totals, captured before the write so we can report deltas.
    previous = {s.id: (existing[s.id].total_solved if s.id in existing else None) for s in batch}

    to_fetch = []
    cached_map = {}
    for s in batch:
        if not s.leetcode_username:
            continue
        to_fetch.append((s.leetcode_username, s.name, s.register_number, s.year, s.section, s.id))
        st = existing.get(s.id)
        if st:
            cached_map[s.leetcode_username.strip().lower()] = {
                "easy_solved": st.easy_solved,
                "medium_solved": st.medium_solved,
                "hard_solved": st.hard_solved,
                "total_solved": st.total_solved,
            }

    fetched = []
    if to_fetch:
        try:
            fetched = asyncio.run(fetch_students_concurrent(to_fetch, cached_stats_map=cached_map))
        except Exception as e:
            log_error(f"Sync batch fetch failed at offset {offset}: {e}", tag="Admin")
            fetched = []

    by_username = {(f.get("username") or "").strip().lower(): f for f in fetched}
    results = []

    for s in batch:
        uname = (s.leetcode_username or "").strip().lower()
        item = by_username.get(uname)
        prev = previous.get(s.id)

        if item is None:
            results.append({
                'name': s.name, 'username': s.leetcode_username,
                'year_display': _year_display(s.year, s.section),
                'total': prev or 0, 'delta': None, 'status': 'unreachable'
            })
            continue

        if item.get('fetch_error'):
            results.append({
                'name': s.name, 'username': s.leetcode_username,
                'year_display': _year_display(s.year, s.section),
                'total': prev or 0, 'delta': None, 'status': 'unreachable'
            })
            continue

        new_total = item.get('total', 0)

        if item.get('is_stale'):
            # All sources failed; the fetcher fell back to the stored value,
            # so there is nothing new to write and no delta to claim.
            results.append({
                'name': s.name, 'username': s.leetcode_username,
                'year_display': _year_display(s.year, s.section),
                'total': new_total, 'delta': None, 'status': 'cached'
            })
            continue

        st = existing.get(s.id)
        if not st:
            st = StudentStats(student_id=s.id)
            db.session.add(st)
        st.easy_solved = item.get('easy', 0)
        st.medium_solved = item.get('medium', 0)
        st.hard_solved = item.get('hard', 0)
        st.total_solved = new_total
        st.last_updated = datetime.utcnow()
        st.is_stale = False

        try:
            cache.delete(f"stats:{uname}")
        except Exception:
            pass

        delta = None if prev is None else new_total - prev
        results.append({
            'name': s.name, 'username': s.leetcode_username,
            'year_display': _year_display(s.year, s.section),
            'total': new_total, 'delta': delta,
            'status': 'gained' if (delta or 0) > 0 else 'synced'
        })

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        log_error(f"Sync batch commit failed at offset {offset}: {e}", tag="Admin")
        return jsonify({'success': False, 'message': 'Could not save this batch'}), 500

    next_offset = offset + len(batch)
    return jsonify({
        'success': True,
        'total': total,
        'offset': offset,
        'next_offset': next_offset if next_offset < total else None,
        'results': results
    })


@app.route("/download")
def download_csv():
    """
    CSV export. Reads from the DB only - same as /api/stats's fast path -
    rather than calling get_all_stats(), which can trigger live LeetCode API
    calls. This is a public, unauthenticated GET endpoint; it must never be
    able to trigger third-party API traffic on demand. Freshness comes from
    the existing background refresh (cron/scheduler), same as the dashboard.
    """
    selected_filter = request.args.get("year", None)

    results = get_stats_from_db(selected_filter)
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
        - force_refresh: If "1" or "true", clears cache and fetches fresh data from LeetCode API.
          Requires an authenticated HoD session - this endpoint is public, and a live full-roster
          fetch against third-party LeetCode API mirrors is not something an anonymous caller
          should be able to trigger on demand (they could just keep calling it).
    """
    selected_filter = request.args.get("year", None)
    force_refresh = request.args.get("force_refresh", "").lower() in ("1", "true")
    if force_refresh and not session.get('hod_authenticated'):
        log_warning("Ignoring unauthenticated force_refresh request on /api/stats", tag="API")
        force_refresh = False
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
@csrf.exempt
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
@csrf.exempt
def api_cron_refresh_stats():
    """
    External cron endpoint - optimized for Vercel cold starts.
    Uses paginated DB queries to avoid loading all students.
    """
    start_total = time.time()

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
        
        # Build minimal data for API fetch - must be tuples!
        # Format: (username, name, roll, year, section, student_id)
        batch_data = []
        student_ids = []
        for s in batch_students:
            if s.leetcode_username:
                year_suffix = 'st' if s.year == 1 else 'nd' if s.year == 2 else 'rd' if s.year == 3 else 'th'
                year_str = f"{s.year}{year_suffix} Year"
                batch_data.append((
                    s.leetcode_username,
                    s.name,
                    s.register_number,
                    year_str,
                    s.section,
                    s.id
                ))
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
        
        elapsed = round(time.time() - start_total, 1)
        
        response = jsonify({"ok": True, "b": batch_num + 1, "of": batches, "n": updated, "t": elapsed})
        response.headers['Connection'] = 'close'
        return response
        
    except Exception as e:
        import traceback
        log_error(f"Cron error: {traceback.format_exc()}", tag="Cron")
        return jsonify({"ok": False, "err": str(e)[:100]}), 500
