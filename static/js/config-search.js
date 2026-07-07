/** 插件配置表单中的可搜索选择与作用域联动。 */

export function normalizeChoiceSearchText(value) {
    return String(value ?? "").replace(/\s+/g, " ").trim().toLowerCase();
}

export function normalizeScopeModeValue(value) {
    const normalized = String(value ?? "").trim();
    return normalized.replace(/^"|"$/g, "");
}

export function applySearchableChoiceFilter(input) {
    const fieldContainer = input?.closest("[data-config-field]");
    if (!fieldContainer) {
        return;
    }
    const query = normalizeChoiceSearchText(input.value);
    const showSelectedInput = fieldContainer.querySelector("[data-config-show-selected]");
    const showSelectedOnly = Boolean(showSelectedInput?.checked);
    const choiceItems = [...fieldContainer.querySelectorAll("[data-config-choice-item]")];
    let visibleCount = 0;
    for (const item of choiceItems) {
        const searchText = normalizeChoiceSearchText(item.dataset.searchText || item.textContent || "");
        const checkedInput = item.querySelector('input[type="checkbox"][data-config-key]');
        const checkedMatched = !showSelectedOnly || Boolean(checkedInput?.checked);
        const matched = (!query || searchText.includes(query)) && checkedMatched;
        item.hidden = !matched;
        item.style.display = matched ? "" : "none";
        if (matched) {
            visibleCount += 1;
        }
    }
    const emptyState = fieldContainer.querySelector("[data-config-search-empty]");
    if (emptyState) {
        emptyState.hidden = visibleCount > 0;
    }
}

export function initializeSearchableChoiceFilters(container) {
    if (!container) {
        return;
    }
    container.querySelectorAll("[data-config-search-input]").forEach((input) => {
        applySearchableChoiceFilter(input);
    });
}

export function getSearchableSelectElements(container) {
    return {
        input: container?.querySelector("[data-config-searchable-input]"),
        hiddenInput: container?.querySelector("[data-config-searchable-value]"),
        menu: container?.querySelector("[data-config-searchable-menu]"),
        emptyState: container?.querySelector("[data-config-searchable-empty]"),
        options: container ? [...container.querySelectorAll("[data-config-searchable-option]")] : [],
    };
}

export function getSearchableSelectOptionLabel(optionButton) {
    return String(
        optionButton?.dataset.optionLabel
        || optionButton?.querySelector(".config-searchable-select-option-title")?.textContent
        || ""
    ).trim();
}

export function getSelectedSearchableSelectOption(container) {
    const { hiddenInput, options } = getSearchableSelectElements(container);
    if (!hiddenInput?.value) {
        return null;
    }
    return options.find((option) => option.dataset.optionValue === hiddenInput.value) || null;
}

export function syncSearchableSelectSelection(container) {
    const selectedOption = getSelectedSearchableSelectOption(container);
    const { options } = getSearchableSelectElements(container);
    for (const option of options) {
        option.classList.toggle("is-selected", option === selectedOption);
    }
}

export function applySearchableSelectFilter(input) {
    const container = input?.closest("[data-config-searchable-select]");
    if (!container) {
        return;
    }
    const { menu, emptyState, options } = getSearchableSelectElements(container);
    const query = normalizeChoiceSearchText(input.value);
    let visibleCount = 0;
    for (const option of options) {
        const searchText = normalizeChoiceSearchText(option.dataset.searchText || option.textContent || "");
        const matched = !query || searchText.includes(query);
        option.hidden = !matched;
        option.style.display = matched ? "" : "none";
        if (matched) {
            visibleCount += 1;
        }
    }
    if (emptyState) {
        emptyState.hidden = visibleCount > 0;
    }
    if (menu) {
        menu.hidden = false;
    }
    container.classList.add("is-open");
}

export function closeSearchableSelect(container, restoreDisplay = false) {
    if (!container) {
        return;
    }
    const { input, menu } = getSearchableSelectElements(container);
    const selectedOption = getSelectedSearchableSelectOption(container);
    if (restoreDisplay && input) {
        input.value = selectedOption ? getSearchableSelectOptionLabel(selectedOption) : "";
    }
    if (menu) {
        menu.hidden = true;
    }
    container.classList.remove("is-open");
}

export function clearSearchableSelectSelection(container) {
    const { hiddenInput } = getSearchableSelectElements(container);
    if (hiddenInput) {
        hiddenInput.value = "";
    }
    syncSearchableSelectSelection(container);
}

export function handleSearchableSelectInput(input) {
    const container = input?.closest("[data-config-searchable-select]");
    if (!container) {
        return;
    }
    const selectedOption = getSelectedSearchableSelectOption(container);
    if (selectedOption) {
        const query = normalizeChoiceSearchText(input.value);
        const selectedLabel = normalizeChoiceSearchText(getSearchableSelectOptionLabel(selectedOption));
        const selectedRawValue = normalizeChoiceSearchText(selectedOption.dataset.optionRawValue || "");
        if (query && query !== selectedLabel && query !== selectedRawValue) {
            clearSearchableSelectSelection(container);
        }
    }
    applySearchableSelectFilter(input);
}

export function selectSearchableSelectOption(optionButton) {
    const container = optionButton?.closest("[data-config-searchable-select]");
    if (!container) {
        return;
    }
    const { input, hiddenInput } = getSearchableSelectElements(container);
    if (hiddenInput) {
        hiddenInput.value = optionButton.dataset.optionValue || "";
    }
    if (input) {
        input.value = getSearchableSelectOptionLabel(optionButton);
        input.dispatchEvent(new Event("input", { bubbles: true }));
    }
    syncSearchableSelectSelection(container);
    closeSearchableSelect(container, false);
    hiddenInput?.dispatchEvent(new Event("change", { bubbles: true }));
}

export function syncScopeFieldVisibility(container) {
    if (!container) {
        return;
    }

    const rules = [
        ["_scope_room_mode", "_scope_room_ids"],
        ["_scope_friend_mode", "_scope_friend_labels"],
    ];

    for (const [controllerKey, targetKey] of rules) {
        const controller = container.querySelector(`[data-config-key="${controllerKey}"]`);
        const target = container.querySelector(`[data-config-field="${targetKey}"]`);
        if (!controller || !target) {
            continue;
        }
        const shouldShow = normalizeScopeModeValue(controller.value) === "selected";
        target.hidden = !shouldShow;
        target.style.display = shouldShow ? "" : "none";
        if (shouldShow) {
            initializeSearchableChoiceFilters(target);
        }
    }
}
