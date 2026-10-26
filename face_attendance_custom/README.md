# Face Attendance Custom

This module adds face-attendance data, attendance routes and employee live maps.

## Missing map assets fix — 18.0.0.2

The backend manifest introduced in commit 51eed1f referenced local Leaflet and
Leaflet Routing Machine JS/CSS that were not committed. Odoo reported "Could not
get content" and failed backend style compilation. This release includes the
pinned library distributions, images and licenses under static/lib; see that
directory's README for provenance. No tracking, attendance or payroll rules change.

Deploy the complete module including static/lib to every Odoo worker, upgrade
face_attendance_custom and restart Odoo. Regenerate asset bundles using Odoo's
supported developer tools if the previous failed bundle remains, then hard-refresh
the browser. This module must be included alongside the HR/payroll modules when
transferring the new Face Attendance changes to another repository.

## Validation

- All nine backend asset paths and all local CSS image references resolve.
- Module installation/update completes in isolated raaviya_face_assets_test.
- Installed Chromium check: local JS/CSS/images return HTTP 200; compiled backend
  CSS includes Leaflet without missing-content errors; Leaflet 1.9.4 and Routing
  control are available; no Style error notification or browser exception.
- Install/runtime logs contain no WARNING or ERROR entries in these checks.

These checks address missing assets. They do not establish production deployment
or acceptance of live tracking, GPS accuracy or the routing provider.
