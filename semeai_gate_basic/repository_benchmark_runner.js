"use strict";

const fs = require("node:fs");
const path = require("node:path");

async function main() {
  const corePath = path.resolve(process.argv[2] || "");
  if (!corePath.endsWith(`${path.sep}benchmark.js`)) throw new Error("invalid canonical core path");
  const core = require(corePath);
  const input = JSON.parse(fs.readFileSync(0, "utf8"));
  const snapshot = input.snapshot;
  if (!snapshot || typeof snapshot !== "object") throw new Error("snapshot is required");
  if (Array.isArray(input.paths)) {
    snapshot.normalized_evidence = core.deriveEvidence(snapshot, input.paths, input.document_terms || {});
  }
  const candidate = core.scoreSnapshot(snapshot);
  const gate = core.runPresentationGate(candidate);
  const indicators = core.computeIndicators(candidate);
  const visual = core.computeVisualPhase(snapshot.public_metadata && snapshot.public_metadata.stars);
  const receipt = await core.buildReceipt(candidate, gate, visual);
  process.stdout.write(JSON.stringify({ candidate, gate, indicators, visual, receipt }));
}

main().catch(() => process.exit(1));
