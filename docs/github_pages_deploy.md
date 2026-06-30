# GitHub Pages Deployment

This repo can publish the static SemeAI Gate demo through GitHub Pages.

The public entrypoint is:

```text
index.html
```

It redirects to:

```text
demo/saas_visible.html
```

## Recommended URL

```text
gate.semeai.tech
```

This keeps the root domain available for the broader SemeAI site and leaves
`app.semeai.tech` available for a future authenticated SaaS surface.

## GitHub Settings

In the GitHub repository:

1. Open `Settings`.
2. Open `Pages`.
3. Set source to `GitHub Actions`.
4. Set custom domain to:

```text
gate.semeai.tech
```

Do this after the DNS record below has been added. The first deployment can run
on the default GitHub Pages URL before the custom domain is attached.

## Namecheap DNS

In Namecheap:

1. Open `Domain List`.
2. Select `semeai.tech`.
3. Open `Advanced DNS`.
4. Add a host record:

```text
Type: CNAME
Host: gate
Value: SemeAIPletinnya.github.io
TTL: Automatic
```

Wait for DNS propagation, then enable HTTPS in GitHub Pages when available.

If you want the repository to enforce the custom domain from the deployment
artifact later, add a root `CNAME` file containing:

```text
gate.semeai.tech
```

## Scope Boundary

This hosted page is a static demo, not the production SaaS backend.

It does not add:

- cloud AI calls;
- external LLM APIs;
- backend storage;
- auth;
- billing;
- customer data storage.

The canonical machine values remain unchanged:

```text
SHOW   = PROCEED
REVIEW = NEEDS_REVIEW
BLOCK  = SILENCE
```

`SILENCE` means release denied, execution withheld, and audit preserved.
