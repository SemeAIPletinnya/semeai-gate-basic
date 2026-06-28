const { spawnSync } = require("node:child_process");
const path = require("node:path");

function checkAIAnswer(request, options = {}) {
  const root = options.root || path.resolve(__dirname, "..", "..");
  const python = options.python || process.env.PYTHON || "python";
  const args = ["-m", "semeai_gate_basic"];
  if (options.receiptDir) {
    args.push("--receipt-dir", options.receiptDir);
  }
  const completed = spawnSync(python, args, {
    cwd: root,
    input: JSON.stringify(request),
    encoding: "utf8",
    timeout: options.timeoutMs || 10000
  });
  if (completed.error) {
    throw completed.error;
  }
  if (completed.status !== 0) {
    throw new Error(completed.stderr || `SemeAI Gate exited with ${completed.status}`);
  }
  return JSON.parse(completed.stdout);
}

module.exports = {
  checkAIAnswer,
  ACTION_TO_INTERNAL: {
    SHOW: "PROCEED",
    REVIEW: "NEEDS_REVIEW",
    BLOCK: "SILENCE"
  }
};
