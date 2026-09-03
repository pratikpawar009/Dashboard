import { describe, expect, it } from "vitest";

import { PersonaTagError, formatPersonaTag } from "@/lib/formatPersonaTag";

describe("formatPersonaTag", () => {
  it.each([
    { persona: "architect", tag: "Architect", subtitle: "Architect overview" },
    { persona: "developer", tag: "Developer", subtitle: "Developer overview" },
    {
      persona: "product-manager",
      tag: "Product Manager",
      subtitle: "Product Manager overview",
    },
    {
      persona: "engineering-manager",
      tag: "Eng Manager",
      subtitle: "Engineering manager overview",
    },
  ])(
    "resolves $persona to tag '$tag' and subtitle '$subtitle'",
    ({ persona, tag, subtitle }) => {
      const result = formatPersonaTag(persona);
      expect(result.tag).toBe(tag);
      expect(result.subtitle).toBe(subtitle);
    },
  );

  it.each(["cio", "unknown-persona"])(
    "throws PersonaTagError for invalid persona '%s'",
    (persona) => {
      expect(() => formatPersonaTag(persona)).toThrow(PersonaTagError);
    },
  );
});
