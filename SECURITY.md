# Security policy

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting feature for this repository when available. If it is unavailable, open a minimal public issue that asks maintainers for a private reporting channel; do not include exploit details, personal data, logs containing secrets, or device identifiers that you consider sensitive.

## Scope and safety

- The application creates a virtual game controller and reads keyboard/HID input.
- ViGEmBus is a separate system driver and is not installed silently by this project.
- Do not run untrusted provider DLLs or SDK plugins. Obtain them from their official publisher and review their licensing.
- Diagnostic bundles should exclude credentials, personal documents, and unrelated process details.
- Please include the application version, Windows version, keyboard model/firmware, provider and a minimal reproduction when reporting a bug.

Security reports are reviewed on a best-effort basis. Do not assume that a public repository or CI build has undergone a formal security audit.
