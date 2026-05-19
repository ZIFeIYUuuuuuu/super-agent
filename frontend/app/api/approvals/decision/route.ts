import { buildBackendUrl } from "@/lib/backend";

export async function POST(request: Request) {
  const body = await request.text();
  const response = await fetch(buildBackendUrl("/v1/approvals/decision"), {
    method: "POST",
    headers: {
      "Content-Type": request.headers.get("content-type") || "application/json",
    },
    body,
    cache: "no-store",
  });

  return new Response(response.body, {
    status: response.status,
    headers: {
      "Content-Type": response.headers.get("content-type") || "application/json",
    },
  });
}
