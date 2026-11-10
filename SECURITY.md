# Security policy

CloneX handles Discord account tokens and can delete server data. We take reports seriously.

## Reporting a vulnerability

Please **do not open a public issue**. Report privately through GitHub's [private vulnerability reporting](https://github.com/kaanxsrd/CloneX/security/advisories/new) for this repository.

Include:

- what is affected (module or command, and version or commit),
- steps to reproduce or a proof of concept, using sanitized or synthetic data,
- the impact you expect.

Never include real tokens or private server data.

## What to expect

- Acknowledgement within 3 business days.
- An assessment and a planned fix date within 10 business days.
- Credit in the advisory and changelog when the fix ships, unless you prefer to stay anonymous.

Please give us a reasonable time to fix the issue before disclosing it publicly.

## Scope

In scope: this repository's code and its release builds.
Out of scope: Discord itself, account actions Discord takes against automated accounts, and findings that need a compromised machine or account.

## Verifying a download

Release builds are made by this repository's release workflow from the tagged source, and each release includes `checksums.txt`. Only run a file whose hash matches: a modified build could steal the token you give it.

## Credential exposure

Treat an account token as a password. If one is exposed, secure your Discord account and revoke its sessions. Removing it from a file does not remove it from existing commits, forks, logs or screenshots.

CloneX reads tokens through hidden input or `DISCORD_USER_TOKEN`, keeps them in memory only, and refuses settings files that contain one.

## Operational safety

A copy can delete destination channels, message history and editable roles, and it is not transactional, so a failure can leave partial changes. Treat copied role and channel permissions as security-sensitive configuration, and review them before inviting anyone.
