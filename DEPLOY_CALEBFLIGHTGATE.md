# Caleb Flight Gate Deployment Notes

`calebflightgate.pages.dev` looks unclaimed by DNS, but Cloudflare Pages can only be reserved from a Cloudflare account.

## Important

The current app is a Python web app. It uses:

- SQLite for submissions
- file uploads for proof images/PDFs
- Pillow to generate final PNG/PDF records

Cloudflare Pages cannot run this Python server directly. Use one of these paths:

## Path A: fastest stable deployment

Deploy this Docker app to Render, then use the platform's fixed URL.

Recommended service name:

```text
calebflightgate
```

The repo includes `render.yaml`, which defines:

- Docker runtime
- Starter plan
- Singapore region
- `FLIGHT_RECORD_ADMIN_PASSWORD=wuyixuan`
- generated admin cookie secret
- 1GB persistent disk mounted at `/app/flight_record_site/data`

That disk stores:

- `flight_record.sqlite3`
- uploaded proof files
- generated `calebflightrecord-xxxx.png`
- generated `calebflightrecord-xxxx.pdf`

If setting it up manually instead of using the blueprint, set environment variables:

```text
FLIGHT_RECORD_ADMIN_PASSWORD=wuyixuan
FLIGHT_RECORD_ADMIN_SECRET=<a long random secret>
FLIGHT_RECORD_AMAP_KEY=<optional Gaode/Amap key>
```

And add a persistent disk:

```text
Name: flight-record-data
Mount path: /app/flight_record_site/data
Size: 1 GB
```

The Dockerfile already:

- listens on the platform `PORT`
- installs Chinese-capable Noto CJK fonts
- copies only the flight-record app, renderer, static assets, and signature asset

## Path B: keep `calebflightgate.pages.dev`

Use Cloudflare Pages for the public domain/front door and put the Python app behind it on Koyeb/Render.

Later, we can either:

- make `calebflightgate.pages.dev` redirect/proxy to the backend URL, or
- rebuild the backend as Cloudflare Workers + D1/R2 + client-side PNG/PDF export.

The second option is cleaner but is a real migration, not a quick deploy.

## Cloudflare Pages name to reserve

Project name:

```text
calebflightgate
```

Expected Pages URL:

```text
https://calebflightgate.pages.dev
```

Temporary placeholder:

```text
cloudflare_pages_placeholder/
```

Use Cloudflare Pages "Direct Upload" with this folder if you want to reserve the name before the Python backend is deployed.
