"use strict";

// Pure navigation rules shared by the UI and its regression tests.
((factory) => {
  if (typeof module !== "undefined" && module.exports)
    module.exports = factory();
  else window.CqaWorkflows = factory();
})(() => {
  const isProblem = (row) =>
    Boolean(
      row.critical ||
        row.needs_review ||
        row.pending_appeals ||
        row.status === "failed",
    );
  function problemQueue(rows, currentId = null) {
    const ids = [...new Set(rows.filter(isProblem).map((r) => r.id))];
    const index = ids.indexOf(currentId);
    return index < 0 ? ids : [...ids.slice(index), ...ids.slice(0, index)];
  }
  function reviewStep(ids, currentId, rows, direction = 1) {
    const index = ids.indexOf(currentId);
    const current = new Map(rows.map((row) => [row.id, row]));
    if (index < 0) return null;
    if (direction < 0)
      return (
        ids
          .slice(0, index)
          .reverse()
          .find((id) => current.has(id)) || null
      );
    return (
      ids
        .slice(index + 1)
        .find((id) => current.has(id) && isProblem(current.get(id))) || null
    );
  }
  function externalRecordingUrl(value) {
    try {
      const url = new URL(value);
      return ["https:", "http:"].includes(url.protocol) ? url.href : null;
    } catch {
      return null;
    }
  }
  return { isProblem, problemQueue, reviewStep, externalRecordingUrl };
});
