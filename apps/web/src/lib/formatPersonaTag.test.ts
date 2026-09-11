import { describe, expect, it } from "vitest";

import { PersonaTagError, formatPersonaTag } from "@/lib/formatPersonaTag";

describe("formatPersonaTag", () => {
  it.each([
    {
      persona: "architect",
      tag: "Architect",
      subtitle: "Architect overview",
      jobTitle: "Architect",
    },
    {
      persona: "developer",
      tag: "Developer",
      subtitle: "Developer overview",
      jobTitle: "Developer",
    },
    {
      persona: "product-manager",
      tag: "Product Manager",
      subtitle: "Product Manager overview",
      jobTitle: "Product Manager",
    },
    {
      persona: "engineering-manager",
      tag: "Eng Manager",
      subtitle: "Engineering manager overview",
      jobTitle: "Engineering Manager",
    },
    {
      persona: "cio",
      tag: "CIO / CXO",
      subtitle: "Organization-wide AI-in-SDLC adoption, spend & impact",
      jobTitle: "Chief Information Officer",
    },
  ])(
    "resolves $persona to tag '$tag', subtitle '$subtitle', and jobTitle '$jobTitle'",
    ({ persona, tag, subtitle, jobTitle }) => {
      const result = formatPersonaTag(persona);
      expect(result.tag).toBe(tag);
      expect(result.subtitle).toBe(subtitle);
      expect(result.jobTitle).toBe(jobTitle);
    },
  );

  it("throws PersonaTagError for invalid persona 'unknown-persona'", () => {
    expect(() => formatPersonaTag("unknown-persona")).toThrow(PersonaTagError);
  });
});
