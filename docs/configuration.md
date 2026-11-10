# Configuration

CloneX works with no configuration. Settings change what a copy includes and how the interface behaves.

## Where settings come from

Highest priority first:

1. Command-line flags: `--lang`, `--source`, `--target`
2. `--set KEY=VALUE`, repeatable
3. The `CLONEX_LANG` environment variable
4. One settings file, the first of:
   - `--config PATH`, or the path in `CLONEX_CONFIG`
   - `clonex.toml` in the current folder
   - your per-user file
5. The defaults below

| Platform | Per-user file                                          |
| -------- | ------------------------------------------------------ |
| Windows  | `%APPDATA%\CloneX\config.toml`                         |
| macOS    | `~/Library/Application Support/CloneX/config.toml`     |
| Linux    | `$XDG_CONFIG_HOME/clonex/config.toml` (`~/.config/...`) |

```sh
clonex --init-config              # write a commented file to the per-user location
clonex --init-config clonex.toml  # or to a path you choose
clonex --show-config              # print the settings in effect and where they came from
```

Mistyped settings are reported rather than ignored. Account tokens can never be stored here: a file containing one is refused.

## Settings

| Setting        | Default                                   | Purpose                                          |
| -------------- | ----------------------------------------- | ------------------------------------------------ |
| `language`     | `"auto"`                                  | A [language code](languages.md), or your system's |
| `source`       | not set                                   | Source server ID; skips the prompt               |
| `target`       | not set                                   | Destination server ID; skips the prompt          |
| `audit_reason` | `"CloneX: user-confirmed structure copy"` | Shown in the destination's audit log, up to 512 characters |

### `[copy]`

Choose what is created in the destination.

| Setting                 | Default  | When turned off                                                                |
| ----------------------- | -------- | ------------------------------------------------------------------------------ |
| `roles`                 | `true`   | No roles are created. Overwrites that refer to them need your consent to drop  |
| `everyone_permissions`  | `true`   | The destination keeps its `@everyone` permissions                              |
| `categories`            | `true`   | Channels are created without a category                                        |
| `text_channels`         | `true`   | Text channels are left out                                                     |
| `voice_channels`        | `true`   | Voice channels are left out                                                    |
| `announcement_channels` | `"text"` | `"skip"` leaves them out instead of recreating them as text channels           |
| `permission_overwrites` | `true`   | Channels are created with no allow/deny rules, after you consent               |
| `server_name`           | `true`   | The destination keeps its name                                                 |
| `server_icon`           | `true`   | The destination keeps its icon, and the source icon is not downloaded          |

Leaving out channel types is not a warning, because you asked for it. Removing permission rules is different: it can make private channels visible, so `permission_overwrites = false` and `roles = false` still show what will be lost and ask for your consent during a copy.

### `[replace]`

Choose what is deleted from the destination first.

| Setting    | Default | When turned off                                                        |
| ---------- | ------- | ---------------------------------------------------------------------- |
| `channels` | `true`  | Existing channels stay, and Community servers become allowed           |
| `roles`    | `true`  | Existing roles stay and still count toward Discord's limit of 250      |

With both off, CloneX only adds to the destination and the confirmation says so. Names can then be duplicated, because Discord allows that.

### `[ui]`

| Setting      | Default  | Purpose                                                  |
| ------------ | -------- | -------------------------------------------------------- |
| `color`      | `"auto"` | `"always"` or `"never"`; `NO_COLOR` is also respected    |
| `max_listed` | `8`      | Items shown per adjustment list before "...and N more"   |

## Examples

Keep existing channels and add a copied set beside them:

```toml
[replace]
channels = false
roles = false
```

Copy only the channel layout, without roles or the server's name and icon:

```toml
[copy]
roles = false
everyone_permissions = false
permission_overwrites = false
server_name = false
server_icon = false
```

Change one thing for one run:

```sh
clonex --set copy.voice_channels=false --set ui.color=never
```
