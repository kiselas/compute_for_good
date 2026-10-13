# Security policy

## Supported versions

ComputeForGood is an alpha. Security fixes are applied to current `main` and deployed
to the maintained service. Older alpha commits are not maintained release branches.

## Reporting a vulnerability

Use GitHub's private [Report a vulnerability](https://github.com/kiselas/compute_for_good/security/advisories/new)
form. Private vulnerability reporting was enabled and verified through the GitHub API
on 13 October 2026. The security owner is `@kiselas`.

Include the affected version or commit, a minimal synthetic reproduction, expected
behaviour, impact and any known workaround. Do not include real credentials, personal
data or unredacted production evidence. Report suspected authentication bypass,
cross-account disclosure, credential leaks, unsafe task authorization, evidence
tampering and deployment authorization failures privately.

The owner will acknowledge and triage complete reports as soon as practical. This is
not a guaranteed response or remediation deadline. Disclosure is coordinated with the
reporter after an applicable fix and release are verified. Do not open a public issue
with details of an undisclosed vulnerability or test other people's deployments
without their authorization.

## Trust boundaries

The platform coordinates contribution contracts, authorization and evidence. It does
not execute submitted project code or provide a sandbox for arbitrary code. Coding
and testing take place in participant-controlled environments. Acceptance of a PR
does not establish that every affected downstream installation has been updated.

Real HIGH and CRITICAL task dispatch is disabled while verified model attestation is
unavailable. A security report or a small patch does not override that policy. Task
risk is assessed separately from the severity of the reported vulnerability.
