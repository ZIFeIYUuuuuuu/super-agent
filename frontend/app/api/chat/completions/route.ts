import { buildBackendUrl } from "@/lib/backend";

function copyResponseHeaders(response: Response) {
  const headers = new Headers();
  const contentType = response.headers.get("content-type");
  const threadId = response.headers.get("x-thread-id");

  if (contentType) {
    headers.set("Content-Type", contentType);
  }
  if (threadId) {
    headers.set("X-Thread-Id", threadId);
  }

  headers.set("Cache-Control", "no-cache");
  headers.set("X-Accel-Buffering", "no");
  return headers;
}

export async function POST(request: Request) {
  const body = await request.text();
  const response = await fetch(buildBackendUrl("/v1/chat/completions"), {
    method: "POST",
    headers: {
      "Content-Type": request.headers.get("content-type") || "application/json",
    },
    body,
    cache: "no-store",
  });

  return new Response(response.body, {
    status: response.status,
    headers: copyResponseHeaders(response),
  });
}
