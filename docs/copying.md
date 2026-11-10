# Copying a server

How a copy behaves from start to finish. For every option that changes this, see [configuration](configuration.md).

## Before you start

1. Use your own Discord account, with membership in both servers.
2. The **source** requires membership only, not Administrator or Manage Server. CloneX uses every channel and category Discord supplies and all ordinary source roles, including roles you do not hold. Hidden channels are included when Discord supplies their metadata.
3. The **destination** requires Administrator or ownership, because its structure is modified.
4. If you own the destination, no separate access role is needed. Otherwise your highest role must grant Administrator and sit above every other ordinary role. CloneX keeps that role while replacing the others.
5. The destination must have Community disabled, unless [`replace.channels`](configuration.md#replace) is off.
6. Enable Developer Mode in Discord and use **Copy Server ID** for both servers.

Use servers you own or are authorized to manage. Channel metadata and channel contents are separate: copying a hidden channel's structure does not read its messages or grant access in the source. If Discord omits or redacts metadata, it cannot be reconstructed. See Discord's [channel obfuscation announcement](https://docs.discord.com/developers/change-log#channel-obfuscation-for-users-and-bots).

## What gets copied

| Item                  | Behavior                                                                                                                                                       |
| --------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Server identity       | Copies the name and icon; uses a static PNG if animated icons are unavailable; clears the icon if the source has none                                          |
| Roles                 | Copies names, permissions, primary colors, hoist, mentionability and relative order                                                                            |
| Default role          | Copies `@everyone` permissions                                                                                                                                 |
| Categories            | Copies names, order and permission overwrites                                                                                                                  |
| Text channels         | Copies names, categories, order, topics, NSFW flags, slowmode and thread defaults                                                                              |
| Announcement channels | Creates standard text channels with the same name, category, order, topic, permissions and compatible text settings; publishing and following are not copied   |
| Voice channels        | Copies names, categories, order, NSFW flags, slowmode, user limits, region, video quality and bitrate within destination limits                                |
| Other channel types   | Skips forum, media, stage and unrecognized types; lists omissions in the preview and the completion summary                                                    |
| Permission overwrites | Maps roles by ID; copies individual overwrites for destination members and reports skipped overwrites for absent members                                       |
| Managed roles         | Keeps destination bot and integration roles; does not copy source managed roles                                                                                |
| Account access role   | If you do not own the destination, keeps your highest Administrator role                                                                                       |

Messages, threads, members, member role assignments, emojis, stickers, webhooks, invites, bans, integrations, role icons and gradients, and other server settings are **not copied**. This is a structure copier, not a backup or a continuous sync.

**Role names** are checked first. Empty or invisible-only names become `Role <source ID>`, control characters and outer whitespace are removed, and names over 100 characters are shortened. If Discord still rejects only a name's length, that role is retried once with `Role <source ID>`. Permissions and ID-based mappings are preserved either way.

**Overwrites for managed or missing roles** are recoverable. CloneX explains which role and how many channels are affected and asks whether to continue. Accepting skips those overwrites and keeps every other mapping. The decision covers that role across the copy.

**Absent members** only lose their own channel overwrites; the channels and remaining permissions are still copied. If that person joins later, review their permissions.

## Preview, then copy

A preview checks prerequisites, resolves member overwrites, reads the source icon and shows the planned deletions and creations. **It makes no server changes**, but still needs a valid token and a connection.

A copy shows the same plan, then asks you to type the **destination server ID**. Any other response cancels. Keep both servers unchanged while it runs.

Started without arguments, CloneX offers a menu:

- **1. Preview only** checks the servers and shows the plan.
- **2. Copy** shows the plan and asks for the destination server ID.
- **3. Exit** closes the program without connecting.

## Options

| Option                       | Purpose                                                          |
| ---------------------------- | ---------------------------------------------------------------- |
| `--source ID`, `--target ID` | Server IDs; prompted if missing                                  |
| `--apply`                    | Copy after an interactive confirmation; without it, only preview |
| `--demo`                     | Show the interface offline with sample data                      |
| `--check`                    | Verify the installation and print versions, without connecting   |
| `--lang CODE`                | Interface language                                               |
| `--config PATH`              | Use this settings file                                           |
| `--set KEY=VALUE`            | Override one setting; repeatable                                 |
| `--init-config [PATH]`       | Write a commented settings file                                  |
| `--show-config`              | Print the settings in effect                                     |
| `--list-languages`           | List the available languages                                     |
| `--version`                  | Print the version                                                |

## Recoverable failures

If Discord rejects an individual request, a recovery panel shows the operation, item, rejected fields and the effect of continuing. Each failure needs its own decision, and Enter means no.

| Failure                                            | Effect of choosing to continue                                                                   |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| Delete a destination role or channel               | Leave that item in place; old permissions and duplicate names may remain                         |
| Create a role or copy its permissions              | Skip the role and its channel overwrites; copy the remaining roles                               |
| Update `@everyone`                                 | Keep the destination's existing default permissions                                              |
| Create a category, or a category is missing        | Create its children without a category, with their own available overwrites                      |
| Create a text or voice channel, or copy overwrites | Skip that channel; continue with the others                                                      |
| Set a voice channel's slowmode                     | Leave slowmode off for that channel                                                              |
| Restore role, channel or category order            | Keep the order the items were created in; ordering is one decision per kind of channel           |
| Read the source icon                               | Keep the destination icon; still copy the name and structure                                     |
| Update the server name or icon                     | Keep the copied structure and omit the rejected update                                           |
| Resolve a member's overwrites                      | Skip that member's overwrites, with a warning that their access may differ                       |
| Exceed role capacity during preparation            | Copy the roles that fit, in source hierarchy order; list and skip the rest and their overwrites  |

Permissions are never silently stripped from a rejected request. Progress distinguishes `SKIP` from `DONE`, and the final panel says **COPY FINISHED WITH WARNINGS** and lists every omission.

Invalid server selection, missing access, unsafe role hierarchy, authentication failures, lost server access, exhausted rate limits, server failures, uncertain writes and unexpected errors always stop the operation. These are not retried or treated as success. A repeated READY event cannot run the copy twice.

## Exit codes

| Code  | Meaning                                                                       |
| ----- | ----------------------------------------------------------------------------- |
| `0`   | Preview completed, or copy completed without omissions                        |
| `1`   | Validation, authentication, connection or copy failed                         |
| `2`   | Invalid arguments, confirmation did not match, or a recovery was declined     |
| `3`   | Copy finished with omissions; review the final report                         |
| `130` | Interrupted, or interactive input ended                                       |

A failed operation may leave a partially modified destination. Review it before retrying.

## Your token

- Enter your account token at the hidden prompt, or provide `DISCORD_USER_TOKEN` through your environment or a secret manager.
- CloneX never writes the token to a file and has no token argument. Settings files that contain one are refused.
- Hidden input must be available; CloneX refuses a fallback that would echo the token.
- Never paste tokens into source code, issues, screenshots or shell commands saved to history.
- Treat a token as a password. If exposed, secure your account and revoke its sessions in Discord's settings.
