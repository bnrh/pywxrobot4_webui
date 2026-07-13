/** 仪表盘概览网格渲染。 */

import { el, replaceChildren, text } from "./dom-utils.js";
import { buildOverviewCards } from "./overview-cards.js";

export function renderOverviewGrid(elements, overview, overviewFetchedAt) {
    if (!overview) {
        return;
    }

    const cards = buildOverviewCards(overview, overviewFetchedAt);
    replaceChildren(
        elements.overviewGrid,
        ...cards.map((item) => el("article", { className: `overview-card tone-${item.tone || ""}` }, [
            el("div", { className: "overview-label" }, text(item.label)),
            el(
                "div",
                { className: `overview-value${item.valueClass ? ` ${item.valueClass}` : ""}` },
                text(item.value),
            ),
            el("div", { className: "overview-hint" }, text(item.hint)),
            item.body || null,
        ])),
    );
}
