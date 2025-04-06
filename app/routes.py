import csv
import os
import io
import asyncio
import aiohttp
from datetime import datetime

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

async def fetch_leetcode_stats_async(username):
    """
    Asynchronously fetch LeetCode statistics.
    """
    if username == "higher studies":
        return {"easy": 0, "medium": 0, "hard": 0, "total": 0}
    
    url = f"https://leetcode-api-faisalshohag.vercel.app/{username}"
    full_url = f"{url}?t={datetime.now().timestamp()}"
    print(f"Fetching stats for {username} from {full_url}")
    
    # Create a timeout for the requests
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
                    # If not successful, wait before retry
                    await asyncio.sleep(0.5 * (attempt + 1))
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                print(f"Attempt {attempt+1} failed for {username}: {e}")
                if attempt < 2:  # Not the last attempt
                    await asyncio.sleep(0.5 * (attempt + 1))
    
    # If all attempts fail, return zeros
    return {"easy": 0, "medium": 0, "hard": 0, "total": 0}

@cache.memoize(timeout=300)
def fetch_leetcode_stats(username):
    """
    Cached wrapper for the async fetch function.
    """
    return asyncio.run(fetch_leetcode_stats_async(username))

async def fetch_all_stats_async():
    """
    Fetch stats for all students concurrently using a shared session.
    """
    # Create a connector with increased connection limit
    connector = aiohttp.TCPConnector(limit=50)
    timeout = aiohttp.ClientTimeout(total=10)
    
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        tasks = []
        for username, name, roll_no, year in students:
            task = fetch_student_stats_async(username, name, roll_no, year, session)
            tasks.append(task)
        
        # Run all tasks concurrently and wait for them to complete
        return await asyncio.gather(*tasks)

async def fetch_student_stats_async(username, name, roll_no, year, session):
    """
    Fetch a student's stats using an existing session.
    """
    if username == "higher studies":
        stats = {"easy": 0, "medium": 0, "hard": 0, "total": 0}
    else:
        url = f"https://leetcode-api-faisalshohag.vercel.app/{username}"
        full_url = f"{url}?t={datetime.now().timestamp()}"
        
        try:
            for attempt in range(3):
                try:
                    async with session.get(full_url) as response:
                        if response.status == 200:
                            data = await response.json()
                            stats = {
                                "easy": data.get("easySolved", 0),
                                "medium": data.get("mediumSolved", 0),
                                "hard": data.get("hardSolved", 0),
                                "total": data.get("totalSolved", 0)
                            }
                            break
                        await asyncio.sleep(0.5 * (attempt + 1))
                except Exception as e:
                    print(f"Attempt {attempt+1} failed for {username}: {e}")
                    if attempt < 2:
                        await asyncio.sleep(0.5 * (attempt + 1))
            else:  # If all attempts fail
                stats = {"easy": 0, "medium": 0, "hard": 0, "total": 0}
        except Exception as e:
            print(f"Error fetching {username}: {e}")
            stats = {"easy": 0, "medium": 0, "hard": 0, "total": 0}
    
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

def get_all_stats():
    """
    Synchronous wrapper to get all stats using asyncio.
    """
    return asyncio.run(fetch_all_stats_async())

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/download")
def download_csv():
    selected_year = request.args.get("year", None)
    
    # Get all stats in one asynchronous operation instead of multiple calls
    all_results = get_all_stats()
    
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
    
    # Get all stats in one asynchronous operation
    all_results = get_all_stats()
    
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

