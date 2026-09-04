import { fetchProgramDetail } from "@/lib/programDetailApi";
import { ProgramDetailView } from "@/components/ProgramDetailView";

interface PageProps {
  // Next.js 15: `params` is a Promise in Server Components (must be awaited).
  params: Promise<{ program_id: string }>;
}

/**
 * `/programs/[program_id]` (T-13) — Server Component entry point.
 *
 * Performs the initial, server-side fetch (DESIGN.md Screen inventory:
 * "server (initial load)") and hands the result to `ProgramDetailView`,
 * which owns every render after that.
 *
 * No route-level `not-found.tsx`/`error.tsx` exists for this segment, and
 * `notFound()` is never called here: DECISIONS.md D-03 makes the 404 an
 * in-page state rendered by `ProgramDetailView`/`ProgramDetailErrorPanel`,
 * not a Next.js route boundary.
 *
 * Switcher reloads (FR-4, D-07) do not re-enter this Server Component: once
 * mounted, `ProgramDetailView` fetches the new program client-side and
 * updates the URL via `next/navigation`'s `router.replace()`, which is a
 * client-side history update, not a navigation back through this page's
 * server render.
 */
export default async function Page({ params }: PageProps) {
  const { program_id: programId } = await params;
  const result = await fetchProgramDetail(programId);

  return (
    <ProgramDetailView initialProgramId={programId} initialResult={result} />
  );
}
