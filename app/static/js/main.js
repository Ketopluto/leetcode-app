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

// Get random spinner
function getRandomSpinner() {
  const type = spinnerTypes[Math.floor(Math.random() * spinnerTypes.length)];
  
  switch(type) {
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

// Get random fun fact
function getRandomFunFact() {
  return funFacts[Math.floor(Math.random() * funFacts.length)];
}

// Show loading screen with random spinner
function showLoading() {
  const loadingScreen = document.getElementById('loading-screen');
  const spinnerContainer = document.getElementById('spinner-container');
  const funFactElement = document.getElementById('fun-fact');
  const progressBar = document.getElementById('progress-bar');
  
  loadingScreen.classList.remove('fade-out');
  loadingScreen.style.display = 'flex';
  spinnerContainer.innerHTML = getRandomSpinner();
  funFactElement.textContent = getRandomFunFact();
  
  // Reset progress bar
  progressBar.style.animation = 'none';
  setTimeout(() => {
    progressBar.style.animation = 'progress 3s ease-in-out forwards';
  }, 10);
  
  document.getElementById('mainContent').style.display = 'none';
}

// Hide loading screen
function hideLoading() {
  const loadingScreen = document.getElementById('loading-screen');
  loadingScreen.classList.add('fade-out');
  
  setTimeout(() => {
    loadingScreen.style.display = 'none';
    document.getElementById('mainContent').style.display = 'block';
  }, 500);
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
    
    html += `<tr ${row.username === 'higher studies' ? 'class="highlight"' : ''}>
               <td>${row.roll_no}</td>
               <td><a href="/student/${row.roll_no}" class="student-name-link">${row.actual_name}</a></td>
               <td>${row.username}</td>
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
    const medal = index === 0 ? '🥇' : index === 1 ? '🥈' : index === 2 ? '🥉' : '🏅';
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
  
  animateCounter('totalUsers', totalUsers);
  animateCounter('totalProblems', totalProblems);
  animateCounter('avgProblems', avgProblems);
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
function loadData(year = '') {
  showLoading();
  
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
      
      // Minimum loading time for better UX
      setTimeout(() => {
        hideLoading();
      }, 1500);
    })
    .catch(error => {
      console.error('Error fetching data:', error);
      setTimeout(() => {
        hideLoading();
      }, 1000);
    });
}

// Initialize
document.addEventListener('DOMContentLoaded', function() {
  // Handle year form submission
  document.getElementById('yearForm').addEventListener('submit', function(e) {
    e.preventDefault();
    const selectedYear = document.getElementById('year').value;
    loadData(selectedYear);
  });
  
  // Initial load
  loadData();
});

// Client-side table search (filter as you type)
document.addEventListener('DOMContentLoaded', function() {
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
    
    searchInput.addEventListener('input', function(e) {
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
