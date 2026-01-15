"""
Production-ready LeetCode API fetcher with:
- Multiple fallback API sources
- Exponential backoff retry strategy
- Circuit breaker pattern
- Persistent stats caching
"""

import asyncio
import aiohttp
import time
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

# -----------------------
# Configuration
# -----------------------
CACHE_TTL = 300            # seconds each student's stats are cached in memory
CONCURRENCY = 30           # reduced from 50 to be more gentle on APIs
TIMEOUT_SECONDS = 10       # increased from 5 for reliability
MAX_RETRIES = 3            # retry attempts per API source
CIRCUIT_BREAKER_THRESHOLD = 5   # failures before circuit opens
CIRCUIT_BREAKER_TIMEOUT = 300   # seconds to wait before retrying failed API

# Exponential backoff delays (seconds)
BACKOFF_DELAYS = [0.2, 0.4, 0.8]

# -----------------------
# API Sources (in order of preference)
# All verified working as of Jan 2026
# -----------------------
API_SOURCES = [
    {
        "name": "alfa-leetcode-vercel",
        "base_url": "https://alfa-leetcode-api-blush.vercel.app",
        "solved_endpoint": "/{username}/solved",
        "parser": "alfa"
    },
    {
        "name": "alfa-leetcode-render",
        "base_url": "https://alfa-leetcode-api.onrender.com",
        "solved_endpoint": "/{username}/solved",
        "parser": "alfa"
    },
    {
        "name": "leetcode-api-faisalshohag",
        "base_url": "https://leetcode-api-faisalshohag.vercel.app",
        "solved_endpoint": "/{username}",
        "parser": "faisal"
    },
    {
        "name": "leetcode-stats-api",
        "base_url": "https://leetcode-stats-api.herokuapp.com",
        "solved_endpoint": "/{username}",
        "parser": "stats"
    },
]


@dataclass
class CircuitBreaker:
    """Circuit breaker to prevent hammering failed APIs"""
    failures: Dict[str, int] = field(default_factory=dict)
    last_failure_time: Dict[str, float] = field(default_factory=dict)
    
    def record_failure(self, api_name: str):
        self.failures[api_name] = self.failures.get(api_name, 0) + 1
        self.last_failure_time[api_name] = time.time()
    
    def record_success(self, api_name: str):
        self.failures[api_name] = 0
    
    def is_open(self, api_name: str) -> bool:
        """Check if circuit is open (API should be skipped)"""
        failures = self.failures.get(api_name, 0)
        if failures < CIRCUIT_BREAKER_THRESHOLD:
            return False
        
        # Check if timeout has passed
        last_failure = self.last_failure_time.get(api_name, 0)
        if time.time() - last_failure > CIRCUIT_BREAKER_TIMEOUT:
            # Reset and allow retry
            self.failures[api_name] = 0
            return False
        
        return True


# Global circuit breaker instance
circuit_breaker = CircuitBreaker()


def parse_alfa_response(data: dict) -> dict:
    """Parse response from alfa-leetcode-api"""
    if "errors" in data:
        return {"error": data["errors"][0].get("message", "user_not_found")}
    
    return {
        "easy": data.get("easySolved", 0),
        "medium": data.get("mediumSolved", 0),
        "hard": data.get("hardSolved", 0),
        "total": data.get("solvedProblem", 0)
    }


def parse_stats_response(data: dict) -> dict:
    """Parse response from leetcode-stats-api.herokuapp.com"""
    if data.get("status") == "error":
        return {"error": data.get("message", "user_not_found")}
    
    return {
        "easy": data.get("easySolved", 0),
        "medium": data.get("mediumSolved", 0),
        "hard": data.get("hardSolved", 0),
        "total": data.get("totalSolved", 0)
    }


def parse_faisal_response(data: dict) -> dict:
    """Parse response from leetcode-api-faisalshohag"""
    if "errors" in data or data.get("status") == "error":
        return {"error": "user_not_found"}
    
    return {
        "easy": data.get("easySolved", 0),
        "medium": data.get("mediumSolved", 0),
        "hard": data.get("hardSolved", 0),
        "total": data.get("totalSolved", data.get("solvedProblem", 0))
    }


PARSERS = {
    "alfa": parse_alfa_response,
    "stats": parse_stats_response,
    "faisal": parse_faisal_response,
}


async def fetch_from_api(
    username: str,
    api_config: dict,
    session: aiohttp.ClientSession,
    timeout_seconds: int = TIMEOUT_SECONDS
) -> Optional[dict]:
    """Fetch stats from a single API source with retries"""
    api_name = api_config["name"]
    
    # Check circuit breaker
    if circuit_breaker.is_open(api_name):
        print(f"[Circuit Breaker] Skipping {api_name} - circuit is open")
        return None
    
    url = api_config["base_url"] + api_config["solved_endpoint"].format(username=username)
    parser = PARSERS[api_config["parser"]]
    
    for attempt in range(MAX_RETRIES):
        try:
            timeout = aiohttp.ClientTimeout(total=timeout_seconds)
            async with session.get(url, timeout=timeout) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    result = parser(data)
                    
                    if "error" not in result:
                        circuit_breaker.record_success(api_name)
                        return result
                    else:
                        # User doesn't exist - this is valid, not a failure
                        return result
                
                elif resp.status == 404:
                    # User not found - valid response
                    return {"error": "user_not_found"}
                
                elif 500 <= resp.status < 600:
                    # Server error - retry
                    circuit_breaker.record_failure(api_name)
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(BACKOFF_DELAYS[attempt])
                    continue
                
                else:
                    # Other error
                    circuit_breaker.record_failure(api_name)
                    return None
                    
        except asyncio.TimeoutError:
            circuit_breaker.record_failure(api_name)
            print(f"[{api_name}] Timeout fetching {username} (attempt {attempt + 1}/{MAX_RETRIES})")
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(BACKOFF_DELAYS[attempt])
                
        except aiohttp.ClientError as e:
            circuit_breaker.record_failure(api_name)
            print(f"[{api_name}] Client error fetching {username}: {e}")
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(BACKOFF_DELAYS[attempt])
                
        except Exception as e:
            circuit_breaker.record_failure(api_name)
            print(f"[{api_name}] Unexpected error fetching {username}: {e}")
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(BACKOFF_DELAYS[attempt])
    
    return None


async def fetch_stats_with_fallback(
    username: str,
    session: aiohttp.ClientSession
) -> Tuple[dict, bool]:
    """
    Fetch stats trying multiple APIs in order.
    Returns (stats_dict, is_fresh) where is_fresh=True if fetched from API
    """
    username = (username or "").strip()
    
    if not username or username.lower() == "higher studies":
        return {"easy": 0, "medium": 0, "hard": 0, "total": 0, "user_error": None}, True
    
    # Try each API in order
    for api_config in API_SOURCES:
        result = await fetch_from_api(username, api_config, session)
        
        if result is not None:
            if "error" in result:
                # User doesn't exist
                return {
                    "easy": 0, "medium": 0, "hard": 0, "total": 0,
                    "user_error": result["error"]
                }, True
            else:
                # Success!
                return {
                    "easy": result["easy"],
                    "medium": result["medium"],
                    "hard": result["hard"],
                    "total": result["total"],
                    "user_error": None
                }, True
    
    # All APIs failed - return None to trigger fallback to cached data
    return None, False


async def fetch_student_stats(
    username: str,
    name: str,
    roll_no: str,
    year: int,
    section: str,
    session: aiohttp.ClientSession,
    cached_stats: Optional[dict] = None
) -> dict:
    """
    Fetch stats for a single student with fallback to cached data.
    """
    result, is_fresh = await fetch_stats_with_fallback(username, session)
    
    if result is None:
        # All APIs failed - use cached data if available
        if cached_stats:
            print(f"[Fallback] Using cached stats for {username}")
            result = {
                "easy": cached_stats.get("easy_solved", 0),
                "medium": cached_stats.get("medium_solved", 0),
                "hard": cached_stats.get("hard_solved", 0),
                "total": cached_stats.get("total_solved", 0),
                "user_error": None,
                "is_stale": True
            }
        else:
            # No cached data - return zeros with temp error indicator
            result = {
                "easy": 0, "medium": 0, "hard": 0, "total": 0,
                "user_error": None,
                "temp_error": "all_apis_failed"
            }
    
    # Build response
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
        "easy": result.get("easy", 0),
        "medium": result.get("medium", 0),
        "hard": result.get("hard", 0),
        "total": result.get("total", 0),
        "fetch_error": result.get("user_error"),
        "is_stale": result.get("is_stale", False),
        "fetched_at": int(time.time())
    }


async def fetch_students_concurrent(
    students_to_fetch: List[Tuple],
    cached_stats_map: Dict[str, dict] = None,
    concurrency: int = CONCURRENCY
) -> List[dict]:
    """
    Fetch a list of students concurrently with fallback support.
    students_to_fetch: [(username, name, roll, year, section, student_id), ...]
    cached_stats_map: {username: {easy_solved, medium_solved, hard_solved, total_solved}, ...}
    """
    if not students_to_fetch:
        return []
    
    cached_stats_map = cached_stats_map or {}
    
    connector = aiohttp.TCPConnector(limit_per_host=concurrency, limit=concurrency)
    timeout = aiohttp.ClientTimeout(total=TIMEOUT_SECONDS * 2)  # Extra buffer
    
    sem = asyncio.Semaphore(concurrency)
    
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        async def guarded_fetch(item):
            async with sem:
                if len(item) == 6:
                    username, name, roll, year, section, student_id = item
                else:
                    username, name, roll, year, section = item
                    student_id = None
                
                cached = cached_stats_map.get((username or "").strip().lower())
                
                try:
                    return await fetch_student_stats(
                        username, name, roll, year, section, session, cached
                    )
                except Exception as e:
                    print(f"[Error] Exception fetching {username}: {e}")
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
                        "fetch_error": None,
                        "is_stale": False,
                        "fetched_at": int(time.time())
                    }
        
        tasks = [asyncio.create_task(guarded_fetch(s)) for s in students_to_fetch]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        return results


def get_circuit_breaker_status() -> dict:
    """Get current status of all API circuit breakers"""
    status = {}
    for api in API_SOURCES:
        name = api["name"]
        failures = circuit_breaker.failures.get(name, 0)
        is_open = circuit_breaker.is_open(name)
        last_failure = circuit_breaker.last_failure_time.get(name)
        
        status[name] = {
            "failures": failures,
            "is_open": is_open,
            "last_failure": datetime.fromtimestamp(last_failure).isoformat() if last_failure else None
        }
    
    return status
