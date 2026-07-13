/**
 * Remote SaaS client for api.semeai.tech
 */
async function request(baseUrl, apiKey, method, path, body) {
  const res = await fetch(`${baseUrl.replace(/\/$/, "")}${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
      Accept: "application/json",
      "User-Agent": "semeai-gate-node-sdk/0.2",
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  let data;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { raw: text };
  }
  if (!res.ok) {
    const err = new Error(data.error || res.statusText || "request failed");
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

function createClient({ apiKey, baseUrl = "https://api.semeai.tech" } = {}) {
  if (!apiKey) throw new Error("apiKey is required");
  return {
    check: (payload) => request(baseUrl, apiKey, "POST", "/v0/check", payload),
    account: () => request(baseUrl, apiKey, "GET", "/v0/account"),
    usage: () => request(baseUrl, apiKey, "GET", "/v0/usage"),
    keys: () => request(baseUrl, apiKey, "GET", "/v0/keys"),
    rotateKey: (label = "rotated") =>
      request(baseUrl, apiKey, "POST", "/v0/keys/rotate", { label }),
  };
}

module.exports = {
  createClient,
  ACTION_TO_INTERNAL: {
    SHOW: "PROCEED",
    REVIEW: "NEEDS_REVIEW",
    BLOCK: "SILENCE",
  },
};
