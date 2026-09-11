import { describe, expect, it } from "vitest";

import { composeSignedInUser } from "@/lib/composeSignedInUser";
import type { MeData } from "@/types/me";

/**
 * OVW-05-TC-01 unit backstop (research risk #2, the sole HIGH — composition,
 * not pass-through). The fixture below carries a decoy `jobTitle`-shaped key
 * that does not exist on the real, `extra="forbid"` `MeData` contract — cast
 * through `unknown` to simulate a hypothetical pass-through bug reintroducing
 * it. The test proves the returned `jobTitle` is sourced from
 * `PERSONA_DISPLAY.cio.jobTitle`, never that decoy value.
 */
describe("composeSignedInUser (OVW-05-AC-6/AC-7, OVW-05-TC-01)", () => {
  it("composes jobTitle from PERSONA_DISPLAY, ignoring a decoy jobTitle-shaped key on the input", () => {
    const decoyMe = {
      name: "Elena Vasquez",
      persona: "cio",
      jobTitle: "Chief Backend Engineer",
    } as unknown as MeData;

    const result = composeSignedInUser(decoyMe);

    expect(result).toEqual({
      name: "Elena Vasquez",
      jobTitle: "Chief Information Officer",
    });
  });

  it("returns undefined when name is null (AC-7) rather than fabricating a name", () => {
    const me: MeData = { name: null, persona: "cio" };

    expect(composeSignedInUser(me)).toBeUndefined();
  });

  it("returns undefined for an unresolvable persona with a known name (D-03, does not throw)", () => {
    const me: MeData = { name: "Devon Rao", persona: "unknown-persona" };

    expect(composeSignedInUser(me)).toBeUndefined();
  });

  it("composes a non-cio valid persona correctly", () => {
    const me: MeData = { name: "Maya Chen", persona: "architect" };

    expect(composeSignedInUser(me)).toEqual({
      name: "Maya Chen",
      jobTitle: "Architect",
    });
  });
});
