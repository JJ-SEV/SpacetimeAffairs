# Caleb Flight Gate

Temporary deployment package for the Caleb Flight Gate review site.

Render uses `render.yaml` to create:

- a Docker web service named `calebflightgate`
- a 1GB persistent disk mounted at `/app/flight_record_site/data`
- the admin password `wuyixuan`

The persistent disk stores SQLite data, proof uploads, and generated PNG/PDF files.
