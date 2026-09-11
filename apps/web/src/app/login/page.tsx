import { redirect } from "next/navigation";

import { ADOPTION_OVERVIEW_ROUTE } from "@/lib/routes";
import { readSession } from "@/lib/tokenStore";

import styles from "./page.module.css";

/**
 * `/login` (OVW-05, T-11) — branded sign-in page + already-authenticated
 * pass-through (AC-16/17/18/19, DESIGN.md § Recorded deviation B).
 *
 * Server Component. `readSession()` (`@/lib/tokenStore`, the same helper
 * `GET /logout` already calls) runs first, before any markup: a valid
 * session redirects to `ADOPTION_OVERVIEW_ROUTE` (AC-18) — there is no
 * visual state for that path, no spinner, no "redirecting…" copy
 * (DESIGN.md deviation B). `redirect()` throws its own `NEXT_REDIRECT`
 * control-flow signal — see `apps/web/src/app/overview/page.tsx`'s
 * docstring for the same hazard — so it is never wrapped in a try/catch
 * that could swallow it.
 *
 * Otherwise renders the branded card: logo tile + "AgentRise Harness" +
 * "AI SDLC Governance" (byte-exact from the shipped brand bar geometry,
 * `PersonaDashboardShell.module.css`'s `.logoTile`/`.logoInner`, reproduced
 * here rather than composing that component — DESIGN.md deviation B
 * explicitly rejects rendering `PersonaDashboardShell` on this pre-auth
 * page: it has no `persona`, so the shell would mount straight into its
 * `isLoading` branch, coupling the sign-in screen to the identity gate for
 * no visual gain) — plus a single zero-JS SSO sign-in form targeting
 * `/login/start` (AC-17), the relocated OAuth relay (T-10).
 */
export default async function Page() {
  const session = await readSession();
  if (session !== null) {
    redirect(ADOPTION_OVERVIEW_ROUTE);
  }

  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <div className={styles.brand}>
          <div className={styles.logoTile}>
            <div className={styles.logoInner} />
          </div>
          <div className={styles.brandText}>
            <div className={styles.productName}>AgentRise Harness</div>
            <div className={styles.tagline}>AI SDLC Governance</div>
          </div>
        </div>
        <form className={styles.form} action="/login/start" method="get">
          <button type="submit" className={styles.ssoButton}>
            Sign in with SSO
          </button>
        </form>
      </div>
    </div>
  );
}
