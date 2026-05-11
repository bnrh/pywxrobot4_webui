# Plugin Workflow Reference

This repository loads Python plugins directly from plugins/*.py and manages configuration from webui.sqlite3.

## Core Runtime Shape

- Metadata: name, description
- Common hook: async def handle_message(event, context)
- Optional hooks: startup, shutdown, execute, tick, on_hot_reload
- Message result pattern: return a dict like {"handled": bool, "detail": "...", "data": {...}}

## Repository-Native Capabilities

- context.api: wrapped wxrobot_api client for send_text, send_image, room members, downloads, and other platform calls
- context.logger: structured logger with debug, info, warning, error, and scope(name)
- context.state: SQLite-backed persistent store for counters, caches, and deduplication
- context.hot_reload: metadata about file reload status

## Common Design Rules

1. Normalize inbound values early.
   - Prefer helpers from plugins/_plugin_sdk.py such as normalize_text, get_message_type, to_string_list, unique_strings, and XML helpers.
2. Keep plugin logic asynchronous.
   - Await context.api calls and SDK helpers like sleep.
3. Preserve stored config.
   - If a plugin already has live users, keep aliases, legacy keys, or normalization shims instead of hard-cutting old shapes.
4. Keep operator UX in config_schema whenever possible.
   - The plugin management UI is schema-driven.
   - Common fields already supported in this repo include text, textarea, number, boolean, select, and object-list with display_mode="table".
5. Avoid unnecessary frontend edits.
   - Only change static/js/plugin-config-form.js or static/css/app.css when the schema language truly cannot express the requirement.

## Config Schema Patterns Worth Reusing

### Group-scoped rule table

Use an object-list table when the operator manages multiple rules keyed by roomid, keyword, or similar identifiers.

Important table options seen in this repo:

- meaningful_keys
- require_one_of / require_one_of_message
- unique_by / unique_message
- empty_text
- columns with searchable select fields and options_source

### Searchable room selector

For room-specific rules, use a select column with:

- searchable: True
- options_source: room_options
- placeholder that allows searching by group name or wxid

### Relative file picker

For image or file paths, prefer:

- file_picker
- accept
- upload_dir
- placeholder that states the path can be relative to the project root

## Validation Checklist

- Python syntax check passes: python -m py_compile on the touched files
- No editor diagnostics remain in the changed files
- Config defaults, required flags, uniqueness rules, and descriptions agree with runtime logic
- Existing config data remains readable if the plugin is being evolved rather than created from scratch

## Practical Editing Sequence

1. Open plugin_base.py and plugins/_plugin_sdk.py.
2. Open one sibling plugin closest to the requested behavior.
3. Draft the plugin file or the minimal plugin diff.
4. Add config_schema only for operator-facing inputs.
5. Add normalization or migration logic if the plugin already existed.
6. Run focused validation.
7. Summarize trigger conditions, config keys, and compatibility notes.
