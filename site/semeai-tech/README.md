# semeai.tech landing page

This folder contains a standalone static landing page for:

```text
https://semeai.tech
```

It is intentionally separate from the Gate demo:

```text
https://gate.semeai.tech
```

## Purpose

`semeai.tech` should be the public front door:

- SemeAI thesis;
- SemeAI Gate product link;
- SemeAI Local direction;
- Silence-as-Control governance context;
- research/publication links;
- author/developer attribution.

`gate.semeai.tech` should remain the live product demo.

## Research Links

The landing page includes clean public links:

```text
https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6613718
https://zenodo.org/records/20525820
```

Do not publish temporary Cloudflare challenge URLs with `__cf_chl_*`
parameters.

## Deploy Options

Use any static host:

- GitHub Pages from a separate `semeai-tech` repository;
- Netlify / Vercel static site;
- Namecheap static hosting;
- an Nginx/VPS static directory.

If using GitHub Pages with the apex domain, add:

```text
CNAME = semeai.tech
```

Then configure DNS according to the hosting provider.

## Boundary

This landing page does not run the gate, store customer data, or process
payments. It links to:

- `gate.semeai.tech` for demo;
- `api.semeai.tech` for API health;
- GitHub repositories;
- research/publication records.
