/**
 * Route constants (D-02).
 *
 * `ADOPTION_OVERVIEW_ROUTE` is the single place the Adoption Overview
 * route target lives — every consumer imports it rather than hardcoding
 * `/overview`. The Adoption Overview page (OVW epic) has not shipped yet,
 * so this route 404s today; that is accepted and visible, not a defect.
 * OVW-01 flips this one constant to the real route when it ships.
 */
export const ADOPTION_OVERVIEW_ROUTE = "/overview";
