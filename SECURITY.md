# Security Policy

## Reporting a vulnerability

Please do not open public issues for security problems.

Report privately via [GitHub Security Advisories](https://github.com/VishiATChoudhary/theorem/security/advisories/new) or email vishisht.choudhary@tum.de with "theorem security" in the subject.

You will get an acknowledgment within 72 hours. Fixes for confirmed issues ship in a patch release with credit to the reporter (unless you prefer anonymity).

## Scope

theorem runs as a single-process engine over local files. Reports of most interest: sandbox escapes through query text, path traversal via db paths, crashes exploitable through crafted `.thm` programs or crafted WAL/snapshot files.
