// Fun facts for loading screen
const funFacts = [
  "💡 The first computer bug was an actual moth found in 1947!",
  "🚀 JavaScript was created in just 10 days by Brendan Eich!",
  "👩‍💻 Ada Lovelace, daughter of poet Lord Byron, was the world's first programmer in 1842!",
  "🎯 There are over 700 programming languages in existence!",
  "💻 NASA still uses programs from the 1970s for spacecraft!",
  "🔥 The first programming language was FORTRAN, created in the 1950s!",
  "⚡ Programmers make an average of 15 mistakes per 1000 lines of code!",
  "🌟 The term 'debugging' comes from removing actual bugs from computers!",
  "🎨 LeetCode was founded in 2015 and now has over 26 million monthly visitors!",
  "🏆 Consistent practice is the key to mastering coding!",
  "📊 The average LeetCode has over 3,500 problems across three difficulty levels!",
  "💪 Programming is 10% writing code and 90% figuring out why it doesn't work!",
  "🧠 Your brain is doing incredible work right now - keep it up!",
  "🎓 Every expert was once a beginner who refused to give up!",
  "⏰ The best time to start was yesterday, the second best time is now!",
  "🌈 Debugging is like being a detective where you're also the murderer!",
  "✨ Good code is its own best documentation!",
  "🎪 Talk is cheap, show me the code! - Linus Torvalds",
  "🔧 Any fool can write code that a computer can understand. Good programmers write code that humans can understand!",
  "🎯 Code never lies, comments sometimes do!",
  "🚦 Always code as if the person maintaining your code is a violent psychopath who knows where you live!",
  "📚 The best error message is the one that never shows up!",
  "🎁 Software is like sex: it's better when it's free! - Linus Torvalds",
  "⚙️ Programmers are machines that turn coffee into code!",
  "🌍 There are only two hard things in Computer Science: cache invalidation and naming things!",
  "🎲 The first computer game was created in 1961!",
  "🔐 Prime numbers are the foundation of modern encryption algorithms!",
  "📱 Your smartphone has more computing power than the computers that sent astronauts to the moon!",
  "🎭 C programming language was created to implement Unix operating system!",
  "🌟 The first emoticon :-) was created by Scott Fahlman in 1982!",
  "🚀 Java is used by over 5 billion devices worldwide!",
  "💎 Python is named after Monty Python, not the snake!",
  "🎯 'Hello, World!' is traditionally the first program people write when learning a new language!",
  "🔮 Machine learning models can now write basic code!",
  "🎨 CSS stands for Cascading Style Sheets!",
  "⚡ The first 1GB hard drive weighed over 500 pounds!",
  "🌟 40% of developers are self-taught!",
  "🎮 The video game industry is larger than the movie and music industries combined!",
  "💡 Bill Gates' first computer program was a tic-tac-toe game!",
  "🏃 The first computer virus was created in 1983!"
];

// LeetCode Pro Tips for loading screen
const leetcodeTips = [
  "Start with Easy problems to build confidence, then gradually move to Medium",
  "Practice the Blind 75 list - it covers the most important patterns",
  "Understand time & space complexity before jumping to code",
  "Draw out examples on paper - it helps visualize the problem",
  "Learn patterns: Two Pointers, Sliding Window, Binary Search, DFS/BFS",
  "Always think about edge cases: empty input, single element, duplicates",
  "Try to solve without hints first, even if it takes longer",
  "Review your solutions - there's always room for optimization",
  "Consistency beats intensity: 1 problem daily > 10 problems weekly",
  "Don't memorize solutions - understand the underlying patterns",
  "Master arrays and strings first - they're the foundation",
  "Hash maps are your best friend for O(1) lookups",
  "Stuck? Break the problem into smaller sub-problems",
  "Practice explaining your approach out loud - great for interviews",
  "Read the constraints - they often hint at the expected complexity"
];

// Spinner types
const spinnerTypes = [
  'circle',
  'dots',
  'pulse',
  'squares',
  'orbit',
  'bars',
  'ring',
  'bounce'
];

function getRandomSpinner() {
  const type = spinnerTypes[Math.floor(Math.random() * spinnerTypes.length)];

  switch (type) {
    case 'circle':
      return '<div class="spinner-circle"></div>';
    case 'dots':
      return '<div class="spinner-dots"><div class="dot"></div><div class="dot"></div><div class="dot"></div></div>';
    case 'pulse':
      return '<div class="spinner-pulse"></div>';
    case 'squares':
      return '<div class="spinner-squares">' + '<div class="square"></div>'.repeat(9) + '</div>';
    case 'orbit':
      return '<div class="spinner-orbit"><div class="orbit-circle"></div><div class="orbit-circle"></div></div>';
    case 'bars':
      return '<div class="spinner-bars">' + '<div class="bar"></div>'.repeat(5) + '</div>';
    case 'ring':
      return '<div class="spinner-ring"></div>';
    case 'bounce':
      return '<div class="spinner-bounce"><div class="ball"></div><div class="ball"></div><div class="ball"></div></div>';
    default:
      return '<div class="spinner-circle"></div>';
  }
}

// API endpoints for variety (text + images)
const contentAPIs = [
  // Text-based facts
  {
    name: 'useless-facts',
    type: 'text',
    url: 'https://uselessfacts.jsph.pl/api/v2/facts/random',
    parse: (data) => ({
      text: `💡 ${data.text}`,
      image: null
    })
  },
  {
    name: 'cat-facts',
    type: 'text',
    url: 'https://catfact.ninja/fact',
    parse: (data) => ({
      text: `🐱 ${data.fact}`,
      image: null
    })
  },
  {
    name: 'quotes',
    type: 'text',
    url: 'https://api.quotable.io/random',
    parse: (data) => ({
      text: `💬 "${data.content}" - ${data.author}`,
      image: null
    })
  },
  {
    name: 'programming-jokes',
    type: 'text',
    url: 'https://official-joke-api.appspot.com/random_joke',
    parse: (data) => ({
      text: `😄 ${data.setup} ${data.punchline}`,
      image: null
    })
  },
  {
    name: 'advice',
    type: 'text',
    url: 'https://api.adviceslip.com/advice',
    parse: (data) => ({
      text: `💭 ${data.slip.advice}`,
      image: null
    })
  },

  // Image-based content (Art Institute of Chicago)
  {
    name: 'art-chicago',
    type: 'image',
    url: () => `https://api.artic.edu/api/v1/artworks?page=${Math.floor(Math.random() * 100) + 1}&limit=1`,
    parse: (data) => {
      const artwork = data.data[0];
      const imageId = artwork.image_id;

      return {
        text: `🎨 "${artwork.title}" by ${artwork.artist_display}`,
        image: imageId ? `https://www.artic.edu/iiif/2/${imageId}/full/400,/0/default.jpg` : null
      };
    }
  },

  // Dog images with facts
  {
    name: 'dog-images',
    type: 'image',
    url: 'https://dog.ceo/api/breeds/image/random',
    parse: (data) => ({
      text: '🐶 Random dog breed - Dogs have been humans\' best friends for over 15,000 years!',
      image: data.message
    })
  },

  // Cat images
  {
    name: 'cat-images',
    type: 'image',
    url: 'https://api.thecatapi.com/v1/images/search',
    parse: (data) => ({
      text: '🐱 A majestic feline - Cats spend 70% of their lives sleeping!',
      image: data[0].url
    })
  }
];

// Fallback content if all APIs fail
const fallbackContent = {
  text: "💡 The first computer bug was an actual moth found in 1947!",
  image: null
};

// Note: Content API functions removed - using simpler tips-based loading screen

// Get random fun fact
function getRandomFunFact() {
  return funFacts[Math.floor(Math.random() * funFacts.length)];
}

// Get random tip
function getRandomTip() {
  return leetcodeTips[Math.floor(Math.random() * leetcodeTips.length)];
}

// Tip cycling interval reference
let tipInterval = null;

// Progress bar variables
let progressInterval = null;
let currentProgress = 0;

// Show loading screen with random spinner
function showLoading() {
  const loadingScreen = document.getElementById('loading-screen');
  const spinnerContainer = document.getElementById('spinner-container');
  const tipTextElement = document.getElementById('tip-text');
  const progressBar = document.getElementById('progress-bar');

  loadingScreen.classList.remove('fade-out');
  loadingScreen.style.display = 'flex';
  spinnerContainer.innerHTML = getRandomSpinner();

  // Set initial tip
  if (tipTextElement) {
    tipTextElement.textContent = getRandomTip();

    // Cycle tips every 3 seconds
    if (tipInterval) clearInterval(tipInterval);
    tipInterval = setInterval(() => {
      tipTextElement.style.animation = 'none';
      tipTextElement.offsetHeight; // Trigger reflow
      tipTextElement.textContent = getRandomTip();
      tipTextElement.style.animation = 'tipFade 0.5s ease-in-out';
    }, 3000);
  }

  // Reset progress bar
  if (progressBar) {
    progressBar.style.animation = 'none';
    progressBar.style.width = '0%';
    progressBar.style.transition = 'width 0.4s ease';
    currentProgress = 0;
    
    if (progressInterval) clearInterval(progressInterval);
    
    // Simulate loading up to 90%
    progressInterval = setInterval(() => {
      if (currentProgress < 90) {
        currentProgress += Math.random() * 15;
        if (currentProgress > 90) currentProgress = 90;
        progressBar.style.width = `${currentProgress}%`;
      }
    }, 300);
  }

  document.getElementById('mainContent').style.display = 'none';
}

// Hide loading screen
function hideLoading() {
  const loadingScreen = document.getElementById('loading-screen');
  const progressBar = document.getElementById('progress-bar');

  if (progressBar) {
    if (progressInterval) clearInterval(progressInterval);
    progressBar.style.width = '100%';
  }

  setTimeout(() => {
    loadingScreen.classList.add('fade-out');

    // Clear tip cycling interval
    if (tipInterval) {
      clearInterval(tipInterval);
      tipInterval = null;
    }

    setTimeout(() => {
      loadingScreen.style.display = 'none';
      document.getElementById('mainContent').style.display = 'block';
    }, 500);
  }, 400); // Wait for 100% width transition before fading out
}

// Build table from results
function buildTable(results) {
  let html = `<table>
                <thead>
                  <tr>
                    <th>Roll Number</th>
                    <th>Name</th>
                    <th>LeetCode Username</th>
                    <th>Year</th>
                    <th>Easy</th>
                    <th>Medium</th>
                    <th>Hard</th>
                    <th>Total</th>
                  </tr>
                </thead>
                <tbody>`;

  results.forEach(row => {
    const yearDisplay = row.year_display || row.year;
    const hasError = row.fetch_error;
    const isHigherStudies = row.username === 'higher studies';

    // Determine row class based on error status
    let rowClass = '';
    if (isHigherStudies) {
      rowClass = 'class="highlight"';
    } else if (hasError) {
      rowClass = 'class="error-row"';
    }

    // Show error indicator for invalid usernames
    let usernameDisplay = row.username;
    if (hasError && !isHigherStudies) {
      usernameDisplay = `<span title="Error: ${row.fetch_error}" style="color: #e53e3e; cursor: help;"><svg class="icon inline" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg> ${row.username}</span>`;
    }

    html += `<tr ${rowClass}>
               <td>${row.roll_no}</td>
               <td><a href="/student/${row.roll_no}" class="student-name-link">${row.actual_name}</a></td>
               <td>${usernameDisplay}</td>
               <td>${yearDisplay}</td>
               <td>${row.easy}</td>
               <td>${row.medium}</td>
               <td>${row.hard}</td>
               <td><strong>${row.total}</strong></td>
             </tr>`;
  });

  html += `</tbody></table>`;
  document.getElementById('tableContainer').innerHTML = html;
}

// Build leaderboard
function buildLeaderboard(results) {
  const top5 = results.sort((a, b) => b.total - a.total).slice(0, 5);
  let html = '';

  top5.forEach((solver, index) => {
    const medal = `<span class="rank-badge rank-${index + 1}">#${index + 1}</span>`;
    const yearDisplay = solver.year_display || solver.year;
    html += `<li>
               <span>${medal} <strong>${solver.actual_name}</strong> (${solver.username}) - ${yearDisplay}</span>
               <span><strong>${solver.total}</strong> problems</span>
             </li>`;
  });

  document.getElementById('leaderboardList').innerHTML = html;
}

// Update stats overview
function updateStatsOverview(results) {
  const totalUsers = results.length;
  const totalProblems = results.reduce((sum, user) => sum + user.total, 0);
  const avgProblems = totalUsers > 0 ? Math.round(totalProblems / totalUsers) : 0;
  const errorCount = results.filter(user => user.fetch_error && user.username !== 'higher studies').length;

  animateCounter('totalUsers', totalUsers);
  animateCounter('totalProblems', totalProblems);
  animateCounter('avgProblems', avgProblems);

  // Log error count for debugging
  if (errorCount > 0) {
    console.warn(`<svg class="icon inline" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg> ${errorCount} users have invalid LeetCode profiles (showing 0 scores)`);
  }
}

// Animate counter
function animateCounter(elementId, targetValue) {
  const element = document.getElementById(elementId);
  const duration = 1000;
  const steps = 50;
  const stepValue = targetValue / steps;
  let currentValue = 0;
  let currentStep = 0;

  const interval = setInterval(() => {
    currentValue += stepValue;
    currentStep++;
    element.textContent = Math.round(currentValue);

    if (currentStep >= steps) {
      element.textContent = targetValue;
      clearInterval(interval);
    }
  }, duration / steps);
}

// Load data from API
function loadData(year = '', showLoadingScreen = true) {
  if (showLoadingScreen) {
    showLoading();
  }

  fetch('/api/stats' + (year ? '?year=' + encodeURIComponent(year) : ''))
    .then(response => response.json())
    .then(data => {
      console.log('API Response:', data);
      console.log('Selected filter:', year);
      console.log('Results count:', data.results.length);

      buildTable(data.results);
      buildLeaderboard(data.results);
      updateStatsOverview(data.results);
      document.getElementById('downloadLink').href = '/download' + (year ? '?year=' + encodeURIComponent(year) : '');

      // Update last refresh timestamp
      updateLastRefreshTime();

      if (showLoadingScreen) {
        // Minimum loading time for better UX
        setTimeout(() => {
          hideLoading();
        }, 1500);
      }
    })
    .catch(error => {
      console.error('Error fetching data:', error);
      if (showLoadingScreen) {
        setTimeout(() => {
          hideLoading();
        }, 1000);
      }
    });
}

// Update last refresh timestamp display
function updateLastRefreshTime() {
  const now = new Date();
  const timeStr = now.toLocaleTimeString();

  // Create or update the refresh indicator
  let refreshIndicator = document.getElementById('refreshIndicator');
  if (!refreshIndicator) {
    const statsOverview = document.querySelector('.stats-overview');
    if (statsOverview) {
      refreshIndicator = document.createElement('div');
      refreshIndicator.id = 'refreshIndicator';
      refreshIndicator.className = 'stat-card';
      refreshIndicator.style.cssText = `
        background: #ffffff;
        border: 1px solid #e2e8f0;
        color: #1e293b;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        text-align: center;
        min-height: 120px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        border-radius: 12px;
      `;
      statsOverview.appendChild(refreshIndicator);
    }
  }
  if (refreshIndicator) {
    refreshIndicator.innerHTML = `
      <div style="font-size: 28px; margin-bottom: 8px;">🔄</div>
      <div style="font-size: 24px; font-weight: 700; margin-bottom: 4px;">${timeStr}</div>
      <div style="font-size: 13px; opacity: 0.9;">Auto-refreshes every 2 min</div>
    `;
  }
}

// Auto-refresh interval (2 minutes = 120000ms)
let autoRefreshInterval = null;
const AUTO_REFRESH_INTERVAL = 120000; // 2 minutes

function startAutoRefresh() {
  // Clear any existing interval
  if (autoRefreshInterval) {
    clearInterval(autoRefreshInterval);
  }

  // Start auto-refresh
  autoRefreshInterval = setInterval(() => {
    const selectedYear = document.getElementById('year')?.value || '';
    console.log('Auto-refreshing data...');
    loadData(selectedYear, false); // false = don't show loading screen
  }, AUTO_REFRESH_INTERVAL);

  console.log('Auto-refresh started (every 2 minutes)');
}

// Initialize
document.addEventListener('DOMContentLoaded', function () {
  // Handle year form submission
  document.getElementById('yearForm').addEventListener('submit', function (e) {
    e.preventDefault();
    const selectedYear = document.getElementById('year').value;
    loadData(selectedYear);
  });

  // Initial load
  loadData();

  // Start auto-refresh
  startAutoRefresh();
});

// Client-side table search (filter as you type)
document.addEventListener('DOMContentLoaded', function () {
  // Check if we're on a page with a table
  const tableContainer = document.getElementById('tableContainer');
  if (!tableContainer) return;

  // Create search input above table
  const tableSection = document.querySelector('.table-section');
  if (tableSection) {
    const searchBar = document.createElement('div');
    searchBar.style.cssText = 'margin-bottom: 20px; display: flex; align-items: center; gap: 10px;';
    searchBar.innerHTML = `
      <input type="text" 
             id="tableSearch" 
             placeholder="🔍 Filter table..." 
             style="flex: 1; padding: 12px 16px; border: 2px solid #cbd5e0; border-radius: 8px; font-size: 15px;">
      <span id="tableCount" style="color: #718096; font-size: 14px; min-width: 150px;"></span>
    `;
    tableSection.insertBefore(searchBar, tableContainer);

    // Add search functionality
    const searchInput = document.getElementById('tableSearch');
    const tableCount = document.getElementById('tableCount');

    searchInput.addEventListener('input', function (e) {
      const searchTerm = e.target.value.toLowerCase();
      const table = tableContainer.querySelector('table');
      if (!table) return;

      const rows = table.querySelectorAll('tbody tr');
      let visibleCount = 0;

      rows.forEach(row => {
        const text = row.textContent.toLowerCase();
        if (text.includes(searchTerm)) {
          row.style.display = '';
          visibleCount++;
        } else {
          row.style.display = 'none';
        }
      });

      tableCount.textContent = `Showing ${visibleCount} of ${rows.length} students`;
    });

    // Initial count
    const initialRows = tableContainer.querySelectorAll('tbody tr').length;
    tableCount.textContent = `Showing ${initialRows} students`;
  }
});
