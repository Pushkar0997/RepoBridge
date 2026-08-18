/* RepoBridge home page: submit the analyze form and go to the run it creates. */
document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("analyze-form");
  if (!form) return;

  const button = document.getElementById("analyze-button");
  const statusEl = document.getElementById("analyze-status");
  const errorBox = document.getElementById("analyze-error");
  const errorMsg = document.getElementById("analyze-error-message");
  const errorLink = document.getElementById("analyze-error-link");

  form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const repoUrl = document.getElementById("repo_url").value.trim();
    const branch = document.getElementById("branch_or_ref").value.trim();

    errorBox.hidden = true;
    errorLink.hidden = true;
    button.disabled = true;
    statusEl.textContent = "Fetching the repository tree and classifying entries\u2026";

    const payload = { repo_url: repoUrl };
    if (branch) payload.branch_or_ref = branch;

    try {
      const response = await fetch("/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      let body = null;
      try {
        body = await response.json();
      } catch (e) {
        body = null;
      }

      if (response.ok && body && body.run_id) {
        statusEl.textContent = "Done. Opening the run\u2026";
        window.location.href = "/runs/" + body.run_id;
        return;
      }

      /* Show what actually went wrong, not a generic message. */
      const detail = body && body.detail ? body.detail : null;
      errorMsg.textContent =
        (detail && detail.message) ||
        (body && body.message) ||
        ("The server returned HTTP " + response.status + ".");

      /* A failed run is still a run: link to it when one was recorded. */
      if (detail && detail.run_id) {
        const link = errorLink.querySelector("a");
        link.href = "/runs/" + detail.run_id;
        errorLink.hidden = false;
      }
      errorBox.hidden = false;
    } catch (networkError) {
      errorMsg.textContent =
        "Could not reach the RepoBridge server: " + networkError.message;
      errorBox.hidden = false;
    } finally {
      button.disabled = false;
      statusEl.textContent = "";
    }
  });
});
