import { redirect } from "next/navigation";

import { ADOPTION_OVERVIEW_ROUTE } from "@/lib/routes";

/**
 * `/` has no design of its own — no mockup in `docs/design/mockups/` covers a
 * root landing screen, so this route invents no UI. It forwards to the
 * Adoption Overview, which is the application's home surface and already the
 * target `BackToProgramBoard` sends users to.
 *
 * That route 404s until the OVW epic ships; `@/lib/routes` records this as
 * accepted and visible rather than a defect, and `OVW-01` flips the single
 * `ADOPTION_OVERVIEW_ROUTE` constant when it lands. This replaced the
 * `create-next-app` scaffold page, which shipped Next.js/Vercel marketing
 * links as the product's front door.
 */
export default function Home() {
  redirect(ADOPTION_OVERVIEW_ROUTE);
}
