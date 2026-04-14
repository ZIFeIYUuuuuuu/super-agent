type ApiRequestOptions = Omit<RequestInit, "body"> & {
  body?: BodyInit | null;
  fallbackMessage: string;
};

export type StreamResponse = Response & {
  body: ReadableStream<Uint8Array>;
};

async function readErrorDetail(response: Response, fallbackMessage: string) {
  try {
    const data = (await response.json()) as { detail?: string };
    return data.detail || JSON.stringify(data);
  } catch {
    return response.statusText || fallbackMessage;
  }
}

function mergeHeaders(headers?: HeadersInit, defaults?: HeadersInit) {
  const merged = new Headers(defaults);
  if (!headers) return merged;
  new Headers(headers).forEach((value, key) => merged.set(key, value));
  return merged;
}

export async function request(input: string, options: ApiRequestOptions) {
  const { fallbackMessage, headers, cache = "no-store", ...init } = options;
  const response = await fetch(input, {
    ...init,
    cache,
    headers,
  });

  if (!response.ok) {
    throw new Error(await readErrorDetail(response, fallbackMessage));
  }

  return response;
}

export async function getJson<T>(input: string, fallbackMessage: string, init?: Omit<RequestInit, "method">) {
  const response = await request(input, {
    ...init,
    method: "GET",
    fallbackMessage,
  });
  return (await response.json()) as T;
}

export async function postJson<TResponse>(
  input: string,
  body: unknown,
  fallbackMessage: string,
  init?: Omit<RequestInit, "method" | "body">,
) {
  const response = await request(input, {
    ...init,
    method: "POST",
    body: JSON.stringify(body),
    headers: mergeHeaders(init?.headers, { "Content-Type": "application/json" }),
    fallbackMessage,
  });
  return (await response.json()) as TResponse;
}

export async function postFormData<TResponse>(
  input: string,
  body: FormData,
  fallbackMessage: string,
  init?: Omit<RequestInit, "method" | "body" | "headers">,
) {
  const response = await request(input, {
    ...init,
    method: "POST",
    body,
    fallbackMessage,
  });
  return (await response.json()) as TResponse;
}

export async function postStream(
  input: string,
  body: unknown,
  fallbackMessage: string,
  init?: Omit<RequestInit, "method" | "body">,
): Promise<StreamResponse> {
  const response = await request(input, {
    ...init,
    method: "POST",
    body: JSON.stringify(body),
    headers: mergeHeaders(init?.headers, { "Content-Type": "application/json" }),
    fallbackMessage,
  });

  if (!response.body) {
    throw new Error(fallbackMessage);
  }

  return response as StreamResponse;
}
