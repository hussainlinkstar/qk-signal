/**
 * What content looks like inside a report section (SIGV2-1317).
 *
 * The expandable section is already the card: `ReportDisclosure` draws the
 * border, the radius and the panel background, on the approved Scan history
 * anatomy from `Signal Overview.html`. Anything inside it is therefore a
 * block, not another card.
 *
 * Every tab used to open with its own
 * `rounded-[22px] border-0 bg-white`, which put a card
 * inside a card inside a section. Fifty of those wrappers across eight
 * components, and the page was reported for exactly that.
 *
 * Blocks separate the approved way, with `.st`, which is
 * `border-top: 1px solid var(--line-2)` and nothing else. A rule between two
 * things reads as a division; a border all the way round reads as a new
 * object, and there is only one object here.
 */

/** A block inside a section. No border, no background, no radius. */
export const REPORT_BLOCK = "min-w-0";

/**
 * A block that follows another one. The rule and the spacing come from the
 * approved `.st`, so a section of four blocks has three rules and no boxes.
 */
export const REPORT_BLOCK_DIVIDED = "min-w-0 border-t border-t-(--line-2) pt-4 mt-4";

/**
 * A nested detail inside a block, where one genuinely is needed: a tinted
 * well rather than a card, so it reads as part of its parent instead of as a
 * sibling of it. Used sparingly, and never for a whole section.
 */
export const REPORT_WELL = "rounded-[10px] bg-(--line-2) px-[14px] py-3";
