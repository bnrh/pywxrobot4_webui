---
name: write-webui-plugin
description: 'Create, scaffold, implement, refactor, or review Python plugins for this wxrobot web UI repository. Use when adding a plugin under plugins/, defining config_schema, handling text/notice/sysmsg events, using context.api/context.state/context.logger, or following existing patterns such as enter_room_tip and invite_to_room.'
argument-hint: 'What plugin should be created or changed?'
---

# Write WebUI Plugin

## When to Use
- Create a new Python plugin under plugins/.
- Refactor an existing plugin without breaking stored JSON config.
- Add or redesign config_schema entries for the plugin management UI.
- Implement message handling with handle_message, or lifecycle hooks such as startup, execute, tick, and on_hot_reload.
- Reuse repository-specific patterns for room selection, state storage, logging, and relative file paths.

## Procedure
1. Classify the plugin shape before editing.
   - Message-driven plugins usually declare event_filters and implement handle_message.
   - Lifecycle or job-style plugins might use startup, tick, execute, shutdown, or on_hot_reload instead.
2. Read the nearest existing example first.
   - Start with plugin_base.py and plugins/_plugin_sdk.py.
   - Then open one sibling plugin that matches the same message type, config shape, or API usage.
3. Design the smallest viable surface.
   - Required metadata is name and description.
   - Add event_filters only when the plugin reacts to incoming messages.
   - Prefer config_schema field types already used in this repo instead of inventing new frontend controls.
   - For one-click functional plugins declare direct_execute = True; for summary exporters also declare message_summary = True.
4. Implement with repository-native primitives.
   - Use context.api for wxrobot_api calls.
   - Use context.state or context.state.namespace(...) for persistent counters, caches, and deduplication.
   - Use context.logger for structured logs instead of print.
   - Normalize text, message types, XML, room scopes, SQL rows, and HTTP with helpers from plugins/_plugin_sdk.py when possible (async_http_get/post, extract_sql_rows, parse_int, etc.).
5. Preserve compatibility when changing existing plugins.
   - Keep aliases, legacy keys, or normalization fallbacks if historical config may already be stored in webui.sqlite3.
   - Prefer additive schema changes over breaking replacements.
6. Touch frontend code only when the schema cannot express the requirement.
   - First try to solve the UX through config_schema options already supported by the form renderer.
   - Only edit static/js/plugin-config-form.js or static/css/app.css when a new control or layout behavior is genuinely required.
7. Validate narrowly.
   - Run python -m py_compile on touched Python files.
   - Check editor diagnostics for the changed files.
   - If config_schema changed, confirm labels, defaults, uniqueness rules, and placeholders are internally consistent.
8. Finish with an operator-facing summary.
   - Explain what triggers the plugin, which config keys matter, whether old config is migrated, and any runtime assumptions.

## Decision Points
- Need durable plugin-local memory: use context.state and split concerns with namespace(...).
- Need group-specific rules: prefer object-list plus unique_by and searchable select fields that source room_options.
- Need relative image or file paths: resolve them from PROJECT_ROOT instead of assuming absolute paths.
- Need hot-reload warmup: pair startup with on_hot_reload instead of repeating initialization inside every message path.
- Need new UI behavior: verify the existing schema language cannot express it before modifying frontend assets.

## Completion Criteria
- The plugin lives in plugins/*.py and follows the repository's async plugin shape.
- Return values are structured and explain why a message was or was not handled.
- Logging is structured through context.logger.
- Persisted config remains readable, or the plugin includes a normalization path for legacy data.
- Focused validation passes for the touched files.

## Resources
- [Plugin workflow reference](./references/plugin-workflow.md)
- [Plugin template](./assets/plugin-template.py)