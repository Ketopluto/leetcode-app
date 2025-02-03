import csv
import os
import io
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from flask import render_template, make_response, request
from app import app, cache

def load_students_data():
    students = []
    current_year = None
    # Assuming students.txt is in the project root.
    file_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "students.txt")
    with open(file_path, "r") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            if line.endswith("Students:"):
                current_year = line.replace("Students:", "").strip()
            else:
                parts = line.split(",")
                if len(parts) == 3 and current_year:
                    username, name, roll_no = [p.strip() for p in parts]
                    students.append((username, name, roll_no, current_year))
    return students

students = load_students_data()

def create_session():
    session = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504]
    )
    adapter = HTTPAdapter(max_retries=retries, pool_connections=20, pool_maxsize=20)
    session.mount('https://', adapter)
    return session

#@cache.memoize(timeout=600)
def fetch_leetcode_stats(username):
    """
    Fetch LeetCode statistics using the designated API endpoint.
    This endpoint is: https://leetcode-api-faisalshohag.vercel.app/<username>
    """
    if username == "higher studies":
        return {"easy": 0, "medium": 0, "hard": 0, "total": 0}
    
    session = create_session()
    url = f"https://leetcode-api-faisalshohag.vercel.app/{username}"
    try:
        full_url = f"{url}?t={datetime.now().timestamp()}"
        print(f"Fetching stats for {username} from {full_url}")
        res = session.get(full_url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            return {
                "easy": data.get("easySolved", 0),
                "medium": data.get("mediumSolved", 0),
                "hard": data.get("hardSolved", 0),
                "total": data.get("totalSolved", 0)
            }
    except Exception as e:
        print(f"Error fetching {username}: {e}")
    return {"easy": 0, "medium": 0, "hard": 0, "total": 0}

def process_student(student):
    """Fetch a student's stats using the new API (no DB integration)."""
    username, name, roll_no, year = student
    stats = fetch_leetcode_stats(username)
    return {
        "roll_no": roll_no,
        "actual_name": name,
        "username": username,
        "year": year,
        "easy": stats["easy"],
        "medium": stats["medium"],
        "hard": stats["hard"],
        "total": stats["total"]
    }

@app.route("/")
def index():
    # This endpoint now renders the main page; content is loaded asynchronously.
    return render_template("index.html")

@app.route("/download")
def download_csv():
    selected_year = request.args.get("year", None)
    all_results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(process_student, student) for student in students]
        for future in futures:
            all_results.append(future.result())
    if selected_year:
        results = [r for r in all_results if r["year"] == selected_year]
    else:
        results = all_results

    results.sort(key=lambda x: x["roll_no"])
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Roll Number", "Name", "LeetCode Username", "Year", "Easy Solved", "Medium Solved", "Hard Solved", "Total Solved"])
    for row in results:
        writer.writerow([row["roll_no"], row["actual_name"], row["username"], row["year"],
                         row["easy"], row["medium"], row["hard"], row["total"]])
    response = make_response(output.getvalue())
    filename = f"leetcode_stats_{selected_year if selected_year else 'all'}.csv"
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    response.headers["Content-type"] = "text/csv"
    return response

@app.route("/api/stats")
def api_stats():
    selected_year = request.args.get("year", None)
    all_results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(process_student, student) for student in students]
        for future in futures:
            all_results.append(future.result())
    if selected_year:
        results = [r for r in all_results if r["year"] == selected_year]
    else:
        results = all_results
    results.sort(key=lambda x: x["roll_no"])
    return {"results": results}

@app.route("/refresh/<username>")
def refresh_user(username):
    cache.delete_memoized(fetch_leetcode_stats, username)
    return f"Cache cleared for {username}. Next request will fetch fresh data."