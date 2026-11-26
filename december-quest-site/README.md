# SEFIROT DECEMBER QUEST · isolated static site

This folder is an isolated **paper-only** December 2026 football analytics front-end. It does not implement sportsbook bets or backend prediction execution.

## Vercel deployment

- Import GitHub repository `VolodimerT/Sefirot` and select branch `feature/december-quest-web-v3-20261123`.
- Set **Root Directory** to `december-quest-site`.
- Framework preset: `Other`, build command blank, output directory `.` (the folder itself contains `index.html`).
- Publish on HTTPS after preview inspection. Never include Supabase `service_role` secrets in the site; the file contains only a public publishable key.
- The site uses Supabase Auth and user-owned RLS table `public.sefirot_december_quest_saves` in project `kxqpwgwihtjmqlcxgfxp`.
- To test live cloud sync, log in with your own account via the site, back up local data, push and verify reload from another browser, then compare the journal. No assistant access to your password or tokens.
- Do not use or merge this branch to deploy the canonical SEFIROT model.
- Publicly served empty shell, PRIVATE per-user Supabase row.
- V3 master source available as single HTML. Script integrity and product function have only been checked locally; external hosting and user auth are not verified yet.

## Render

Render deployment attempt failed because workspace Hobby cap is 25 services. No Render service was changed and no paid upgrade was made.

## Checks

`node test.js` in local V3 source: 26 calculation assertions + lose/pending regression.
