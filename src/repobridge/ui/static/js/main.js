/* RepoBridge home page: submit the analyze form and go to the run it creates. */
document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("analyze-form");
  if (!form) return;

  const button = document.getElementById("analyze-button");
  const statusEl = document.getElementById("analyze-status");
  const elapsedEl = document.getElementById("analyze-elapsed");
  const errorBox = document.getElementById("analyze-error");

  /*
    Milestone messages, by elapsed seconds.

    Before this, one static line was set at submit time and never changed again.
    `psf/requests` takes about eight seconds and `github/docs` minutes, and for all of
    that a person saw the same sentence with no way to tell working from stuck -- which is
    exactly the "states that are visually indistinguishable" failure signal in evals.md.

    These four lines are announced: the status element is a polite live region. The
    ticking seconds beside them are not, because a clock read aloud once a second is
    noise, not information -- so the clock lives in a separate aria-hidden element and
    only these lines ever reach a screen reader.
  */
  const STAGES = [
    [0, "Fetching repository metadata and the file tree…"],
    [8, "Still working — reading and extracting the selected files…"],
    [25, "Still working. Large repositories take a while; nothing is stuck."],
    [60, "Still working. Very large repositories can take several minutes."],
  ];

  let timer = null;

  function startProgress() {
    const began = Date.now();
    statusEl.textContent = STAGES[0][1];
    elapsedEl.textContent = "0s";
    let stage = 0;

    timer = window.setInterval(() => {
      const seconds = Math.floor((Date.now() - began) / 1000);
      elapsedEl.textContent = seconds + "s";
      while (stage + 1 < STAGES.length && seconds >= STAGES[stage + 1][0]) {
        stage += 1;
        statusEl.textContent = STAGES[stage][1];
      }
    }, 1000);
  }

  function stopProgress() {
    if (timer !== null) {
      window.clearInterval(timer);
      timer = null;
    }
    elapsedEl.textContent = "";
  }

  /*
    Fill the empty live region.

    The container ships empty and carries role="alert", rather than shipping pre-written
    prose kept out of sight with `hidden`. Two things change: the markup no longer asserts
    "Analysis failed." on every render of a page where nothing has failed, and the failure
    is now announced at the moment it happens instead of appearing silently.
  */
  function showError(message, failedRunId) {
    errorBox.textContent = "";

    const heading = document.createElement("strong");
    heading.textContent = "Analysis failed.";
    errorBox.appendChild(heading);

    const para = document.createElement("p");
    para.textContent = message;
    errorBox.appendChild(para);

    if (failedRunId) {
      /* A failed run is still a run: link to it when one was recorded. */
      const para2 = document.createElement("p");
      para2.appendChild(
        document.createTextNode("The attempt was still recorded — ")
      );
      const link = document.createElement("a");
      link.href = "/runs/" + failedRunId;
      link.textContent = "open the failed run";
      para2.appendChild(link);
      para2.appendChild(document.createTextNode("."));
      errorBox.appendChild(para2);
    }

    errorBox.hidden = false;
    errorBox.focus();
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const repoUrl = document.getElementById("repo_url").value.trim();
    const branch = document.getElementById("branch_or_ref").value.trim();

    errorBox.hidden = true;
    errorBox.textContent = "";
    button.disabled = true;
    form.setAttribute("aria-busy", "true");
    startProgress();

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
        stopProgress();
        statusEl.textContent = "Done. Opening the run…";
        window.location.href = "/runs/" + body.run_id;
        return;
      }

      /* Show what actually went wrong, not a generic message.
         One envelope for every API failure -- see api/errors.py. */
      const err = body && body.error ? body.error : null;
      showError(
        (err && err.message) ||
          "The server returned HTTP " + response.status + ".",
        err && err.details && err.details.run_id
      );
    } catch (networkError) {
      showError(
        "Could not reach the RepoBridge server: " + networkError.message,
        null
      );
    } finally {
      stopProgress();
      button.disabled = false;
      form.removeAttribute("aria-busy");
      statusEl.textContent = "";
    }
  });
});


/*
  Run detail page: re-summarise a stored run.

  POSTs to the API endpoint and reloads, so the page re-renders from the database rather
  than from anything this script believes. HTTP 200 is not success here: a provider error
  is a normal, recorded outcome that comes back 200 with status "provider_error", and
  showing it is the point.
*/
document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("resummarise-form");
  if (!form) return;

  const runId = form.dataset.runId;
  const button = document.getElementById("resummarise-button");
  const statusEl = document.getElementById("resummarise-status");
  const errorBox = document.getElementById("resummarise-error");

  /* Same treatment as the analyze error: an empty live region the script fills. */
  function showError(message) {
    errorBox.textContent = "";
    const heading = document.createElement("strong");
    heading.textContent = "Still no summary.";
    errorBox.appendChild(heading);
    const para = document.createElement("p");
    para.className = "mono";
    para.textContent = message;
    errorBox.appendChild(para);
    errorBox.hidden = false;
    errorBox.focus();
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();

    errorBox.hidden = true;
    errorBox.textContent = "";
    button.disabled = true;
    form.setAttribute("aria-busy", "true");
    statusEl.textContent = "Summarising the stored content…";

    try {
      const response = await fetch("/api/runs/" + runId + "/summarize", {
        method: "POST",
      });

      let body = null;
      try {
        body = await response.json();
      } catch (e) {
        body = null;
      }

      if (response.ok && body && body.status === "ok") {
        statusEl.textContent = "Done. Reloading…";
        window.location.reload();
        return;
      }

      /* A 200 carrying status "provider_error" lands here, which is correct: the request
         succeeded and the summarisation did not, and the second is what to report. */
      showError(
        (body && body.error && body.error.message) ||
          (body && body.error) ||
          "The server returned HTTP " + response.status + "."
      );
    } catch (networkError) {
      showError("Could not reach the RepoBridge server: " + networkError.message);
    } finally {
      button.disabled = false;
      form.removeAttribute("aria-busy");
      statusEl.textContent = "";
    }
  });
});
