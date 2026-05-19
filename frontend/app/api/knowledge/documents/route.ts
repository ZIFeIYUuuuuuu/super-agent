import { buildBackendUrl } from "@/lib/backend";

export async function POST(request: Request) {
  const formData = await request.formData();
  const response = await fetch(buildBackendUrl("/v1/knowledge/documents"), {
    method: "POST",
    body: formData,
    cache: "no-store",
  });

  return new Response(response.body, {
    status: response.status,
    headers: {
      "Content-Type": response.headers.get("content-type") || "application/json",
    },
  });
}
