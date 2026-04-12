import { buildBackendUrl } from "@/lib/backend";

export const dynamic = "force-dynamic";

export async function GET() {
  const response = await fetch(buildBackendUrl("/v1/knowledge/status"), {
    method: "GET",
    cache: "no-store",
  });

  return new Response(response.body, {
    status: response.status,
    headers: {
      "Content-Type": response.headers.get("content-type") || "application/json",
    },
  });
}
