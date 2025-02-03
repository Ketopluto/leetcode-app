document.addEventListener("DOMContentLoaded", function() {
    const loadingScreen = document.getElementById("loading-screen");
    setTimeout(() => {
      loadingScreen.style.display = "none";
    }, 2000); // Adjust the duration if needed
  });
  