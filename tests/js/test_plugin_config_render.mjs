import {
    getPluginModuleNameForForm,
    getWxpidFieldOptions,
    hydrateDynamicFieldOptions,
    resolveTargetOptionsBySource,
} from "../../static/js/plugin-config-render.js";
import { WXPID_OPTION_ALL, WXPID_OPTION_DEFAULT } from "../../static/js/plugin-helpers.js";

const elements = {
    pluginConfigForm: { id: "pluginConfigForm" },
    pluginExecuteForm: { id: "pluginExecuteForm" },
};

const moduleState = {
    pluginConfigModule: "demo_plugin",
    pluginExecuteModule: "feature_plugin",
};

if (getPluginModuleNameForForm(elements.pluginConfigForm, elements, moduleState) !== "demo_plugin") {
    throw new Error("config form module name mismatch");
}
if (getPluginModuleNameForForm(elements.pluginExecuteForm, elements, moduleState) !== "feature_plugin") {
    throw new Error("execute form module name mismatch");
}

const pluginTargets = {
    room_options: [{ label: "群 A", value: "room-a" }],
    label_options: [{ label: "标签 1", value: "tag-1" }],
    wxpid_options: [{ label: "进程 1", value: 1001 }],
};

const roomOptions = resolveTargetOptionsBySource("room_options", ["room-b"], {}, pluginTargets);
if (!roomOptions.some((item) => item.value === "room-a") || !roomOptions.some((item) => item.value === "room-b")) {
    throw new Error("room options should merge current values with targets");
}

const labelOptions = resolveTargetOptionsBySource("label_options", [], {}, pluginTargets);
if (labelOptions.length !== 1 || labelOptions[0].value !== "tag-1") {
    throw new Error("label options should come from plugin targets");
}

const wxpidOptions = getWxpidFieldOptions(1001, pluginTargets, null);
const wxpidValues = wxpidOptions.map((item) => String(item.value));
for (const expected of [WXPID_OPTION_DEFAULT, WXPID_OPTION_ALL, "1001"]) {
    if (!wxpidValues.includes(expected)) {
        throw new Error(`missing wxpid option: ${expected}`);
    }
}

const hydrated = hydrateDynamicFieldOptions(
    { key: "rooms", options_source: "room_options" },
    ["room-b"],
    {},
    pluginTargets,
);
if (!hydrated.options.some((item) => item.value === "room-a")) {
    throw new Error("hydrated field should resolve room options");
}

console.log("plugin-config-render ok");
