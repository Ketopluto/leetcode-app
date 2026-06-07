"""
Production-ready LeetCode API fetcher that hits LeetCode's official GraphQL API directly,
bypassing unreliable third-party wrappers.
"""

import asyncio
import aiohttp
import time
import json
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

# -----------------------
# Configuration
# -----------------------
CACHE_TTL = 300            # seconds each student's stats are cached in memory
CONCURRENCY = 15           # Reduced to avoid LeetCode rate limits
TIMEOUT_SECONDS = 15       # timeout for GraphQL requests
MAX_RETRIES = 3            # retry attempts per user

# Exponential backoff delays (seconds)
BACKOFF_DELAYS = [1.0, 2.0, 4.0]

LEETCODE_GRAPHQL_URL = "https://leetcode.com/graphql/"

BASIC_STATS_QUERY = """
query getUserProfile($username: String!) {
  matchedUser(username: $username) {
    submitStatsGlobal {
      acSubmissionNum {
        difficulty
        count
      }
    }
  }
}
"""

async def fetch_from_graphql(
    username: str,
    session: aiohttp.ClientSession,
    timeout_seconds: int = TIMEOUT_SECONDS
) -> Optional[dict]:
    """Fetch basic stats directly from LeetCode GraphQL with retries."""
    
    payload = {
        "query": BASIC_STATS_QUERY,
        "variables": {"username": username}
    }
    
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    for attempt in range(MAX_RETRIES):
        try:
            timeout = aiohttp.ClientTimeout(total=timeout_seconds)
            async with session.post(LEETCODE_GRAPHQL_URL, json=payload, headers=headers, timeout=timeout) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    if "errors" in data:
                        # Usually means user not found or invalid
                        return {"error": "user_not_found"}
                    
                    matched_user = data.get("data", {}).get("matchedUser")
                    if not matched_user:
                        return {"error": "user_not_found"}
                        
                    ac_submissions = matched_user.get("submitStatsGlobal", {}).get("acSubmissionNum", [])
                    
                    stats = {"easy": 0, "medium": 0, "hard": 0, "total": 0}
                    for sub in ac_submissions:
                        diff = sub.get("difficulty", "").lower()
                        count = sub.get("count", 0)
                        if diff == "all":
                            stats["total"] = count
                        elif diff in stats:
                            stats[diff] = count
                            
                    return stats
                
                elif resp.status == 404:
                    return {"error": "user_not_found"}
                elif resp.status == 429:
                    # Rate limited! Back off significantly
                    print(f"[Rate Limit] Hit rate limit fetching {username}")
                    await asyncio.sleep(BACKOFF_DELAYS[attempt] * 2)
                    continue
                elif 500 <= resp.status < 600:
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(BACKOFF_DELAYS[attempt])
                    continue
                else:
                    return None
                    
        except asyncio.TimeoutError:
            print(f"[GraphQL] Timeout fetching {username} (attempt {attempt + 1}/{MAX_RETRIES})")
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(BACKOFF_DELAYS[attempt])
                
        except aiohttp.ClientError as e:
            print(f"[GraphQL] Client error fetching {username}: {e}")
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(BACKOFF_DELAYS[attempt])
                
        except Exception as e:
            print(f"[GraphQL] Unexpected error fetching {username}: {e}")
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(BACKOFF_DELAYS[attempt])
    
    return None


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
    username = (username or "").strip()
    
    if not username or username.lower() == "higher studies":
        result = {"easy": 0, "medium": 0, "hard": 0, "total": 0, "error": None}
    else:
        result = await fetch_from_graphql(username, session)
    
    if result is None:
        # Request failed - use cached data if available
        if cached_stats:
            print(f"[Fallback] Using cached stats for {username}")
            result = {
                "easy": cached_stats.get("easy_solved", 0),
                "medium": cached_stats.get("medium_solved", 0),
                "hard": cached_stats.get("hard_solved", 0),
                "total": cached_stats.get("total_solved", 0),
                "error": None,
                "is_stale": True
            }
        else:
            # No cached data - return zeros with temp error indicator
            result = {
                "easy": 0, "medium": 0, "hard": 0, "total": 0,
                "error": "api_failed"
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
        "fetch_error": result.get("error") if "is_stale" not in result else None,
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
                        "fetch_error": str(e),
                        "is_stale": False,
                        "fetched_at": int(time.time())
                    }
        
        tasks = [asyncio.create_task(guarded_fetch(s)) for s in students_to_fetch]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        return results


def get_circuit_breaker_status() -> dict:
    """Mock circuit breaker status since we are now direct to LeetCode"""
    return {
        "leetcode_graphql": {
            "failures": 0,
            "is_open": False,
            "last_failure": None
        }
    }
