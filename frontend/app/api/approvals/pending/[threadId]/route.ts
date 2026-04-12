import { buildBackendUrl } from "@/lib/backend";

export const dynamic = "force-dynamic";

type RouteContext = {
  params: Promise<{
    threadId: string;
  }>;
};

export async function GET(_request: Request, context: RouteContext) {
  const { threadId } = await context.params;
  const response = await fetch(
    buildBackendUrl(`/v1/approvals/pending/${encodeURIComponent(threadId)}`),
    {
      method: "GET",
      cache: "no-store",
    },
  );

  return new Response(response.body, {
    status: response.status,
    headers: {
      "Content-Type": response.headers.get("content-type") || "application/json",
    },
  });
}
