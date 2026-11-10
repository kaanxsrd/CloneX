# Languages

CloneX ships 42 languages: every language Discord's own client offers, plus other widely spoken ones. English is the source text, and the others started as machine translations that no native speaker has reviewed yet. [Corrections are welcome](../CONTRIBUTING.md#translations).

## Choosing a language

Highest priority first:

1. `--lang CODE`
2. `--set language=CODE`
3. The `CLONEX_LANG` environment variable
4. `language = "CODE"` in your [settings file](configuration.md)
5. Your system language, read from `LANGUAGE`, `LC_ALL`, `LC_MESSAGES` or `LANG`, then from the Windows or macOS language setting
6. English

Regional codes find the closest match, so `pt_BR.UTF-8` selects `pt-BR`, `es_MX` selects `es-419`, and `zh-Hant` selects `zh-TW`. Run `clonex --list-languages` to see what is available.

Where a yes or no is asked, the language's own words work, and English `y` and `n` always do too. Server IDs and menu choices can be typed in the digits of any script.

| Code     | Language                | In English              |
| -------- | ----------------------- | ----------------------- |
| `ar`     | العربية                 | Arabic                  |
| `bg`     | Български               | Bulgarian               |
| `bn`     | বাংলা                   | Bengali                 |
| `cs`     | Čeština                 | Czech                   |
| `da`     | Dansk                   | Danish                  |
| `de`     | Deutsch                 | German                  |
| `el`     | Ελληνικά                | Greek                   |
| `en`     | English                 | English                 |
| `es`     | Español                 | Spanish                 |
| `es-419` | Español (Latinoamérica) | Spanish (Latin America) |
| `fa`     | فارسی                   | Persian                 |
| `fi`     | Suomi                   | Finnish                 |
| `fil`    | Filipino                | Filipino                |
| `fr`     | Français                | French                  |
| `he`     | עברית                   | Hebrew                  |
| `hi`     | हिन्दी                  | Hindi                   |
| `hr`     | Hrvatski                | Croatian                |
| `hu`     | Magyar                  | Hungarian               |
| `id`     | Bahasa Indonesia        | Indonesian              |
| `it`     | Italiano                | Italian                 |
| `ja`     | 日本語                     | Japanese                |
| `ko`     | 한국어                     | Korean                  |
| `lt`     | Lietuvių                | Lithuanian              |
| `mr`     | मराठी                   | Marathi                 |
| `ms`     | Bahasa Melayu           | Malay                   |
| `nl`     | Nederlands              | Dutch                   |
| `no`     | Norsk bokmål            | Norwegian Bokmål        |
| `pl`     | Polski                  | Polish                  |
| `pt`     | Português (Portugal)    | Portuguese (Portugal)   |
| `pt-BR`  | Português (Brasil)      | Portuguese (Brazil)     |
| `ro`     | Română                  | Romanian                |
| `ru`     | Русский                 | Russian                 |
| `sv`     | Svenska                 | Swedish                 |
| `ta`     | தமிழ்                   | Tamil                   |
| `te`     | తెలుగు                  | Telugu                  |
| `th`     | ไทย                     | Thai                    |
| `tr`     | Türkçe                  | Turkish                 |
| `uk`     | Українська              | Ukrainian               |
| `ur`     | اردو                    | Urdu                    |
| `vi`     | Tiếng Việt              | Vietnamese              |
| `zh-CN`  | 简体中文                    | Simplified Chinese      |
| `zh-TW`  | 繁體中文                    | Traditional Chinese     |

## Adding or correcting a language

Any language can be added without rebuilding CloneX:

1. Find your settings folder: `%APPDATA%\CloneX` on Windows, `~/Library/Application Support/CloneX` on macOS, or `~/.config/clonex` on Linux.
2. Copy [`en.json`](../clonex/locales/en.json) to `locales/<code>.json` inside it.
3. Translate the values, keep every `{placeholder}`, and set `_meta` to the language's name.
4. Run `clonex --lang <code> --demo`.

A file there overrides a shipped language of the same code. Any key you leave out falls back to English, so a partial translation is safe. To share one with everyone, open a pull request adding it to `clonex/locales/`.

## Terminal display

CloneX sends correct Unicode text, and how it looks depends on your terminal and font. Right-to-left languages (Arabic, Hebrew, Persian and Urdu) can appear reversed in terminals without bidirectional text support, and some South Asian scripts can look misaligned in panel borders. If so, try a different terminal or font, or use `--lang en`.
