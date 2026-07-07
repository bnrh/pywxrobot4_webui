/** 仪表盘概览网格渲染。 */

import { escapeHtml } from "./dom-utils.js";
import { buildOverviewCards } from "./overview-cards.js";

export function renderOverviewGrid(elements, overview, overviewFetchedAt) {
    if (!overview) {
        return;
    }

    const cards = buildOverviewCards(overview, overviewFetchedAt);
    elements.overviewGrid.innerHTML = cards.map((item) => `
        <article class="overview-card tone-${escapeHtml(item.tone)}">
            <div class="overview-label">${escapeHtml(item.label)}</div>
            <div class="overview-value${item.valueClass ? ` ${item.valueClass}` : ""}">${escapeHtml(item.value)}</div>
            <div class="overview-hint">${escapeHtml(item.hint)}</div>
            ${item.body || ""}
        </article>
    `).join("");
}
