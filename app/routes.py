import csv
import io
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from flask import render_template, make_response
from app import app, db, cache
from app.models import StudentStats

# Student data structure (username, name, roll_no)
students = [
    ("SRIbNNFCEY", "Aallan Hrithick A S", "310622148001"),
    ("higher studies", "Achyuthnarayanan M", "310622148002"),
    ("higher studies", "Alban J", "310622148003"),
    ("Archana0521", "Archana V C Nair", "310622148004"),
    ("ARYA_SUDHEER", "Arya S", "310622148005"),
    ("asvika_28", "Asvika M A", "310622148006"),
    ("bala_shivani", "Bala Shivani P D", "310622148007"),
    ("bharwtg300922", "Bharath K", "310622148008"),
    ("Deepthavc", "Deeptha V", "310622148009"),
    ("Divyaa_05_", "Divyaa B", "310622148010"),
    ("DurgaL011", "Durga L", "310622148011"),
    ("fahmitha4", "Fahmitha Farhana S", "310622148012"),
    ("Harini_3538", "Harini V", "310622148013"),
    ("Harsha21062004", "Harsha Varthini S", "310622148014"),
    ("kZn84IKEv5", "Harshita V", "310622148015"),
    ("Jaya_Arshin", "Jaya Arshin A", "310622148016"),
    ("jeniliagracelyn", "Jenilia Gracelyn S", "310622148017"),
    ("Jhaishnavi_S", "Jhaishnavi S", "310622148018"),
    ("higher studies", "Kaaviya B", "310622148019"),
    ("higher studies", "Kavitha A", "310622148020"),
    ("RVkaviya", "Kaviya R V", "310622148021"),
    ("keertij", "Keerti J", "310622148022"),
    ("higher studies", "Manikanda Ganapathi T", "310622148023"),
    ("Manvik_ram", "Manoj Ram K", "310622148024"),
    ("ManuSavithri", "Manu Savithri V", "310622148025"),
    ("MP0ZkaD5OP", "Megala P", "310622148026"),
    ("higher studies", "Mohammed Mohseen A", "310622148027"),
    ("Mohnish_KJ", "Mohnish K J", "310622148028"),
    ("higher studies", "Narendran G T", "310622148029"),
    ("Nav3005", "Naveen Karthik R", "310622148030"),
    ("poovarasan_03", "Poovarasan G", "310622148031"),
    ("rakheshkrishnap", "Rakhesh Krishna P", "310622148032"),
    ("RanjanaG", "Ranjana G", "310622148033"),
    ("SEPYbnmEIv", "Rithanya V R", "310622148034"),
    ("Rohit_Chandramohan", "Rohit C", "310622148035"),
    ("Zaw5lz57ys", "Ruchikaa K", "310622148036"),
    ("Sam_jefferson_2005", "Sam Jefferson M P", "310622148037"),
    ("Saranya_874", "Saranya K", "310622148038"),
    ("Sheshanathan", "Sheshanathan S", "310622148039"),
    ("Snehapm", "Sneha P M", "310622148040"),
    ("iAJ3eWxBRW", "Sri Rajarajeswaran B", "310622148041"),
    ("sudiptasundar27", "Sudipta Sundar", "310622148042"),
    ("sujeth_21", "Sujeth S", "310622148043"),
    ("Sundar_2104", "Sundaram R K", "310622148044"),
    ("suprajavenkatesan", "Supraja Venkatesan", "310622148045"),
    ("Tanush_83", "Tanush T M", "310622148046"),
    ("TejaswiniDhakshnamurthy", "Tejaswini D", "310622148047"),
    ("Varun_Kumar_04", "Varun Kumar G S", "310622148048"),
    ("Vignesh49", "Vignesh M", "310622148049"),
    ("Vinodhini-K", "Vinodhini K", "310622148050"),
    ("Vishnu_MP2004", "Vishnu Manheri Puthiyaveetil", "310622148051"),
    ("vishveswarR", "Vishveswar R", "310622148053"),
    ("avs242004", "Visvesh Sanathan A", "310622148054"),
    ("Viswa_312004", "Viswa K", "310622148055"),
    ("yukitha04", "Yukitha K", "310622148056"),
    ("ksamanasesh", "Manasesh S", "310622148301"),
    ("ashif13", "Mohamed Ashif A", "310622148302"),
    ("71jBRQtgg5", "Pranavaa P", "310622148303"),
    ("higher studies", "Saieed Marichamy", "310622148304"),
    ("sakthivel17", "Sakthivel A", "310622148305"),
    ("velmuruganr21", "Velmurugan R", "310622148306")
]

# Create a session with retry logic for API calls
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

def fetch_leetcode_stats(username):
    if username == "higher studies":
        return {"easy": 0, "medium": 0, "hard": 0, "total": 0}
    session = create_session()
    try:
        res = session.get(f"https://leetcode-stats-api.herokuapp.com/{username}", timeout=3)
        if res.status_code == 200:
            data = res.json()
            if data.get("status") == "success":
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
    username, name, roll_no = student
    # Each threaded call needs its own application context.
    with app.app_context():
        stat_record = StudentStats.query.filter_by(username=username, roll_no=roll_no).first()
        if stat_record:
            new_stats = fetch_leetcode_stats(username)
            if new_stats["total"] > stat_record.total:
                stat_record.easy = new_stats["easy"]
                stat_record.medium = new_stats["medium"]
                stat_record.hard = new_stats["hard"]
                stat_record.total = new_stats["total"]
                stat_record.last_updated = datetime.utcnow()
                db.session.commit()
            result = {
                "roll_no": roll_no,
                "actual_name": name,
                "username": username,
                "easy": stat_record.easy,
                "medium": stat_record.medium,
                "hard": stat_record.hard,
                "total": stat_record.total
            }
        else:
            new_stats = fetch_leetcode_stats(username)
            new_record = StudentStats(
                username=username,
                actual_name=name,
                roll_no=roll_no,
                easy=new_stats["easy"],
                medium=new_stats["medium"],
                hard=new_stats["hard"],
                total=new_stats["total"],
                last_updated=datetime.utcnow()
            )
            db.session.add(new_record)
            db.session.commit()
            result = {
                "roll_no": roll_no,
                "actual_name": name,
                "username": username,
                "easy": new_stats["easy"],
                "medium": new_stats["medium"],
                "hard": new_stats["hard"],
                "total": new_stats["total"]
            }
    return result

@app.route("/")
@cache.cached(timeout=60)
def index():
    results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(process_student, student) for student in students]
        for future in futures:
            results.append(future.result())
    results.sort(key=lambda x: x["roll_no"])
    # Query the database for the top 5 problem solvers.
    top_solvers = StudentStats.query.order_by(StudentStats.total.desc()).limit(7).all()
    top_7_data = [{'username': solver.username, 'actual_name': solver.actual_name, 'total': solver.total} for solver in top_solvers]
    return render_template("index.html", results=results, top_7_data=top_7_data)

@app.route("/download")
def download_csv():
    results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(process_student, student) for student in students]
        for future in futures:
            results.append(future.result())
    results.sort(key=lambda x: x["roll_no"])
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Roll Number", "Name", "LeetCode Username", "Easy Solved", "Medium Solved", "Hard Solved", "Total Solved"])
    for row in results:
        writer.writerow([row["roll_no"], row["actual_name"], row["username"],
                         row["easy"], row["medium"], row["hard"], row["total"]])
    response = make_response(output.getvalue())
    response.headers["Content-Disposition"] = "attachment; filename=leetcode_stats.csv"
    response.headers["Content-type"] = "text/csv"
    return response
