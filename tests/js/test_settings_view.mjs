import assert from "node:assert/strict";
import test from "node:test";

import { readSettingsForm, renderSettingsView } from "../../static/js/settings-view.js";

test("renderSettingsView is a no-op when settings form is not mounted", () => {
    assert.doesNotThrow(() => {
        renderSettingsView(
            { settingsForm: null, settingsAlert: null },
            {
                config: { host: "127.0.0.1" },
                runtime: { host: "127.0.0.1", port: 28080 },
                restart_required: false,
                api_auth_enabled: false,
                callback_auth_enabled: false,
            },
            () => "",
        );
    });
});

test("readSettingsForm returns empty object without form", () => {
    assert.deepEqual(readSettingsForm({ settingsForm: null }), {});
});
