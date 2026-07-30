document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("analyze-form");
  if (!form) return;

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    alert("Analyze endpoint will be wired in later milestones. For now, verify that the UI and /health work.");
  });
});