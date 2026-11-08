const { test } = require("node:test");
const assert = require("node:assert/strict");
const {
  isProblem,
  problemQueue,
  reviewStep,
  externalRecordingUrl,
} = require("../cqa/web_assets/workflows.js");
const rows = [
  { id: "clean", status: "completed" },
  { id: "critical", critical: true },
  { id: "pending", pending_appeals: 1 },
  { id: "external", needs_review: true },
  { id: "failed", status: "failed" },
  { id: "new", status: "unrated" },
];
test("external recording links require an absolute web URL and retain the query", () => {
  const link = "https://example.test/call.mp3?key=sample%2Bvalue";
  assert.equal(externalRecordingUrl(link), link);
  for (const value of [null, "", "/call.mp3", "file:///call.mp3", "javascript:void(0)"]) {
    assert.equal(externalRecordingUrl(value), null);
  }
});
test("problem list includes critical, unverified, pending and failed; an unassessed record is separate", () => {
  assert.deepEqual(problemQueue(rows), [
    "critical",
    "pending",
    "external",
    "failed",
  ]);
  assert.equal(isProblem(rows[0]), false);
});
test("queue keeps the filtered order and does not reintroduce filtered-out records", () => {
  assert.deepEqual(problemQueue([rows[3], rows[1]]), ["external", "critical"]);
  assert.deepEqual(problemQueue(rows, "external"), [
    "external",
    "failed",
    "critical",
    "pending",
  ]);
});
test("next skips resolved and removed entries, never loops at the end", () => {
  const ids = problemQueue(rows);
  const current = rows
    .filter((r) => r.id !== "external")
    .map((r) => (r.id === "pending" ? { ...r, pending_appeals: 0 } : r));
  assert.equal(reviewStep(ids, "critical", current), "failed");
  assert.equal(reviewStep(ids, "failed", current), null);
  assert.equal(reviewStep(ids, "unknown", current), null);
});
test("previous can revisit a now-resolved dialogue; new problems do not reorder a running queue", () => {
  const ids = problemQueue(rows);
  const current = rows
    .map((r) => (r.id === "critical" ? { id: r.id } : r))
    .concat({ id: "new-problem", critical: true });
  assert.equal(reviewStep(ids, "pending", current, -1), "critical");
  assert.equal(reviewStep(ids, "failed", current), null);
});
test("empty and single-item queues have no artificial next item", () => {
  assert.deepEqual(problemQueue([]), []);
  assert.equal(reviewStep(["critical"], "critical", rows), null);
  assert.equal(reviewStep(["critical"], "critical", rows, -1), null);
});
