# Security Policy

SemeAI Gate Basic is an early local release-control prototype.

## Reporting

For now, report security issues privately to the project owner before public
disclosure. A dedicated security contact should be added before a public launch.

## Current Security Boundary

- The default package is local-only.
- It does not call cloud APIs.
- It does not send telemetry.
- It does not run an LLM.
- It does not store raw prompt or AI answer text in receipts by default.

## Not Yet Provided

This basic repo does not yet provide:

- hosted API security;
- authentication;
- tenant isolation;
- SOC2 or compliance certification;
- cryptographic receipt signing;
- production SLA.

## Important Invariant

`SILENCE` means release denied / execution withheld / audit preserved. Security
fixes must not collapse blocked output into deletion without audit evidence.
